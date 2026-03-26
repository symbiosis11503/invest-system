"""市場情報收集 + AI 情感分析模組"""
import argparse
import json
import os
import sqlite3
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from config import DB_PATH, load_env

# 確保環境變數已載入
load_env()

# ── RSS 來源 ──────────────────────────────────────────────
# 2026-03-24: Google News RSS 已封鎖自動抓取（302→400），
# 改用 CNYES/Yahoo/LTN 替代，保留 Google 搜尋作 fallback
RSS_SOURCES = {
    # 台灣財經 — 鉅亨網 (Anue CNYES)
    'cnyes_headline': 'https://news.cnyes.com/rss/v1/news/category/headline',
    'cnyes_tw_stock': 'https://news.cnyes.com/rss/v1/news/category/tw_stock',
    'cnyes_us_stock': 'https://news.cnyes.com/rss/v1/news/category/us_stock',
    'cnyes_forex': 'https://news.cnyes.com/rss/v1/news/category/forex',
    'cnyes_wd_stock': 'https://news.cnyes.com/rss/v1/news/category/wd_stock',
    # Yahoo 台灣股市
    'yahoo_tw_market': 'https://tw.stock.yahoo.com/rss?category=tw-market',
    # 自由時報
    'ltn_business': 'https://news.ltn.com.tw/rss/business.xml',
    'ltn_world': 'https://news.ltn.com.tw/rss/world.xml',
    'ltn_politics': 'https://news.ltn.com.tw/rss/politics.xml',
}

