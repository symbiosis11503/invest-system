"""PTT 股版爬蟲 — 收集文章 + 情緒分析"""
import argparse
import re
import sqlite3
import time
from datetime import datetime, timedelta

import requests
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from config import DB_PATH

PTT_BASE = "https://www.ptt.cc"
PTT_STOCK_URL = f"{PTT_BASE}/bbs/Stock/index.html"

# 用 Session 管理 cookie，避免 Connection Reset
_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
})
_session.cookies.set('over18', '1', domain='.ptt.cc')
_session.verify = False  # PTT SSL 有時有問題

# 關閉 SSL 警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 保留 HEADERS 給不用 session 的場合（相容）
HEADERS = {
    'User-Agent': _session.headers['User-Agent'],
    'Cookie': 'over18=1',
}

# 情緒關鍵詞
BULLISH_KEYWORDS = ['多', '噴', '利多', '大漲', '起飛', '突破', '強勢', '紅的', '上看', '噴出']
BEARISH_KEYWORDS = ['空', '崩', '利空', '大跌', '崩盤', '跳水', '弱勢', '綠的', '下看', '套牢', 'GG']

# 分類對應
CATEGORY_MAP = {
    '標的': '標的',
    '新聞': '新聞',
    '請益': '請益',
    '閒聊': '閒聊',
    '心得': '心得',
    '情報': '情報',
    '其他': '其他',
}


