"""
每日市場摘要報告生成器
- 市場情緒總覽
- 各市場昨日行情
- 策略訊號
- 重要新聞摘要
- 可推播到 Telegram
"""
import json
import os
import sqlite3
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import requests

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH, load_env

load_env()


# ── AI 市場總結 & 技術面情境 ──────────────────────────────

def _get_technical_snapshot():
    """從 market_data 計算主要市場的 RSI(14) 和 MA(5/20/60)"""
    conn = get_conn()
    key_symbols = {'^TWII': '台灣加權', '^GSPC': 'S&P500', 'GC=F': '黃金', 'BTC-USD': '比特幣'}
    snapshots = []
    for sym, name in key_symbols.items():
        rows = conn.execute(
            "SELECT close FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 60",
            (sym,)
        ).fetchall()
        if len(rows) < 14:
            continue
        closes = [r['close'] for r in rows][::-1]  # 由舊到新
        # RSI 14
        gains, losses = [], []
        for i in range(1, min(15, len(closes))):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / 14 if gains else 0
        avg_loss = sum(losses) / 14 if losses else 0.0001
        rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss else 100

        latest = closes[-1]
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else latest
        ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else latest
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else latest

        snapshots.append({
            'symbol': sym, 'name': name, 'close': latest,
            'rsi': round(rsi, 1), 'ma5': round(ma5, 2),
            'ma20': round(ma20, 2), 'ma60': round(ma60, 2),
        })
    conn.close()
    return snapshots


def _describe_technical(snapshots):
    """用規則把技術指標轉成文字描述"""
    lines = []
    for s in snapshots:
        parts = []
        # RSI 描述
        if s['rsi'] > 70:
            parts.append(f"RSI {s['rsi']} 超買區")
        elif s['rsi'] < 30:
            parts.append(f"RSI {s['rsi']} 超賣區")
        else:
            parts.append(f"RSI {s['rsi']} 中性")
        # MA 趨勢
        if s['close'] > s['ma5'] > s['ma20']:
            parts.append("短中期均線多頭排列")
        elif s['close'] < s['ma5'] < s['ma20']:
            parts.append("短中期均線空頭排列")
        elif s['close'] > s['ma20'] and s['close'] < s['ma5']:
            parts.append("短線回檔但中期趨勢仍上")
        elif s['close'] < s['ma20'] and s['close'] > s['ma5']:
            parts.append("短線反彈但中期趨勢仍弱")
        else:
            parts.append("均線糾結，方向不明")
        # 60 日均線判斷
        if s['close'] > s['ma60']:
            parts.append("站穩季線之上")
        else:
            parts.append("跌破季線")
        lines.append(f"• {s['name']}: {'，'.join(parts)}")
    return lines


def _call_groq(prompt: str) -> str | None:
    """呼叫 Groq API 生成文字"""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        return None
    try:
        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.3,
                'max_tokens': 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"  [!] Groq 市場總結失敗: {e}")
        return None


