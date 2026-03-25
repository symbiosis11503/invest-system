"""
X/Twitter 監控模組 — Grok API 搜尋 + Nitter RSS 備援

使用方式：
  python x_monitor.py                  — 完整爬取 + AI 摘要
  python x_monitor.py --topic "台積電"  — 搜尋特定主題
  python x_monitor.py --trending        — 只看趨勢
  python x_monitor.py --summary         — 顯示最近摘要
  python x_monitor.py --daemon          — 每小時自動執行
"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

from config import DB_PATH, load_env

load_env()

# ── 設定 ──────────────────────────────────────────────────

XAI_API_KEY = os.environ.get('XAI_API_KEY', '')
XAI_API_URL = 'https://api.x.ai/v1/chat/completions'
GROK_MODEL = 'grok-3-latest'

SEARCH_TOPICS = [
    # 台灣
    '台股 台灣股市',
    '台積電 TSMC',
    '台海 兩岸',
    # 全球財經
    '全球經濟 global economy',
    '加密貨幣 crypto Bitcoin',
    # 地緣政治
    '中東 Iran war',
    '俄烏 Russia Ukraine',
    # 商品
    'gold 黃金',
    'oil 原油',
    # 科技趨勢
    'AI artificial intelligence 人工智慧',
    'Apple Google Meta 科技巨頭',
    # 網路熱門 / 社會話題
    'trending viral 爆紅 熱門',
    'meme 迷因 網路梗',
    '日本 韓國 流行文化 pop culture',
    '健康 fitness 生活',
    '新奇 科學 太空 space',
]

NITTER_INSTANCES = [
    'https://nitter.privacydev.net',
    'https://nitter.poast.org',
]

WATCH_ACCOUNTS = [
    'elonmusk', 'realDonaldTrump', 'business', 'Reuters',
    'Bloomberg', 'CNBC', 'WSJ', 'CoinDesk',
]

# ── DB ────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建立 x_posts 與 x_summaries 表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS x_posts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,
            topic       TEXT,
            author      TEXT,
            content     TEXT,
            sentiment   TEXT,
            engagement  TEXT,
            url         TEXT,
            content_hash TEXT UNIQUE,
            ts          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_x_posts_ts ON x_posts (ts)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS x_summaries (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            summary TEXT NOT NULL,
            post_count INTEGER,
            ts      TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


init_db()


def _content_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode()).hexdigest()


def _insert_post(source: str, topic: str, author: str, content: str,
                 sentiment: str = '', engagement: str = '', url: str = '') -> bool:
    """插入推文，回傳是否為新資料"""
    h = _content_hash(content)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO x_posts (source, topic, author, content, sentiment, engagement, url, content_hash, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, topic, author, content, sentiment, engagement, url, h,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # 重複
    finally:
        conn.close()


# ── Grok API ─────────────────────────────────────────────

def _grok_request(prompt: str) -> str | None:
    """呼叫 Grok API，回傳文字回應"""
    if not XAI_API_KEY:
        print('[!] XAI_API_KEY 未設定')
        return None

    try:
        resp = requests.post(
            XAI_API_URL,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {XAI_API_KEY}',
            },
            json={
                'model': GROK_MODEL,
                'messages': [
                    {'role': 'system', 'content': '你是 X/Twitter 資訊搜尋助手。請搜尋 X 上的即時內容並回傳結果。'},
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': 0.3,
                'search': True,  # 啟用 Grok 搜尋功能
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content']
        # 追蹤 API 用量
        try:
            requests.post('http://localhost:18800/api/usage/track', json={
                'engine': 'grok', 'tokens': data.get('usage', {}).get('total_tokens', 0)
            }, timeout=3)
        except Exception:
            pass
        return content
    except requests.exceptions.HTTPError as e:
        print(f'[!] Grok API HTTP 錯誤: {e}')
        if hasattr(e, 'response') and e.response is not None:
            print(f'    回應: {e.response.text[:300]}')
        return None
    except Exception as e:
        print(f'[!] Grok API 錯誤: {e}')
        return None


def search_x_trending(topic: str | None = None) -> list[dict]:
    """用 Grok API 搜尋 X 上的熱門內容"""
    if topic:
        prompt = (
            f'搜尋 X/Twitter 上關於「{topic}」最近 24 小時的熱門推文和討論。\n'
            f'回傳純 JSON 陣列（不要其他文字）：\n'
            f'[{{"author": "帳號", "content": "推文內容摘要", "engagement": "互動量描述", '
            f'"sentiment": "positive/negative/neutral", "url": "推文連結(如果有)"}}]\n'
            f'至少列出 10 則。'
        )
    else:
        prompt = (
            '搜尋 X/Twitter 上最近 24 小時全球最熱門的話題和討論。\n'
            '涵蓋：科技、金融、地緣政治、加密貨幣等領域。\n'
            '回傳純 JSON 陣列（不要其他文字）：\n'
            '[{"author": "帳號", "content": "推文內容摘要", "engagement": "互動量描述", '
            '"sentiment": "positive/negative/neutral", "url": "推文連結(如果有)"}]\n'
            '至少列出 15 則。'
        )

    print(f'[Grok] 搜尋: {topic or "全球趨勢"}...')
    raw = _grok_request(prompt)
    if not raw:
        return []

    # 解析 JSON
    posts = _parse_json_array(raw)
    if not posts:
        print(f'[!] Grok 回傳無法解析為 JSON，原始回應前 200 字:')
        print(f'    {raw[:200]}')
        return []

    # 存入 DB
    new_count = 0
    for p in posts:
        is_new = _insert_post(
            source='grok',
            topic=topic or 'trending',
            author=p.get('author', ''),
            content=p.get('content', ''),
            sentiment=p.get('sentiment', ''),
            engagement=p.get('engagement', ''),
            url=p.get('url', ''),
        )
        if is_new:
            new_count += 1

    print(f'[Grok] {topic or "趨勢"}: 取得 {len(posts)} 則，新增 {new_count} 則')
    return posts


def _parse_json_array(text: str) -> list[dict] | None:
    """從文字中提取 JSON 陣列，容錯多種格式"""
    text = text.strip()

    # 移除 markdown code block
    if '```' in text:
        parts = text.split('```')
        for part in parts:
            part = part.strip()
            if part.startswith('json'):
                part = part[4:].strip()
            if part.startswith('['):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue

    # 直接解析
    if text.startswith('['):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 找第一個 [ 和最後一個 ]
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ── Nitter RSS 備援 ──────────────────────────────────────

def fetch_nitter_rss() -> list[dict]:
    """從 Nitter RSS 抓取推文"""
    all_posts = []
    for account in WATCH_ACCOUNTS:
        fetched = False
        for instance in NITTER_INSTANCES:
            url = f'{instance}/{account}/rss'
            try:
                resp = requests.get(url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; InvestBot/1.0)'
                })
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                items = root.findall('.//item')
                new_count = 0
                for item in items:
                    title = item.findtext('title', '')
                    link = item.findtext('link', '')
                    pub_date = item.findtext('pubDate', '')
                    desc = item.findtext('description', '')

                    content = title or desc
                    if not content:
                        continue

                    is_new = _insert_post(
                        source='nitter',
                        topic='',
                        author=account,
                        content=content[:500],
                        url=link or '',
                    )
                    if is_new:
                        new_count += 1
                        all_posts.append({
                            'author': account,
                            'content': content[:500],
                            'url': link,
                        })

                print(f'[Nitter] @{account}: {len(items)} 則，新增 {new_count} 則 ({instance})')
                fetched = True
                break  # 成功就不試下一個 instance

            except Exception as e:
                continue  # 換下一個 instance

        if not fetched:
            print(f'[Nitter] @{account}: 所有實例失敗，跳過')

    return all_posts


# ── Gemini 摘要 ──────────────────────────────────────────

_gemini_key_index = 0


def _get_gemini_key() -> str | None:
    global _gemini_key_index
    keys = []
    for suffix in ['', '_APEX', '_ECHO', '_BACKUP', '_B2', '_B3']:
        k = os.environ.get(f'GEMINI_API_KEY{suffix}')
        if k:
            keys.append(k)
    if not keys:
        return None
    key = keys[_gemini_key_index % len(keys)]
    _gemini_key_index += 1
    return key


def generate_summary(posts: list[dict]) -> str | None:
    """用 Gemini 產生 X 輿情日報"""
    if not posts:
        print('[!] 沒有推文可摘要')
        return None

    api_key = _get_gemini_key()
    if not api_key:
        print('[!] GEMINI_API_KEY 未設定，跳過摘要')
        return None

    # 組合推文內容
    lines = []
    for i, p in enumerate(posts[:100], 1):  # 最多取 100 則
        author = p.get('author', '?')
        content = p.get('content', '')
        sentiment = p.get('sentiment', '')
        lines.append(f'{i}. @{author}: {content} [{sentiment}]')

    posts_text = '\n'.join(lines)

    prompt = (
        '以下是 X/Twitter 上最近的熱門討論：\n\n'
        f'{posts_text}\n\n'
        '請用繁體中文整理一份 500 字以內的「X/Twitter 網路輿情日報」。\n'
        '格式要求：\n'
        '1. 先列出 3-5 個最重要的趨勢/話題\n'
        '2. 每個話題簡述內容和社群反應\n'
        '3. 最後給出整體市場情緒判斷（偏多/偏空/中性）\n'
        '4. 用 Markdown 格式'
    )

    print('[Gemini] 產生輿情摘要...')
    try:
        resp = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'maxOutputTokens': 2000, 'thinkingConfig': {'thinkingBudget': 0}},
            },
            timeout=60,
        )
        resp.raise_for_status()
        summary = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()

        # 存入 DB
        conn = get_conn()
        conn.execute(
            "INSERT INTO x_summaries (summary, post_count, ts) VALUES (?, ?, ?)",
            (summary, len(posts), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()

        # 追蹤用量
        try:
            requests.post('http://localhost:18800/api/usage/track', json={
                'engine': 'gemini', 'tokens': len(prompt) // 3 + 1000
            }, timeout=3)
        except Exception:
            pass

        return summary

    except Exception as e:
        err_msg = str(e)
        if 'key=' in err_msg:
            err_msg = err_msg.split('key=')[0] + 'key=***'
        print(f'[!] Gemini 摘要錯誤: {err_msg}')
        return None


# ── 主要流程 ─────────────────────────────────────────────

def run_full(topics: list[str] | None = None):
    """完整爬取 + 摘要"""
    all_posts = []

    # 1. Grok 搜尋
    target_topics = topics or SEARCH_TOPICS
    for topic in target_topics:
        posts = search_x_trending(topic)
        all_posts.extend(posts)
        time.sleep(2)  # 避免 rate limit

    # 2. Nitter RSS 備援
    print('\n--- Nitter RSS 備援 ---')
    nitter_posts = fetch_nitter_rss()
    all_posts.extend(nitter_posts)

    # 3. AI 摘要
    print(f'\n--- 共收集 {len(all_posts)} 則推文 ---')
    if all_posts:
        summary = generate_summary(all_posts)
        if summary:
            print('\n' + '=' * 60)
            print('X/Twitter 輿情日報')
            print('=' * 60)
            print(summary)
            print('=' * 60)

    return all_posts


def run_topic(topic: str):
    """搜尋特定主題"""
    posts = search_x_trending(topic)
    if posts:
        print(f'\n--- @{topic} 相關推文 ({len(posts)} 則) ---')
        for i, p in enumerate(posts, 1):
            author = p.get('author', '?')
            content = p.get('content', '')
            sentiment = p.get('sentiment', '')
            print(f'  {i}. @{author}: {content[:80]}  [{sentiment}]')
    return posts


def run_trending():
    """只看全球趨勢"""
    posts = search_x_trending()
    if posts:
        print(f'\n--- 全球趨勢 ({len(posts)} 則) ---')
        for i, p in enumerate(posts, 1):
            author = p.get('author', '?')
            content = p.get('content', '')
            sentiment = p.get('sentiment', '')
            print(f'  {i}. @{author}: {content[:80]}  [{sentiment}]')
    return posts


def show_summary():
    """顯示最近的摘要"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM x_summaries ORDER BY ts DESC LIMIT 5"
    ).fetchall()
    conn.close()

    if not rows:
        print('[i] 尚無摘要，請先執行完整爬取')
        return

    for row in rows:
        print(f'\n{"=" * 60}')
        print(f'時間: {row["ts"]} | 推文數: {row["post_count"]}')
        print('=' * 60)
        print(row['summary'])