GOOGLE_SEARCH_TEMPLATE = (
    'https://news.google.com/rss/search?q={keyword}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-TW'
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ── DB ────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_intel_db():
    """建立 news_intelligence 資料表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS news_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT,
            url TEXT UNIQUE,
            source TEXT,
            sentiment TEXT,
            score INTEGER,
            category TEXT DEFAULT 'finance',
            keywords TEXT,
            reason TEXT,
            published_at TEXT,
            analyzed_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_intel_db()


def _url_exists(url: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM news_intelligence WHERE url=?", (url,)).fetchone()
    conn.close()
    return row is not None


def _insert_news(title, summary, url, source, published_at):
    if _url_exists(url):
        return False
    conn = get_conn()
    conn.execute(
        "INSERT INTO news_intelligence (title, summary, url, source, published_at) VALUES (?,?,?,?,?)",
        (title, summary or '', url, source, published_at)
    )
    conn.commit()
    conn.close()
    return True


# ── RSS 解析 ──────────────────────────────────────────────

def _fetch_rss(url: str) -> list[dict]:
    """抓取 RSS 並回傳 [{title, summary, url, published_at}]"""
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False,
                            allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] RSS 抓取失敗: {e}")
        return items

    # 檢查是否拿到 HTML 而非 XML（Google 會 redirect 到錯誤頁）
    content_type = resp.headers.get('Content-Type', '')
    if 'html' in content_type and 'xml' not in content_type:
        print(f"  [!] 回傳 HTML 非 RSS（可能被封鎖）")
        return items

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"  [!] XML 解析失敗: {e}")
        return items

    # 支援 RSS 2.0 (<channel><item>)
    for item in root.iter('item'):
        title = item.findtext('title', '').strip()
        link = item.findtext('link', '').strip()
        desc = item.findtext('description', '').strip()
        pub_date = item.findtext('pubDate', '').strip()
        if title and link:
            items.append({
                'title': title,
                'summary': desc[:500] if desc else '',
                'url': link,
                'published_at': pub_date,
            })
    return items


def collect_news(keywords: list[str] | None = None) -> int:
    """抓所有 RSS 來源 + 關鍵字搜尋，回傳新增筆數"""
    total_new = 0

    # 固定來源
    for source_name, url in RSS_SOURCES.items():
        print(f"[RSS] 抓取 {source_name} ...")
        items = _fetch_rss(url)
        new = 0
        for it in items:
            if _insert_news(it['title'], it['summary'], it['url'], source_name, it['published_at']):
                new += 1
        print(f"  → {len(items)} 則，新增 {new} 則")
        total_new += new

    # 關鍵字搜尋
    search_keywords = keywords or [
        # 台灣財經
        '台積電', '台股', '台灣經濟',
        # 全球央行 / 貨幣政策
        '聯準會', 'Fed 利率', '央行 降息',
        # 地緣政治 / 戰爭
        '台海', '台灣海峽', '中國軍演',
        '俄烏戰爭', '以色列', '中東局勢',
        # 亞洲局勢
        '中國經濟', '日本央行', '韓國經濟',
        '東南亞', '印度經濟',
        # 國際經濟
        '美國經濟', '歐洲經濟', '通膨',
        # 商品
        '黃金', '原油', '比特幣',
    ]
    for kw in search_keywords:
        print(f"[RSS] 搜尋關鍵字: {kw} ...")
        url = GOOGLE_SEARCH_TEMPLATE.format(keyword=urllib.parse.quote(kw))
        items = _fetch_rss(url)
        new = 0
        for it in items:
            if _insert_news(it['title'], it['summary'], it['url'], f'google_search:{kw}', it['published_at']):
                new += 1
        print(f"  → {len(items)} 則，新增 {new} 則")
        total_new += new

    return total_new


# ── AI 情感分析（Groq + Gemini 備援） ─────────────────────

_gemini_key_index = 0  # Gemini Key 輪替索引
_engine_stats = {'groq': 0, 'gemini': 0}  # 引擎使用計數


def _build_prompt(title: str, summary: str) -> str:
    """建立情感分析 prompt（Groq / Gemini 共用）"""
    return (
        '你是全球市場情感分析器。分析以下新聞對金融市場的影響。\n'
        '考慮範圍：股市、期貨、黃金、原油、加密貨幣、匯率。\n'
        '地緣政治風險（戰爭、台海、中東）通常利空股市、利多黃金。\n'
        '央行升息利空股市債市、央行降息利多。\n'
        '回覆純 JSON（不要其他文字）：\n'
        '{"sentiment": "bullish/bearish/neutral", "score": 1-10, '
        '"category": "finance/geopolitics/economy/commodity/crypto", '
        '"keywords": ["關鍵字"], "reason": "一句話"}\n\n'
        f'標題：{title}\n摘要：{summary}'
    )


def _groq_analyze(title: str, summary: str) -> dict | None:
    """呼叫 Groq API 做情感分析"""
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        print("  [!] GROQ_API_KEY 未設定，跳過分析")
        return None

    prompt = _build_prompt(title, summary)

    try:
        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.1,
                'max_tokens': 256,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()

        # 嘗試提取 JSON（可能包在 markdown code block 裡）
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        # 追蹤 API 用量到 SBS
        try:
            requests.post('http://localhost:18800/api/usage/track', json={
                'engine': 'groq', 'tokens': len(prompt) // 3 + 256
            }, timeout=3)
        except Exception:
            pass
        return result
    except json.JSONDecodeError:
        print(f"  [!] JSON 解析失敗: {content[:200]}")
        return None
    except Exception as e:
        print(f"  [!] Groq API 錯誤: {e}")
        return None


def _get_gemini_key() -> str | None:
    """從所有 GEMINI_API_KEY* 輪替取得 key（7 keys 分散 rate limit）"""
    global _gemini_key_index
    keys = []
    for suffix in ['', '_APEX', '_ECHO', '_BACKUP', '_B2', '_B3', '_SBS']:
        k = os.environ.get(f'GEMINI_API_KEY{suffix}')
        if k:
            keys.append(k)
    if not keys:
        return None
    key = keys[_gemini_key_index % len(keys)]
    _gemini_key_index += 1
    return key


def _gemini_analyze(title: str, summary: str) -> dict | None:
    """呼叫 Gemini API 做情感分析（Groq 備援）"""
    api_key = _get_gemini_key()
    if not api_key:
        print("  [!] GEMINI_API_KEY 未設定，跳過分析")
        return None

    prompt = _build_prompt(title, summary)

    try:
        resp = requests.post(
            'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent',
            headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'maxOutputTokens': 500, 'thinkingConfig': {'thinkingBudget': 0}},
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

        # 嘗試提取 JSON（多種格式容錯）
        # 1. markdown code block
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()
        # 2. 找第一個 { 和最後一個 }
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1:
            content = content[start:end+1]

        result = json.loads(content)
        # 追蹤 API 用量到 SBS
        try:
            requests.post('http://localhost:18800/api/usage/track', json={
                'engine': 'gemini', 'tokens': len(prompt) // 3 + 500
            }, timeout=3)
        except Exception:
            pass
        return result
    except json.JSONDecodeError:
        print(f"  [!] Gemini JSON 解析失敗: {content[:100]}")
        return None
    except Exception as e:
        err_msg = str(e)
        if 'key=' in err_msg:
            err_msg = err_msg.split('key=')[0] + 'key=***'
        print(f"  [!] Gemini API 錯誤: {err_msg}")
        return None


def analyze_news(limit: int = 50) -> int:
    """對未分析的新聞做 AI 情感分析，回傳分析筆數"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, summary FROM news_intelligence WHERE sentiment IS NULL LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()

    if not rows:
        print("[分析] 沒有待分析的新聞")
        return 0

    print(f"[分析] 待分析 {len(rows)} 則...")
    analyzed = 0
    use_gemini = False  # Groq 429 後切換到 Gemini

    for row in rows:
        engine = None
        result = None

        if not use_gemini:
            result = _groq_analyze(row['title'], row['summary'])
            if result:
                engine = 'groq'
            else:
                # 檢查是否 Groq 429 rate limit，切換到 Gemini
                print("  [→] Groq 失敗，切換到 Gemini 備援")
                use_gemini = True

        if use_gemini and result is None:
            result = _gemini_analyze(row['title'], row['summary'])
            if result:
                engine = 'gemini'

        if result and engine:
            _engine_stats[engine] += 1
            conn = get_conn()
            conn.execute(
                """UPDATE news_intelligence
                   SET sentiment=?, score=?, category=?, keywords=?, reason=?, analyzed_at=?
                   WHERE id=?""",
                (
                    result.get('sentiment', 'neutral'),
                    result.get('score', 5),
                    result.get('category', 'finance'),
                    json.dumps(result.get('keywords', []), ensure_ascii=False),
                    result.get('reason', ''),
                    datetime.now().isoformat(),
                    row['id'],
                )
            )
            conn.commit()
            conn.close()
            analyzed += 1
            print(f"  ✓ [{engine}] [{result.get('sentiment', '?')}:{result.get('score', '?')}] {row['title'][:40]}")
            # Groq 1.5s / Gemini 4s（免費 15次/分鐘，4 key 輪替 = 60次/分鐘）
            time.sleep(1.5 if engine == 'groq' else 4)
        else:
            # 標記為 error 避免重複嘗試
            conn = get_conn()
            conn.execute(
                "UPDATE news_intelligence SET sentiment='error', analyzed_at=? WHERE id=?",
                (datetime.now().isoformat(), row['id'])
            )
            conn.commit()
            conn.close()

    if analyzed > 0:
        print(f"[引擎統計] Groq: {_engine_stats['groq']} 則 / Gemini: {_engine_stats['gemini']} 則")
    return analyzed


# ── 市場情緒摘要 ──────────────────────────────────────────

def get_market_mood(hours: int = 24) -> dict:
    """回傳最近 N 小時的市場情緒摘要"""
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        """SELECT sentiment, score, title, reason
           FROM news_intelligence
           WHERE analyzed_at > ? AND sentiment IN ('bullish', 'bearish', 'neutral')
           ORDER BY analyzed_at DESC""",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return {'total': 0, 'mood': 'unknown', 'message': '無近期分析資料'}

    total = len(rows)
    counts = {'bullish': 0, 'bearish': 0, 'neutral': 0}
    score_sum = 0
    for r in rows:
        counts[r['sentiment']] = counts.get(r['sentiment'], 0) + 1
        score_sum += (r['score'] or 5)

    avg_score = score_sum / total
    dominant = max(counts, key=counts.get)

    return {
        'total': total,
        'bullish': counts['bullish'],
        'bearish': counts['bearish'],
        'neutral': counts['neutral'],
        'avg_score': round(avg_score, 1),
        'mood': dominant,
        'message': (
            f"近 {hours}h 共 {total} 則 | "
            f"看多 {counts['bullish']} / 看空 {counts['bearish']} / 中性 {counts['neutral']} | "
            f"平均分數 {avg_score:.1f}/10 | 主導情緒: {dominant}"
        ),
    }


# ── 搜尋特定關鍵字 ────────────────────────────────────────

def search_keyword(keyword: str) -> int:
    """搜尋特定關鍵字的新聞並分析"""
    print(f"\n=== 搜尋關鍵字: {keyword} ===")
    url = GOOGLE_SEARCH_TEMPLATE.format(keyword=urllib.parse.quote(keyword))
    items = _fetch_rss(url)
    new = 0
    for it in items:
        if _insert_news(it['title'], it['summary'], it['url'], f'google_search:{keyword}', it['published_at']):
            new += 1
    print(f"  → {len(items)} 則，新增 {new} 則")

    # 分析新增的
    if new > 0:
        analyzed = analyze_news(limit=new)
        print(f"  → 分析完成 {analyzed} 則")

    # 顯示該關鍵字相關已分析結果
    conn = get_conn()
    rows = conn.execute(
        """SELECT title, sentiment, score, reason, analyzed_at
           FROM news_intelligence
           WHERE (source LIKE ? OR title LIKE ?)
             AND sentiment IS NOT NULL AND sentiment != 'error'
           ORDER BY analyzed_at DESC LIMIT 10""",
        (f'%{keyword}%', f'%{keyword}%')
    ).fetchall()
    conn.close()

    if rows:
        print(f"\n--- {keyword} 相關新聞 (最近 10 則) ---")
        for r in rows:
            print(f"  [{r['sentiment']}:{r['score']}] {r['title'][:60]}")
            if r['reason']:
                print(f"    → {r['reason']}")
    else:
        print(f"  無 {keyword} 相關的已分析新聞")

    return new


# ── 收集循環 ──────────────────────────────────────────────

def run_cycle():
    """一次完整的收集 + 分析循環"""
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始收集循環")
    print(f"{'='*60}")

    new_count = collect_news()
    print(f"\n[收集結果] 新增 {new_count} 則新聞")

    analyzed = analyze_news()
    print(f"[分析結果] 完成 {analyzed} 則分析")

    mood = get_market_mood()
    print(f"\n[市場情緒] {mood['message']}")
    print(f"{'='*60}\n")

    return {'new_news': new_count, 'analyzed': analyzed, 'mood': mood}


# ── CLI ───────────────────────────────────────────────────

def main():
    # 關閉 requests 的 SSL 警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parser = argparse.ArgumentParser(description='市場情報收集 + AI 分析')
    parser.add_argument('--daemon', action='store_true', help='每 1 分鐘執行一次')
    parser.add_argument('--mood', action='store_true', help='顯示當前市場情緒')
    parser.add_argument('--search', type=str, help='搜尋特定關鍵字新聞')
    args = parser.parse_args()

    if args.mood:
        mood = get_market_mood()
        print(f"\n{mood['message']}\n")
        return

    if args.search:
        search_keyword(args.search)
        return

    if args.daemon:
        print("[Daemon] 每 60 秒執行一次收集循環 (Ctrl+C 停止)")
        while True:
            try:
                run_cycle()
                time.sleep(60)
            except KeyboardInterrupt:
                print("\n[Daemon] 已停止")
                break
    else:
        run_cycle()


if __name__ == '__main__':
    main()