# ── DB ────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_ptt_table():
    """建立 ptt_posts 表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ptt_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            author TEXT,
            date TEXT,
            push_count INTEGER DEFAULT 0,
            boo_count INTEGER DEFAULT 0,
            arrow_count INTEGER DEFAULT 0,
            content_preview TEXT,
            category TEXT,
            sentiment TEXT,
            score REAL,
            crawled_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


init_ptt_table()


def _url_exists(url: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM ptt_posts WHERE url=?", (url,)).fetchone()
    conn.close()
    return row is not None


# ── 解析文章列表 ──────────────────────────────────────────

def _parse_push_count(nrec_text: str) -> int:
    """解析推文數：數字/爆/X* → int"""
    nrec_text = nrec_text.strip()
    if not nrec_text:
        return 0
    if nrec_text == '爆':
        return 100
    if nrec_text.startswith('X'):
        try:
            return -int(nrec_text[1:]) if len(nrec_text) > 1 else -10
        except ValueError:
            return -10
    try:
        return int(nrec_text)
    except ValueError:
        return 0


def _extract_category(title: str) -> str:
    """從標題提取分類 [標的]/[新聞] 等"""
    m = re.match(r'\[(.+?)\]', title)
    if m:
        cat = m.group(1)
        for key in CATEGORY_MAP:
            if key in cat:
                return CATEGORY_MAP[key]
    return '其他'


def _fetch_article_list(url: str) -> tuple[list[dict], str | None]:
    """抓取一頁文章列表，回傳 (articles, prev_page_url)"""
    articles = []
    prev_url = None

    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] 抓取列表失敗: {e}")
        return articles, prev_url

    soup = BeautifulSoup(resp.text, 'html.parser')

    # 上一頁連結
    paging = soup.select('.btn-group-paging a')
    for a in paging:
        if '上頁' in a.text:
            prev_url = PTT_BASE + a['href']
            break

    # 文章列表
    for entry in soup.select('.r-ent'):
        title_el = entry.select_one('.title a')
        if not title_el:
            continue  # 被刪除的文章

        title = title_el.text.strip()
        href = PTT_BASE + title_el['href']

        nrec_el = entry.select_one('.nrec span')
        nrec = nrec_el.text.strip() if nrec_el else ''
        push_count = _parse_push_count(nrec)

        author_el = entry.select_one('.meta .author')
        author = author_el.text.strip() if author_el else ''

        date_el = entry.select_one('.meta .date')
        date_str = date_el.text.strip() if date_el else ''

        category = _extract_category(title)

        articles.append({
            'url': href,
            'title': title,
            'author': author,
            'date': date_str,
            'push_count': push_count,
            'category': category,
        })

    return articles, prev_url


# ── 解析文章內容 ──────────────────────────────────────────

def _fetch_article_content(url: str) -> dict:
    """抓取單篇文章內容，回傳 {content_preview, push, boo, arrow}"""
    result = {'content_preview': '', 'push': 0, 'boo': 0, 'arrow': 0}

    try:
        resp = _session.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [!] 抓取文章失敗 {url}: {e}")
        return result

    soup = BeautifulSoup(resp.text, 'html.parser')

    # 推/噓/箭頭統計
    for tag in soup.select('.push-tag'):
        text = tag.text.strip()
        if '推' in text:
            result['push'] += 1
        elif '噓' in text:
            result['boo'] += 1
        else:
            result['arrow'] += 1

    # 內文（去掉 meta 和推文區）
    main_content = soup.select_one('#main-content')
    if main_content:
        # 移除推文
        for push in main_content.select('.push'):
            push.decompose()
        # 移除文章資訊列
        for meta in main_content.select('.article-metaline, .article-metaline-right'):
            meta.decompose()

        text = main_content.get_text(strip=False)
        # 清理多餘空白
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        result['content_preview'] = text[:500]

    return result


# ── 爬取主函式 ────────────────────────────────────────────

def crawl_ptt_stock(pages: int = 3) -> int:
    """爬取最新 N 頁文章，回傳新增文章數"""
    print(f"[PTT] 開始爬取 Stock 版，共 {pages} 頁")
    all_articles = []
    current_url = PTT_STOCK_URL

    for page_num in range(pages):
        print(f"  [PTT] 第 {page_num + 1}/{pages} 頁: {current_url}")
        articles, prev_url = _fetch_article_list(current_url)
        all_articles.extend(articles)

        if not prev_url:
            print("  [PTT] 已到最後一頁")
            break
        current_url = prev_url
        time.sleep(1)  # 避免太頻繁

    # 過濾已存在
    new_articles = [a for a in all_articles if not _url_exists(a['url'])]
    print(f"  [PTT] 列表共 {len(all_articles)} 篇，新文章 {len(new_articles)} 篇")

    if not new_articles:
        print("  [PTT] 沒有新文章")
        return 0

    # 逐篇抓內容
    inserted = 0
    for i, art in enumerate(new_articles):
        print(f"  [{i+1}/{len(new_articles)}] {art['title'][:40]}...", end='')
        detail = _fetch_article_content(art['url'])

        conn = get_conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO ptt_posts
                (url, title, author, date, push_count, boo_count, arrow_count,
                 content_preview, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                art['url'],
                art['title'],
                art['author'],
                art['date'],
                detail['push'],
                detail['boo'],
                detail['arrow'],
                detail['content_preview'],
                art['category'],
            ))
            conn.commit()
            inserted += 1
            print(f" ✓ 推{detail['push']}/噓{detail['boo']}")
        except Exception as e:
            print(f" ✗ {e}")
        finally:
            conn.close()

        time.sleep(1.5)  # 每篇間隔 1.5 秒

    print(f"[PTT] 完成，新增 {inserted} 篇文章")
    return inserted


# ── 情緒分析 ──────────────────────────────────────────────

def get_ptt_sentiment(hours: int = 24) -> dict:
    """分析 PTT 股版情緒"""
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
    rows = conn.execute("""
        SELECT title, content_preview, push_count, boo_count, category
        FROM ptt_posts
        WHERE crawled_at > ?
        ORDER BY crawled_at DESC
    """, (cutoff,)).fetchall()
    conn.close()

    if not rows:
        return {
            'total': 0,
            'bullish_pct': 0,
            'bearish_pct': 0,
            'neutral_pct': 0,
            'hot_topics': [],
            'message': '無近期 PTT 資料',
        }

    total = len(rows)
    bullish = 0
    bearish = 0
    total_push = 0
    total_boo = 0
    keyword_counts = {}

    for r in rows:
        text = (r['title'] or '') + ' ' + (r['content_preview'] or '')
        total_push += r['push_count'] or 0
        total_boo += r['boo_count'] or 0

        # 關鍵詞計數
        for kw in BULLISH_KEYWORDS + BEARISH_KEYWORDS:
            if kw in text:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

        # 判斷單篇偏多/偏空
        bull_score = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
        bear_score = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
        # 推噓也納入
        push_net = (r['push_count'] or 0) - (r['boo_count'] or 0)
        if push_net > 5:
            bull_score += 1
        elif push_net < -5:
            bear_score += 1

        if bull_score > bear_score:
            bullish += 1
        elif bear_score > bull_score:
            bearish += 1

    neutral = total - bullish - bearish
    bullish_pct = round(bullish / total * 100, 1)
    bearish_pct = round(bearish / total * 100, 1)
    neutral_pct = round(neutral / total * 100, 1)

    # 熱門關鍵詞 top 10
    hot_topics = sorted(keyword_counts.items(), key=lambda x: -x[1])[:10]

    # 分類統計
    cat_counts = {}
    for r in rows:
        cat = r['category'] or '其他'
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    return {
        'total': total,
        'bullish_pct': bullish_pct,
        'bearish_pct': bearish_pct,
        'neutral_pct': neutral_pct,
        'total_push': total_push,
        'total_boo': total_boo,
        'hot_topics': [{'keyword': k, 'count': v} for k, v in hot_topics],
        'categories': cat_counts,
        'message': (
            f"PTT Stock 近 {hours}h | 共 {total} 篇 | "
            f"看多 {bullish_pct}% / 看空 {bearish_pct}% / 中性 {neutral_pct}% | "
            f"總推 {total_push} / 總噓 {total_boo}"
        ),
    }


# ── 最新文章查詢 ──────────────────────────────────────────

def get_latest_posts(limit: int = 30) -> list[dict]:
    """取得最新 PTT 文章"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT url, title, author, date, push_count, boo_count, arrow_count,
               content_preview, category, sentiment, score, crawled_at
        FROM ptt_posts
        ORDER BY crawled_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── CLI ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='PTT 股版爬蟲')
    parser.add_argument('--pages', type=int, default=3, help='爬取頁數（預設 3）')
    parser.add_argument('--sentiment', action='store_true', help='輸出情緒分析')
    args = parser.parse_args()

    if args.sentiment:
        result = get_ptt_sentiment()
        print(f"\n{result['message']}")
        if result['hot_topics']:
            print("\n熱門關鍵詞：")
            for item in result['hot_topics']:
                print(f"  {item['keyword']}: {item['count']} 次")
        if result.get('categories'):
            print("\n分類統計：")
            for cat, cnt in result['categories'].items():
                print(f"  [{cat}]: {cnt} 篇")
        print()
        return

    crawl_ptt_stock(pages=args.pages)


if __name__ == '__main__':
    main()