def run_daemon(interval: int = 3600):
    """每隔 interval 秒自動執行"""
    print(f'[daemon] 啟動，每 {interval} 秒執行一次（Ctrl+C 停止）')
    while True:
        try:
            print(f'\n[daemon] {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} 開始爬取...')
            run_full()
            print(f'[daemon] 完成，下次執行: {(datetime.now() + timedelta(seconds=interval)).strftime("%H:%M:%S")}')
            time.sleep(interval)
        except KeyboardInterrupt:
            print('\n[daemon] 停止')
            break
        except Exception as e:
            print(f'[!] daemon 錯誤: {e}')
            time.sleep(60)  # 錯誤後等 1 分鐘再試


# ── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='X/Twitter 監控模組')
    parser.add_argument('--topic', type=str, help='搜尋特定主題')
    parser.add_argument('--trending', action='store_true', help='只看全球趨勢')
    parser.add_argument('--summary', action='store_true', help='顯示最近摘要')
    parser.add_argument('--daemon', action='store_true', help='每小時自動執行')
    parser.add_argument('--interval', type=int, default=3600, help='daemon 間隔秒數 (預設 3600)')

    args = parser.parse_args()

    if args.summary:
        show_summary()
    elif args.trending:
        run_trending()
    elif args.topic:
        run_topic(args.topic)
    elif args.daemon:
        run_daemon(args.interval)
    else:
        run_full()


if __name__ == '__main__':
    main()
