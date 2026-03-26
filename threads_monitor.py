"""Threads 社群貼文監控 + AI 情感分析"""
import argparse
import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from html import unescape

import requests

from config import DB_PATH, load_env

# 確保環境變數已載入
load_env()

# ── 預設監控帳號 ─────────────────────────────────────────
WATCH_ACCOUNTS = [
    'leo19790524',      # 蝦米代誌
    # 之後可以加更多 AI/投資 KOL
]

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

REQUEST_DELAY = 5  # 每次請求間隔秒數

# ── DB ────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_threads_db():
    """建立 threads_posts + threads_accounts 資料表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS threads_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            post_id TEXT,
            content TEXT,
            url TEXT UNIQUE,
            likes INTEGER DEFAULT 0,
            replies INTEGER DEFAULT 0,
            ts TEXT,
            analyzed_at TEXT,
            sentiment TEXT,
            score INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS threads_accounts (
            username TEXT PRIMARY KEY,
            alias TEXT,
            added_at TEXT
        )
    """)
    conn.commit()

    # 確保預設帳號存在
    for acct in WATCH_ACCOUNTS:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO threads_accounts (username, added_at) VALUES (?, ?)",
                (acct, datetime.now().isoformat())
            )
        except Exception as e:
            logging.debug("threads_monitor insert skip: %s", e)
            pass
    conn.commit()
    conn.close()


init_threads_db()