def _call_gemini(prompt: str) -> str | None:
    """呼叫 Gemini API 生成文字（Groq 備援）"""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        resp = requests.post(
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent',
            headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
            json={'contents': [{'parts': [{'text': prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        err_msg = str(e)
        if 'key=' in err_msg:
            err_msg = err_msg.split('key=')[0] + 'key=***'
        print(f"  [!] Gemini 市場總結失敗: {err_msg}")
        return None


def _generate_ai_market_summary(mood, snapshots, strategies):
    """
    用 AI 生成一句話市場總結 + 技術面情境描述。
    Groq 優先 → Gemini 備援 → 規則 fallback。
    """
    # 構建 prompt 素材
    bull_pct = 0
    if mood and mood.get('total', 0) > 0:
        bull_pct = round(mood.get('bullish', 0) / mood['total'] * 100)
    bear_pct = 0
    if mood and mood.get('total', 0) > 0:
        bear_pct = round(mood.get('bearish', 0) / mood['total'] * 100)

    tech_text = '\n'.join(_describe_technical(snapshots)) if snapshots else '無技術面數據'
    strat_text = ', '.join(
        f"{s['symbol']}最佳策略:{s['strategy']}(報酬{s['return']:+.1f}%)"
        for s in (strategies or [])
    ) or '無策略數據'

    prompt = f"""你是一位專業的金融市場分析師。根據以下今天的數據，用繁體中文：
1. 先用「一句話」總結今天市場狀況（30字以內，開頭不要有標點）
2. 再用 2-3 句話描述技術面情境：目前是趨勢延續、趨勢轉弱、情緒性修正、還是觸底反彈？

數據：
- 新聞情緒：看多 {bull_pct}% / 看空 {bear_pct}%（共 {mood.get('total', 0) if mood else 0} 則）
- 技術面：
{tech_text}
- 策略信號：{strat_text}

格式：
一句話總結：<你的總結>
技術面情境：<你的描述>

注意：直接回答，不要加多餘的前綴或解釋。"""

    # 嘗試 Groq → Gemini → 規則
    ai_text = _call_groq(prompt)
    if not ai_text:
        ai_text = _call_gemini(prompt)

    if ai_text:
        return ai_text

    # fallback: 規則生成
    if bull_pct > 60:
        summary = "市場情緒偏多，多數新聞釋出正面訊號"
    elif bear_pct > 60:
        summary = "市場情緒偏空，負面消息主導"
    else:
        summary = "多空分歧，市場觀望氣氛濃厚"

    tech_lines = _describe_technical(snapshots) if snapshots else ["• 無技術面數據"]
    return f"一句話總結：{summary}\n技術面情境：\n" + '\n'.join(tech_lines)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_market_summary():
    """取得各市場最新行情"""
    conn = get_conn()
    symbols = {
        '^TWII': '台灣加權',
        '^GSPC': 'S&P500',
        '^IXIC': 'NASDAQ',
        '^N225': '日經225',
        '^HSI': '恆生',
        'GC=F': '黃金',
        'CL=F': '原油(WTI)',
        'NG=F': '天然氣',
        'HG=F': '銅',
        'BTC-USD': '比特幣',
        'USDTWD=X': '美元/台幣',
        'ZB=F': '30年美債',
    }

    results = []
    for sym, name in symbols.items():
        rows = conn.execute(
            "SELECT date, open, close, high, low, volume FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 2",
            (sym,)
        ).fetchall()
        if len(rows) >= 2:
            today = dict(rows[0])
            yesterday = dict(rows[1])
            change = today['close'] - yesterday['close']
            change_pct = (change / yesterday['close'] * 100) if yesterday['close'] else 0
            results.append({
                'symbol': sym,
                'name': name,
                'date': today['date'],
                'close': today['close'],
                'change': change,
                'change_pct': change_pct,
                'high': today['high'],
                'low': today['low'],
                'volume': today['volume'],
            })
        elif len(rows) == 1:
            today = dict(rows[0])
            results.append({
                'symbol': sym,
                'name': name,
                'date': today['date'],
                'close': today['close'],
                'change': 0,
                'change_pct': 0,
                'high': today['high'],
                'low': today['low'],
                'volume': today['volume'],
            })
    conn.close()
    return results


def get_mood_summary():
    """取得市場情緒摘要"""
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    row = conn.execute("""
        SELECT
            COUNT(CASE WHEN sentiment='bullish' THEN 1 END) as bullish,
            COUNT(CASE WHEN sentiment='bearish' THEN 1 END) as bearish,
            COUNT(CASE WHEN sentiment='neutral' THEN 1 END) as neutral,
            AVG(CASE WHEN score > 0 THEN score END) as avg_score,
            COUNT(*) as total
        FROM news_intelligence
        WHERE analyzed_at > ? AND sentiment IN ('bullish','bearish','neutral')
    """, (cutoff,)).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_top_news(limit=10):
    """取得最重要的新聞（按 score 排序）"""
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    rows = conn.execute("""
        SELECT title, sentiment, score, category, reason
        FROM news_intelligence
        WHERE analyzed_at > ? AND sentiment IN ('bullish','bearish','neutral')
        ORDER BY score DESC
        LIMIT ?
    """, (cutoff, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_institutional_summary():
    """取得法人最新買賣超摘要（最近交易日）"""
    conn = get_conn()
    try:
        # 找最近的交易日
        latest = conn.execute(
            "SELECT MAX(date) FROM tw_institutional"
        ).fetchone()[0]
        if not latest:
            conn.close()
            return []

        rows = conn.execute("""
            SELECT symbol, foreign_net, trust_net, dealer_net, total_net
            FROM tw_institutional WHERE date = ?
            ORDER BY ABS(total_net) DESC LIMIT 10
        """, (latest,)).fetchall()
        conn.close()
        return [dict(r) | {'date': latest} for r in rows]
    except Exception:
        conn.close()
        return []


def get_broker_summary():
    """取得分點主力摘要（今日最新）"""
    conn = get_conn()
    try:
        # 檢查 table 是否存在
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tw_broker_trading'"
        ).fetchone()
        if not table_exists:
            conn.close()
            return []

        latest = conn.execute(
            "SELECT MAX(fetch_date) FROM tw_broker_trading"
        ).fetchone()[0]
        if not latest:
            conn.close()
            return []

        # 取各股近1日 (period=1) 買超第一名
        rows = conn.execute("""
            SELECT stock_id, broker_name, net_qty, pct
            FROM tw_broker_trading
            WHERE fetch_date = ? AND period = 1 AND side = 'buy' AND rank = 1
            ORDER BY ABS(net_qty) DESC LIMIT 6
        """, (latest,)).fetchall()
        conn.close()
        return [dict(r) | {'date': latest} for r in rows]
    except Exception:
        conn.close()
        return []


def get_best_strategies():
    """取得各市場最佳策略"""
    conn = get_conn()
    symbols = ['GC=F', 'TX_TX', 'BTC-USD', '^GSPC']
    results = []
    for sym in symbols:
        row = conn.execute("""
            SELECT strategy, total_return, sharpe_ratio, win_rate
            FROM backtest_results WHERE symbol=?
            ORDER BY total_return DESC LIMIT 1
        """, (sym,)).fetchone()
        if row:
            results.append({
                'symbol': sym,
                'strategy': dict(row)['strategy'],
                'return': dict(row)['total_return'],
                'sharpe': dict(row)['sharpe_ratio'],
            })
    conn.close()
    return results


def generate_report():
    """產生每日報告文字"""
    now = datetime.now()
    report = []
    report.append(f"📊 SBS 每日市場報告")
    report.append(f"📅 {now.strftime('%Y-%m-%d %H:%M')}")
    report.append("=" * 35)

    # AI 市場總結（最前面）
    try:
        mood = get_mood_summary()
        snapshots = _get_technical_snapshot()
        strategies = get_best_strategies()
        ai_summary = _generate_ai_market_summary(mood, snapshots, strategies)
        if ai_summary:
            report.append("\n🤖 AI 市場總結")
            report.append("─" * 35)
            for line in ai_summary.strip().split('\n'):
                report.append(line)
    except Exception:
        traceback.print_exc()
        report.append("\n🤖 AI 市場總結：生成失敗")

    # 泡沫指標
    try:
        conn = get_conn()
        bubble_indicators = []
        symbols = {'^VIX': 'VIX', 'HG=F': '銅', 'GC=F': '金', 'USDTWD=X': 'TWD', '^TNX': '10Y殖利率', 'BTC-USD': 'BTC'}
        for sym, name in symbols.items():
            row = conn.execute("SELECT close FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
            if row:
                bubble_indicators.append(f"{name}: {row['close']:,.2f}")
        conn.close()
        if bubble_indicators:
            report.append("\n🫧 泡沫指標")
            report.append("─" * 35)
            # VIX 燈號
            for sym_data in bubble_indicators:
                report.append(f"• {sym_data}")
    except Exception:
        pass

    # 市場行情
    markets = get_market_summary()
    if markets:
        report.append("\n📈 市場行情")
        report.append("─" * 35)
        for m in markets:
            arrow = "🔴" if m['change'] >= 0 else "🟢"
            report.append(
                f"{arrow} {m['name']}: {m['close']:,.2f} "
                f"({m['change_pct']:+.2f}%)"
            )

    # 市場情緒
    mood = get_mood_summary()
    if mood and mood.get('total', 0) > 0:
        total = mood['total']
        bull = mood.get('bullish', 0)
        bear = mood.get('bearish', 0)
        neut = mood.get('neutral', 0)
        avg = mood.get('avg_score', 5) or 5

        if bull > bear:
            emoji = "🟢"
            label = "偏多"
        elif bear > bull:
            emoji = "🔴"
            label = "偏空"
        else:
            emoji = "⚪"
            label = "中性"

        report.append(f"\n{emoji} 市場情緒: {label}")
        report.append("─" * 35)
        report.append(f"看多 {bull} / 看空 {bear} / 中性 {neut}")
        report.append(f"情緒分數: {avg:.1f}/10 ({total} 則新聞)")

    # 重要新聞
    news = get_top_news(5)
    if news:
        report.append("\n📰 重要新聞 Top 5")
        report.append("─" * 35)
        for i, n in enumerate(news, 1):
            s_emoji = "🔴" if n['sentiment'] == 'bullish' else "🟢" if n['sentiment'] == 'bearish' else "⚪"
            report.append(f"{i}. {s_emoji}[{n['score']}] {n['title'][:40]}")
            if n.get('reason'):
                report.append(f"   → {n['reason'][:50]}")

    # 法人動向
    inst = get_institutional_summary()
    if inst:
        report.append(f"\n🏦 法人動向 ({inst[0]['date']})")
        report.append("─" * 35)
        for r in inst[:6]:
            net = r['total_net']
            arrow = "🔴" if net > 0 else "🟢" if net < 0 else "⚪"
            fn = f"外{r['foreign_net']:+,}" if r['foreign_net'] else ""
            tn = f"投{r['trust_net']:+,}" if r['trust_net'] else ""
            report.append(f"{arrow} {r['symbol']}: {net:+,} ({fn} {tn})")

    # 分點主力
    broker = get_broker_summary()
    if broker:
        report.append(f"\n🔍 分點主力 ({broker[0]['date']})")
        report.append("─" * 35)
        for b in broker:
            report.append(f"• {b['stock_id']}: {b['broker_name']} 淨買超 {b['net_qty']:+,} ({b['pct']})")

    # 最佳策略
    strategies = get_best_strategies()
    if strategies:
        report.append("\n🏆 最佳策略")
        report.append("─" * 35)
        for s in strategies:
            name = s['strategy'].split('|')[0] if '|' in s['strategy'] else s['strategy']
            report.append(f"• {s['symbol']}: {name} ({s['return']:+.1f}%)")

    report.append("\n" + "=" * 35)
    report.append("Symbiosis Investment System")

    return "\n".join(report)


def send_telegram(text):
    """推播到 Telegram"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_ALLOWED_USERS')
    if not bot_token or not chat_id:
        print("[!] Telegram 未設定，跳過推播")
        return False

    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    resp = requests.post(url, json={
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
    })
    if resp.ok:
        print("[✓] 已推播到 Telegram")
        return True
    else:
        print(f"[!] Telegram 推播失敗: {resp.text[:200]}")
        return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='每日市場摘要報告')
    parser.add_argument('--send', action='store_true', help='推播到 Telegram')
    parser.add_argument('--html', action='store_true', help='輸出 HTML 格式')
    args = parser.parse_args()

    report = generate_report()
    print(report)

    if args.send:
        send_telegram(report)
