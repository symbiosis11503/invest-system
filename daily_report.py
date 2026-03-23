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
from datetime import datetime, timedelta
from pathlib import Path

import requests

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH, load_env

load_env()


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