def _post_exists(url: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM threads_posts WHERE url=?", (url,)).fetchone()
    conn.close()
    return row is not None


def _insert_post(username, post_id, content, url, likes=0, replies=0, ts=None):
    """插入貼文，回傳是否為新增"""
    if not url or _post_exists(url):
        return False
    conn = get_conn()
    conn.execute(
        """INSERT INTO threads_posts
           (username, post_id, content, url, likes, replies, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (username, post_id, content, url, likes, replies, ts or datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    return True


def get_watch_accounts() -> list[str]:
    """取得所有監控帳號"""
    conn = get_conn()
    rows = conn.execute("SELECT username, alias FROM threads_accounts ORDER BY username").fetchall()
    conn.close()
    return rows


def add_account(username: str, alias: str = None):
    """新增監控帳號"""
    username = username.lstrip('@').strip()
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO threads_accounts (username, alias, added_at) VALUES (?, ?, ?)",
        (username, alias, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()
    print(f"[+] 已新增監控帳號: @{username}" + (f" ({alias})" if alias else ""))


def remove_account(username: str):
    """移除監控帳號"""
    username = username.lstrip('@').strip()
    conn = get_conn()
    conn.execute("DELETE FROM threads_accounts WHERE username=?", (username,))
    conn.commit()
    conn.close()
    print(f"[-] 已移除監控帳號: @{username}")


# ── IG API 取得用戶資訊 ──────────────────────────────────

IG_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
    ),
    'X-IG-App-ID': '238260118697367',
}


def _get_user_id(username: str) -> str | None:
    """透過 IG web_profile_info API 取得 user_id"""
    try:
        r = requests.get(
            f'https://i.instagram.com/api/v1/users/web_profile_info/?username={username}',
            headers=IG_HEADERS, timeout=10, verify=False,
        )
        if r.status_code == 200:
            data = r.json()
            uid = data.get('data', {}).get('user', {}).get('id')
            if uid:
                print(f"  [i] user_id: {uid}")
                return uid
    except Exception as e:
        print(f"  [!] 取得 user_id 失敗: {e}")
    return None


# ── Threads 抓取 ─────────────────────────────────────────

def _extract_meta_content(html: str, property_name: str) -> str | None:
    """從 HTML 中提取 meta tag 的 content"""
    # og:xxx or twitter:xxx
    patterns = [
        rf'<meta\s+property="{property_name}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+property="{property_name}"',
        rf'<meta\s+name="{property_name}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+name="{property_name}"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return unescape(m.group(1))
    return None


def _extract_json_ld(html: str) -> list[dict]:
    """從 HTML 中提取 JSON-LD 資料"""
    results = []
    pattern = r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>'
    for m in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except json.JSONDecodeError:
            pass
    return results


def _extract_post_links(html: str, username: str) -> list[str]:
    """從 profile 頁面 HTML 提取貼文連結"""
    # Threads 貼文 URL 格式: /t/XXXXX 或 /@username/post/XXXXX
    links = set()
    # 格式 1: threads.net/@user/post/XXXX
    for m in re.finditer(rf'https?://(?:www\.)?threads\.net/@{re.escape(username)}/post/([A-Za-z0-9_-]+)', html):
        links.add(f"https://www.threads.net/@{username}/post/{m.group(1)}")
    # 格式 2: /post/XXXX 相對路徑
    for m in re.finditer(rf'/@{re.escape(username)}/post/([A-Za-z0-9_-]+)', html):
        links.add(f"https://www.threads.net/@{username}/post/{m.group(1)}")
    return list(links)


def fetch_profile_page(username: str) -> dict:
    """抓取 Threads 個人頁面，嘗試取得貼文資訊"""
    url = f"https://www.threads.net/@{username}"
    result = {
        'username': username,
        'posts': [],
        'error': None,
    }

    try:
        print(f"  [GET] {url}")
        resp = requests.get(url, headers=HEADERS, timeout=20, verify=False, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        # 1. 嘗試 JSON-LD
        json_ld = _extract_json_ld(html)
        if json_ld:
            print(f"  [i] 找到 {len(json_ld)} 個 JSON-LD 區塊")
            for item in json_ld:
                if item.get('@type') in ('SocialMediaPosting', 'Article', 'BlogPosting'):
                    post = {
                        'content': item.get('articleBody') or item.get('text') or item.get('headline', ''),
                        'url': item.get('url', ''),
                        'ts': item.get('datePublished') or item.get('dateCreated', ''),
                        'likes': 0,
                        'replies': 0,
                    }
                    if item.get('interactionStatistic'):
                        for stat in item.get('interactionStatistic', []):
                            if 'Like' in str(stat.get('interactionType', '')):
                                post['likes'] = stat.get('userInteractionCount', 0)
                            elif 'Comment' in str(stat.get('interactionType', '')):
                                post['replies'] = stat.get('userInteractionCount', 0)
                    if post['content']:
                        result['posts'].append(post)

        # 2. 嘗試 meta tags (og:description 通常包含最新貼文)
        if not result['posts']:
            og_desc = _extract_meta_content(html, 'og:description')
            og_title = _extract_meta_content(html, 'og:title')
            og_url = _extract_meta_content(html, 'og:url')

            if og_desc and len(og_desc) > 10:
                print(f"  [i] 從 meta tags 取得內容 ({len(og_desc)} 字)")
                result['posts'].append({
                    'content': og_desc,
                    'url': og_url or url,
                    'ts': datetime.now().isoformat(),
                    'likes': 0,
                    'replies': 0,
                })

        # 3. 嘗試從頁面抓取貼文連結
        post_links = _extract_post_links(html, username)
        if post_links:
            print(f"  [i] 找到 {len(post_links)} 個貼文連結")
            # 抓取每個貼文頁面（最多 5 個，避免太快被封）
            for link in post_links[:5]:
                if _post_exists(link):
                    continue
                time.sleep(REQUEST_DELAY)
                post_data = fetch_single_post(link, username)
                if post_data:
                    result['posts'].append(post_data)

        if not result['posts']:
            print(f"  [!] 無法從 HTML 解析貼文（Threads 使用 CSR，反爬蟲嚴格）")
            print(f"  [i] HTML 長度: {len(html)} 字元")
            print(f"  [提示] 未來可透過以下方式改善:")
            print(f"         1. Meta 官方 Threads API (需 access token)")
            print(f"         2. Playwright headless browser")
            print(f"         3. 手動用 --fetch-url 抓取特定貼文")

    except requests.exceptions.HTTPError as e:
        result['error'] = f"HTTP {e.response.status_code}"
        print(f"  [!] HTTP 錯誤: {e.response.status_code}")
    except requests.exceptions.ConnectionError as e:
        result['error'] = f"連線失敗: {e}"
        print(f"  [!] 連線失敗")
    except requests.exceptions.Timeout:
        result['error'] = "請求超時"
        print(f"  [!] 請求超時")
    except Exception as e:
        result['error'] = str(e)
        print(f"  [!] 未預期錯誤: {e}")

    return result


def fetch_single_post(post_url: str, username: str) -> dict | None:
    """抓取單一貼文頁面"""
    try:
        print(f"  [GET] {post_url}")
        resp = requests.get(post_url, headers=HEADERS, timeout=20, verify=False, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text

        content = None
        ts = None
        likes = 0
        replies = 0

        # JSON-LD
        json_ld = _extract_json_ld(html)
        for item in json_ld:
            if item.get('@type') in ('SocialMediaPosting', 'Article', 'BlogPosting'):
                content = item.get('articleBody') or item.get('text') or item.get('headline', '')
                ts = item.get('datePublished') or item.get('dateCreated', '')
                for stat in item.get('interactionStatistic', []):
                    if 'Like' in str(stat.get('interactionType', '')):
                        likes = stat.get('userInteractionCount', 0)
                    elif 'Comment' in str(stat.get('interactionType', '')):
                        replies = stat.get('userInteractionCount', 0)
                break

        # Fallback: meta tags
        if not content:
            content = _extract_meta_content(html, 'og:description')
            ts = ts or datetime.now().isoformat()

        if content and len(content) > 5:
            return {
                'content': content,
                'url': post_url,
                'ts': ts or datetime.now().isoformat(),
                'likes': likes,
                'replies': replies,
            }
    except Exception as e:
        print(f"  [!] 抓取貼文失敗: {e}")

    return None


# ── AI 情感分析（複用 intelligence.py） ──────────────────

def _analyze_post(content: str) -> dict | None:
    """呼叫 intelligence.py 的分析函式"""
    try:
        from intelligence import _groq_analyze, _gemini_analyze
        result = _groq_analyze("Threads 貼文", content[:500])
        if not result:
            result = _gemini_analyze("Threads 貼文", content[:500])
        return result
    except Exception as e:
        print(f"  [!] AI 分析失敗: {e}")
        return None


def analyze_unanalyzed(limit: int = 20) -> int:
    """分析未分析的 Threads 貼文"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content FROM threads_posts WHERE sentiment IS NULL AND content IS NOT NULL LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    print(f"[分析] 待分析 {len(rows)} 則 Threads 貼文...")
    analyzed = 0

    for row in rows:
        result = _analyze_post(row['content'])
        conn = get_conn()
        if result:
            conn.execute(
                """UPDATE threads_posts
                   SET sentiment=?, score=?, analyzed_at=?
                   WHERE id=?""",
                (
                    result.get('sentiment', 'neutral'),
                    result.get('score', 5),
                    datetime.now().isoformat(),
                    row['id'],
                )
            )
            analyzed += 1
            print(f"  [{result.get('sentiment')}:{result.get('score')}] {row['content'][:50]}")

            # 同步寫入 news_intelligence 表
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO news_intelligence
                       (title, summary, url, source, sentiment, score, category, keywords, reason, analyzed_at)
                       SELECT 'Threads: ' || username, content, url, 'threads',
                              ?, ?, ?, ?, ?, ?
                       FROM threads_posts WHERE id=?""",
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
            except Exception:
                pass  # news_intelligence 可能已有此 url

            time.sleep(2)
        else:
            conn.execute(
                "UPDATE threads_posts SET sentiment='error', analyzed_at=? WHERE id=?",
                (datetime.now().isoformat(), row['id'])
            )
        conn.commit()
        conn.close()

    return analyzed


# ── 主要流程 ─────────────────────────────────────────────

def fetch_all_accounts() -> int:
    """抓取所有監控帳號的最新貼文，回傳新增數"""
    accounts = get_watch_accounts()
    if not accounts:
        print("[!] 沒有監控帳號，用 --add 新增")
        return 0

    total_new = 0
    for acct in accounts:
        username = acct['username']
        alias = acct['alias'] or ''
        print(f"\n[Threads] 抓取 @{username}" + (f" ({alias})" if alias else "") + " ...")

        result = fetch_profile_page(username)

        new = 0
        for post in result['posts']:
            post_id = post['url'].rstrip('/').split('/')[-1] if post.get('url') else None
            if _insert_post(
                username=username,
                post_id=post_id,
                content=post['content'],
                url=post['url'],
                likes=post.get('likes', 0),
                replies=post.get('replies', 0),
                ts=post.get('ts'),
            ):
                new += 1
                print(f"  [+] {post['content'][:60]}...")

        print(f"  → {len(result['posts'])} 則貼文，新增 {new} 則")
        if result.get('error'):
            print(f"  [!] 錯誤: {result['error']}")

        total_new += new

        # 帳號間延遲
        if acct != accounts[-1]:
            time.sleep(REQUEST_DELAY)

    return total_new


def run_cycle():
    """一次完整的抓取 + 分析循環"""
    print(f"\n{'='*60}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Threads 監控循環")
    print(f"{'='*60}")

    new_count = fetch_all_accounts()
    print(f"\n[收集結果] 新增 {new_count} 則貼文")

    if new_count > 0:
        analyzed = analyze_unanalyzed()
        print(f"[分析結果] 完成 {analyzed} 則分析")

    # 顯示最近貼文
    conn = get_conn()
    rows = conn.execute(
        """SELECT username, content, sentiment, score, ts
           FROM threads_posts
           ORDER BY id DESC LIMIT 5"""
    ).fetchall()
    conn.close()

    if rows:
        print(f"\n--- 最近 Threads 貼文 ---")
        for r in rows:
            sent = f"[{r['sentiment']}:{r['score']}]" if r['sentiment'] else "[未分析]"
            print(f"  @{r['username']} {sent} {(r['content'] or '')[:60]}")

    print(f"{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────

def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parser = argparse.ArgumentParser(description='Threads 社群貼文監控')
    parser.add_argument('--add', type=str, metavar='USERNAME', help='新增監控帳號')
    parser.add_argument('--alias', type=str, help='帳號別名（搭配 --add）')
    parser.add_argument('--remove', type=str, metavar='USERNAME', help='移除監控帳號')
    parser.add_argument('--list', action='store_true', help='列出所有監控帳號')
    parser.add_argument('--daemon', action='store_true', help='每小時自動抓取')
    parser.add_argument('--fetch', type=str, metavar='USERNAME', help='抓取指定帳號')
    args = parser.parse_args()

    if args.list:
        accounts = get_watch_accounts()
        if not accounts:
            print("目前沒有監控帳號")
        else:
            print(f"\n監控帳號清單 ({len(accounts)} 個):")
            for acct in accounts:
                alias = f" ({acct['alias']})" if acct['alias'] else ""
                # 計算該帳號已收集的貼文數
                conn = get_conn()
                count = conn.execute(
                    "SELECT COUNT(*) as c FROM threads_posts WHERE username=?",
                    (acct['username'],)
                ).fetchone()['c']
                conn.close()
                print(f"  @{acct['username']}{alias} — {count} 則貼文")
            print()
        return

    if args.add:
        add_account(args.add, args.alias)
        return

    if args.remove:
        remove_account(args.remove)
        return

    if args.fetch:
        username = args.fetch.lstrip('@').strip()
        print(f"\n[Threads] 抓取 @{username} ...")
        result = fetch_profile_page(username)
        new = 0
        for post in result['posts']:
            post_id = post['url'].rstrip('/').split('/')[-1] if post.get('url') else None
            if _insert_post(
                username=username,
                post_id=post_id,
                content=post['content'],
                url=post['url'],
                likes=post.get('likes', 0),
                replies=post.get('replies', 0),
                ts=post.get('ts'),
            ):
                new += 1
                print(f"  [+] {post['content'][:80]}")
        print(f"\n→ {len(result['posts'])} 則貼文，新增 {new} 則")
        if result.get('error'):
            print(f"[!] 錯誤: {result['error']}")

        if new > 0:
            analyzed = analyze_unanalyzed(limit=new)
            print(f"[分析] 完成 {analyzed} 則")
        return

    if args.daemon:
        print("[Daemon] 每 3600 秒（1 小時）執行一次 (Ctrl+C 停止)")
        while True:
            try:
                run_cycle()
                time.sleep(3600)
            except KeyboardInterrupt:
                print("\n[Daemon] 已停止")
                break
    else:
        run_cycle()


if __name__ == '__main__':
    main()
