"""
投資系統後端 API  v2.0
整合：回測、優化器、資料下載、情報收集、X 監控、Threads 監控、每日報告
"""
import hashlib, json, os, re, sqlite3, sys, threading, time, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path

import requests
import urllib3
from flask import Flask, jsonify, request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Paths ──────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / 'db' / 'trades.db'
DB_PATH.parent.mkdir(exist_ok=True)

sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / 'strategies'))  # for strategies/base.py

app = Flask(__name__)

# ── DB helpers ─────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def rows_to_dicts(rows):
    return [dict(r) for r in rows]

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL, symbol TEXT NOT NULL,
            action TEXT NOT NULL, price REAL NOT NULL,
            size INTEGER NOT NULL, value REAL NOT NULL,
            pnl REAL DEFAULT 0, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL, symbol TEXT NOT NULL,
            start_date TEXT, end_date TEXT,
            initial_cash REAL, final_value REAL,
            total_return REAL, max_drawdown REAL,
            sharpe_ratio REAL, win_rate REAL,
            total_trades INTEGER, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL, date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER, source TEXT DEFAULT 'yfinance',
            UNIQUE(symbol, date)
        );
        CREATE TABLE IF NOT EXISTS tg_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL, group_name TEXT,
            sender_id INTEGER, sender_name TEXT,
            message_text TEXT, ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tg_messages_group_ts
            ON tg_messages (group_id, ts);
        CREATE TABLE IF NOT EXISTS news_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, summary TEXT,
            url TEXT UNIQUE, source TEXT,
            sentiment TEXT, score INTEGER,
            category TEXT DEFAULT 'finance',
            keywords TEXT, reason TEXT,
            published_at TEXT, analyzed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS x_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, topic TEXT, author TEXT,
            content TEXT, sentiment TEXT, engagement TEXT,
            url TEXT, content_hash TEXT UNIQUE, ts TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_x_posts_ts ON x_posts (ts);
        CREATE TABLE IF NOT EXISTS x_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            summary TEXT NOT NULL, post_count INTEGER, ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS threads_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL, post_id TEXT,
            content TEXT, url TEXT UNIQUE,
            likes INTEGER DEFAULT 0, replies INTEGER DEFAULT 0,
            ts TEXT, analyzed_at TEXT, sentiment TEXT, score INTEGER
        );
        CREATE TABLE IF NOT EXISTS threads_accounts (
            username TEXT PRIMARY KEY, alias TEXT, added_at TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── Settings ───────────────────────────────────────────────────
def _load_shared_env():
    env_path = Path.home() / '.config' / 'ai-hub' / 'shared' / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())

def load_settings_from_db():
    try:
        conn = get_conn()
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
        for r in rows:
            if r['value']:
                os.environ[r['key']] = r['value']
    except Exception:
        pass

_load_shared_env()
load_settings_from_db()

SETTING_KEYS = [
    'GROQ_API_KEY', 'GEMINI_API_KEY', 'GEMINI_API_KEY_APEX',
    'GEMINI_API_KEY_ECHO', 'GEMINI_API_KEY_BACKUP',
    'XAI_API_KEY', 'TG_API_ID', 'TG_API_HASH',
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_ALLOWED_USERS',
    'DEFAULT_CASH', 'DEFAULT_COMMISSION', 'DEFAULT_TAX',
]
SENSITIVE_KEYS = {
    'GROQ_API_KEY', 'GEMINI_API_KEY', 'GEMINI_API_KEY_APEX',
    'GEMINI_API_KEY_ECHO', 'GEMINI_API_KEY_BACKUP',
    'XAI_API_KEY', 'TG_API_HASH', 'TELEGRAM_BOT_TOKEN',
}

# ── Task manager ───────────────────────────────────────────────
_tasks: dict = {}
_tasks_lock = threading.Lock()

def create_task(name: str, fn, *args, **kwargs) -> str:
    task_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + re.sub(r'\W+', '', name)[:8]
    with _tasks_lock:
        _tasks[task_id] = {
            'id': task_id, 'name': name, 'status': 'running',
            'created_at': datetime.now().isoformat(),
            'finished_at': None, 'result': None, 'error': None,
        }
    def worker():
        try:
            result = fn(*args, **kwargs)
            with _tasks_lock:
                _tasks[task_id].update(
                    status='done',
                    result=str(result)[:1000] if result is not None else 'OK',
                    finished_at=datetime.now().isoformat(),
                )
        except Exception as e:
            with _tasks_lock:
                _tasks[task_id].update(
                    status='error', error=str(e),
                    finished_at=datetime.now().isoformat(),
                )
    threading.Thread(target=worker, daemon=True, name=f'task-{task_id}').start()
    return task_id

# ── Intelligence ───────────────────────────────────────────────
RSS_SOURCES = {
    'google_tw_finance': 'https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTUdZU0FucG9LQUFQAQ?hl=zh-TW&gl=TW&ceid=TW:zh-TW',
    'ltn_business':      'https://news.ltn.com.tw/rss/business.xml',
    'ltn_world':         'https://news.ltn.com.tw/rss/world.xml',
    'ltn_politics':      'https://news.ltn.com.tw/rss/politics.xml',
    'google_world_biz':  'https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en',
    'google_geopolitics':'https://news.google.com/rss/search?q=geopolitics+OR+war+OR+conflict+when:1d&hl=en-US&gl=US&ceid=US:en',
    'google_asia':       'https://news.google.com/rss/search?q=Asia+economy+OR+China+trade+when:1d&hl=en-US&gl=US&ceid=US:en',
}
GOOGLE_SEARCH_TMPL = 'https://news.google.com/rss/search?q={keyword}+when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-TW'
DEFAULT_KEYWORDS = [
    '台積電', '台股', '聯準會', 'Fed 利率', '台海', '中國軍演',
    '俄烏戰爭', '以色列', '中東局勢', '黃金', '原油', '比特幣',
    '美國經濟', '歐洲經濟', '通膨', '央行 降息',
]
_HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def _rss_url_exists(url):
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM news_intelligence WHERE url=?", (url,)).fetchone()
    conn.close()
    return row is not None

def _insert_intel_news(title, summary, url, source, published_at):
    if _rss_url_exists(url):
        return False
    conn = get_conn()
    conn.execute(
        "INSERT INTO news_intelligence (title, summary, url, source, published_at) VALUES (?,?,?,?,?)",
        (title, summary or '', url, source, published_at)
    )
    conn.commit(); conn.close()
    return True

def _fetch_rss(url):
    items = []
    try:
        resp = requests.get(url, headers=_HTTP_HEADERS, timeout=15, verify=False)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.iter('item'):
            title = item.findtext('title', '').strip()
            link  = item.findtext('link', '').strip()
            desc  = item.findtext('description', '').strip()
            pub   = item.findtext('pubDate', '').strip()
            if title and link:
                items.append({'title': title, 'summary': desc[:500], 'url': link, 'published_at': pub})
    except Exception as e:
        print(f"  [!] RSS 失敗: {e}")
    return items

def collect_news(keywords=None):
    total_new = 0
    for src, url in RSS_SOURCES.items():
        items = _fetch_rss(url)
        new = sum(1 for it in items
                  if _insert_intel_news(it['title'], it['summary'], it['url'], src, it['published_at']))
        total_new += new
    for kw in (keywords or DEFAULT_KEYWORDS):
        url = GOOGLE_SEARCH_TMPL.format(keyword=urllib.parse.quote(kw))
        items = _fetch_rss(url)
        new = sum(1 for it in items
                  if _insert_intel_news(it['title'], it['summary'], it['url'], f'google:{kw}', it['published_at']))
        total_new += new
    return total_new

_gemini_idx = 0
def _get_gemini_key():
    global _gemini_idx
    keys = [k for k in [os.environ.get(f'GEMINI_API_KEY{s}')
                        for s in ['', '_APEX', '_ECHO', '_BACKUP']] if k]
    if not keys: return None
    key = keys[_gemini_idx % len(keys)]; _gemini_idx += 1
    return key

def _build_analysis_prompt(title, summary):
    return (
        '你是全球市場情感分析器。分析以下新聞對金融市場的影響。\n'
        '地緣政治風險通常利空股市、利多黃金。央行升息利空、降息利多。\n'
        '回覆純 JSON（不要其他文字）：\n'
        '{"sentiment":"bullish/bearish/neutral","score":1-10,'
        '"category":"finance/geopolitics/economy/commodity/crypto",'
        '"keywords":["關鍵字"],"reason":"一句話"}\n\n'
        f'標題：{title}\n摘要：{summary}'
    )

def _groq_analyze(title, summary):
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key: return None
    try:
        resp = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.3-70b-versatile',
                  'messages': [{'role': 'user', 'content': _build_analysis_prompt(title, summary)}],
                  'temperature': 0.1, 'max_tokens': 256},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'): content = content[4:]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"  [!] Groq 錯誤: {e}"); return None

def _gemini_analyze(title, summary):
    api_key = _get_gemini_key()
    if not api_key: return None
    try:
        resp = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={'contents': [{'parts': [{'text': _build_analysis_prompt(title, summary)}]}],
                  'generationConfig': {'maxOutputTokens': 500, 'thinkingConfig': {'thinkingBudget': 0}}},
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        if '```' in content:
            content = content.split('```')[1]
            if content.startswith('json'): content = content[4:]
            content = content.strip()
        s, e2 = content.find('{'), content.rfind('}')
        if s != -1 and e2 != -1: content = content[s:e2+1]
        return json.loads(content)
    except Exception as e:
        print(f"  [!] Gemini 錯誤: {e}"); return None

def analyze_news(limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, summary FROM news_intelligence WHERE sentiment IS NULL LIMIT ?", (limit,)
    ).fetchall(); conn.close()
    if not rows: return 0
    analyzed = 0; use_gemini = False
    for row in rows:
        result = None
        if not use_gemini:
            result = _groq_analyze(row['title'], row['summary'])
            if not result: use_gemini = True
        if use_gemini and result is None:
            result = _gemini_analyze(row['title'], row['summary'])
        conn = get_conn()
        if result:
            conn.execute(
                "UPDATE news_intelligence SET sentiment=?,score=?,category=?,keywords=?,reason=?,analyzed_at=? WHERE id=?",
                (result.get('sentiment', 'neutral'), result.get('score', 5),
                 result.get('category', 'finance'),
                 json.dumps(result.get('keywords', []), ensure_ascii=False),
                 result.get('reason', ''), datetime.now().isoformat(), row['id'])
            )
            analyzed += 1
            time.sleep(1.5 if not use_gemini else 4)
        else:
            conn.execute("UPDATE news_intelligence SET sentiment='error',analyzed_at=? WHERE id=?",
                        (datetime.now().isoformat(), row['id']))
        conn.commit(); conn.close()
    return analyzed

def intelligence_cycle(keywords=None):
    new_count = collect_news(keywords)
    analyzed  = analyze_news()
    return {'new_news': new_count, 'analyzed': analyzed}

# ── X / Twitter Monitor ────────────────────────────────────────
XAI_API_URL  = 'https://api.x.ai/v1/chat/completions'
GROK_MODEL   = 'grok-3-latest'
X_TOPICS = [
    '台股 台灣股市', '台積電 TSMC', '台海 兩岸',
    '全球經濟 global economy', '加密貨幣 crypto Bitcoin',
    '中東 Iran war', '俄烏 Russia Ukraine',
    'gold 黃金', 'oil 原油', 'AI artificial intelligence',
    'trending viral 爆紅', 'meme 迷因',
]
NITTER_INSTANCES  = ['https://nitter.privacydev.net', 'https://nitter.poast.org']
X_WATCH_ACCOUNTS = ['Reuters', 'Bloomberg', 'CNBC', 'WSJ', 'CoinDesk']

def _x_hash(text): return hashlib.md5(text.strip().encode()).hexdigest()

def _insert_x_post(source, topic, author, content, sentiment='', engagement='', url=''):
    h = _x_hash(content)
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO x_posts (source,topic,author,content,sentiment,engagement,url,content_hash,ts) VALUES (?,?,?,?,?,?,?,?,?)",
            (source, topic, author, content, sentiment, engagement, url, h, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit(); return True
    except sqlite3.IntegrityError: return False
    finally: conn.close()

def _grok_request(prompt):
    api_key = os.environ.get('XAI_API_KEY', '')
    if not api_key: return None
    try:
        resp = requests.post(
            XAI_API_URL,
            headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
            json={'model': GROK_MODEL,
                  'messages': [
                      {'role': 'system', 'content': '你是 X/Twitter 資訊搜尋助手。'},
                      {'role': 'user', 'content': prompt},
                  ],
                  'temperature': 0.3, 'search': True},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f'[!] Grok API 錯誤: {e}'); return None

def _parse_json_array(text):
    text = text.strip()
    if '```' in text:
        for part in text.split('```'):
            part = part.strip()
            if part.startswith('json'): part = part[4:].strip()
            if part.startswith('['):
                try: return json.loads(part)
                except: continue
    if text.startswith('['):
        try: return json.loads(text)
        except: pass
    s, e2 = text.find('['), text.rfind(']')
    if s != -1 and e2 != -1 and e2 > s:
        try: return json.loads(text[s:e2+1])
        except: pass
    return None

def search_x_trending(topic=None):
    if topic:
        prompt = (f'搜尋 X/Twitter 上關於「{topic}」最近 24 小時的熱門推文。\n'
                  f'回傳純 JSON 陣列：[{{"author":"帳號","content":"摘要","engagement":"互動量","sentiment":"positive/negative/neutral","url":""}}]\n至少 10 則。')
    else:
        prompt = ('搜尋 X/Twitter 上最近 24 小時全球最熱門的話題。\n'
                  '回傳純 JSON 陣列：[{"author":"帳號","content":"摘要","engagement":"互動量","sentiment":"positive/negative/neutral","url":""}]\n至少 15 則。')
    raw = _grok_request(prompt)
    if not raw: return []
    posts = _parse_json_array(raw)
    if not posts: return []
    for p in posts:
        _insert_x_post('grok', topic or 'trending', p.get('author',''), p.get('content',''),
                       p.get('sentiment',''), p.get('engagement',''), p.get('url',''))
    return posts

def fetch_nitter_rss():
    all_posts = []
    for account in X_WATCH_ACCOUNTS:
        for instance in NITTER_INSTANCES:
            try:
                resp = requests.get(f'{instance}/{account}/rss', timeout=15,
                                    headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code != 200: continue
                root = ET.fromstring(resp.content)
                for item in root.findall('.//item'):
                    content = item.findtext('title','') or item.findtext('description','')
                    link = item.findtext('link','')
                    if content and _insert_x_post('nitter', '', account, content[:500], url=link):
                        all_posts.append({'author': account, 'content': content[:500], 'url': link})
                break
            except: continue
    return all_posts

_x_gemini_idx = 0
def _get_x_gemini_key():
    global _x_gemini_idx
    keys = [k for k in [os.environ.get(f'GEMINI_API_KEY{s}')
                        for s in ['', '_APEX', '_ECHO', '_BACKUP', '_B2', '_B3']] if k]
    if not keys: return None
    key = keys[_x_gemini_idx % len(keys)]; _x_gemini_idx += 1
    return key

def generate_x_summary(posts):
    if not posts: return None
    api_key = _get_x_gemini_key()
    if not api_key: return None
    lines = [f'{i}. @{p.get("author","?")}: {p.get("content","")} [{p.get("sentiment","")}]'
             for i, p in enumerate(posts[:100], 1)]
    prompt = ('以下是 X/Twitter 上最近的熱門討論：\n\n' + '\n'.join(lines) + '\n\n'
              '請用繁體中文整理一份 500 字以內的「X/Twitter 輿情日報」。\n'
              '格式：1. 3-5 個重要趨勢 2. 每個話題簡述 3. 整體市場情緒 4. Markdown 格式')
    try:
        resp = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}',
            headers={'Content-Type': 'application/json'},
            json={'contents': [{'parts': [{'text': prompt}]}],
                  'generationConfig': {'maxOutputTokens': 2000, 'thinkingConfig': {'thinkingBudget': 0}}},
            timeout=60,
        )
        resp.raise_for_status()
        summary = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        conn = get_conn()
        conn.execute("INSERT INTO x_summaries (summary,post_count,ts) VALUES (?,?,?)",
                    (summary, len(posts), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit(); conn.close()
        return summary
    except Exception as e:
        print(f'[!] Gemini 摘要錯誤: {e}'); return None

def x_monitor_cycle(topics=None):
    all_posts = []
    for topic in (topics or X_TOPICS):
        posts = search_x_trending(topic)
        all_posts.extend(posts)
        time.sleep(2)
    nitter_posts = fetch_nitter_rss()
    all_posts.extend(nitter_posts)
    summary = generate_x_summary(all_posts)
    return {'posts': len(all_posts), 'has_summary': summary is not None}

# ── Threads Monitor ────────────────────────────────────────────
_TH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8',
}

def _th_post_exists(url):
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM threads_posts WHERE url=?", (url,)).fetchone()
    conn.close(); return row is not None

def _insert_th_post(username, post_id, content, url, likes=0, replies=0, ts=None):
    if not url or _th_post_exists(url): return False
    conn = get_conn()
    conn.execute(
        "INSERT INTO threads_posts (username,post_id,content,url,likes,replies,ts) VALUES (?,?,?,?,?,?,?)",
        (username, post_id, content, url, likes, replies, ts or datetime.now().isoformat())
    )
    conn.commit(); conn.close(); return True

def _extract_json_ld(html):
    results = []
    for m in re.finditer(r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
                         html, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(m.group(1))
            results.extend(data if isinstance(data, list) else [data])
        except: pass
    return results

def _extract_meta_content(html, prop):
    for pat in [rf'<meta\s+property="{prop}"\s+content="([^"]*)"',
                rf'<meta\s+content="([^"]*)"\s+property="{prop}"']:
        m = re.search(pat, html, re.IGNORECASE)
        if m: return unescape(m.group(1))
    return None

def fetch_threads_profile(username):
    url = f"https://www.threads.net/@{username}"
    result = {'username': username, 'posts': [], 'error': None}
    try:
        resp = requests.get(url, headers=_TH_HEADERS, timeout=20, verify=False, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        for item in _extract_json_ld(html):
            if item.get('@type') in ('SocialMediaPosting', 'Article', 'BlogPosting'):
                content = item.get('articleBody') or item.get('text') or item.get('headline','')
                if content:
                    result['posts'].append({
                        'content': content, 'url': item.get('url', url),
                        'ts': item.get('datePublished') or item.get('dateCreated',''),
                        'likes': 0, 'replies': 0,
                    })
        if not result['posts']:
            og_desc = _extract_meta_content(html, 'og:description')
            if og_desc and len(og_desc) > 10:
                result['posts'].append({
                    'content': og_desc,
                    'url': _extract_meta_content(html, 'og:url') or url,
                    'ts': datetime.now().isoformat(), 'likes': 0, 'replies': 0,
                })
    except Exception as e:
        result['error'] = str(e)
    return result

def threads_cycle():
    conn = get_conn()
    accounts = conn.execute("SELECT username FROM threads_accounts ORDER BY username").fetchall()
    conn.close()
    total_new = 0
    for acct in accounts:
        username = acct['username']
        result = fetch_threads_profile(username)
        for post in result['posts']:
            post_id = post['url'].rstrip('/').split('/')[-1] if post.get('url') else None
            if _insert_th_post(username, post_id, post['content'], post.get('url',''),
                               post.get('likes',0), post.get('replies',0), post.get('ts')):
                total_new += 1
        time.sleep(5)
    return {'new_posts': total_new}

# ── Daily Report ───────────────────────────────────────────────
def get_market_summary():
    conn = get_conn()
    symbols = {'GC=F':'黃金', '^GSPC':'S&P500', '^TWII':'台灣加權',
               'BTC-USD':'比特幣', 'CL=F':'原油', 'USDTWD=X':'美元/台幣'}
    results = []
    for sym, name in symbols.items():
        rows = conn.execute(
            "SELECT date,open,close,high,low,volume FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 2",
            (sym,)
        ).fetchall()
        if len(rows) >= 2:
            t, y = dict(rows[0]), dict(rows[1])
            chg = t['close'] - y['close']
            results.append({'symbol':sym,'name':name,'date':t['date'],'close':t['close'],
                            'change':chg,'change_pct':(chg/y['close']*100) if y['close'] else 0})
        elif rows:
            t = dict(rows[0])
            results.append({'symbol':sym,'name':name,'date':t['date'],'close':t['close'],'change':0,'change_pct':0})
    conn.close()
    return results

def generate_daily_report(send_tg=False):
    now = datetime.now()
    lines = [f"📊 每日市場報告", f"📅 {now.strftime('%Y-%m-%d %H:%M')}", "="*35]
    markets = get_market_summary()
    if markets:
        lines.append("\n📈 市場行情")
        for m in markets:
            arrow = "🔴" if m['change'] >= 0 else "🟢"
            lines.append(f"{arrow} {m['name']}: {m['close']:,.2f} ({m['change_pct']:+.2f}%)")
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    mood_row = conn.execute("""
        SELECT COUNT(CASE WHEN sentiment='bullish' THEN 1 END) as b,
               COUNT(CASE WHEN sentiment='bearish' THEN 1 END) as be,
               COUNT(*) as total, AVG(CASE WHEN score > 0 THEN score END) as avg
        FROM news_intelligence WHERE analyzed_at > ? AND sentiment IN ('bullish','bearish','neutral')
    """, (cutoff,)).fetchone()
    if mood_row and mood_row['total'] > 0:
        m = dict(mood_row)
        label = "偏多" if m['b'] > m['be'] else "偏空" if m['be'] > m['b'] else "中性"
        lines.append(f"\n情緒: {label} | 看多 {m['b']} / 看空 {m['be']} | AVG {(m['avg'] or 5):.1f}/10")
    top_news = conn.execute("""
        SELECT title, sentiment, score FROM news_intelligence
        WHERE analyzed_at > ? AND sentiment IN ('bullish','bearish','neutral')
        ORDER BY score DESC LIMIT 5
    """, (cutoff,)).fetchall()
    if top_news:
        lines.append("\n📰 重要新聞 Top 5")
        for i, n in enumerate(top_news, 1):
            lines.append(f"{i}. [{n['score']}] {n['title'][:50]}")
    conn.close()
    report = "\n".join(lines)
    if send_tg:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id   = os.environ.get('TELEGRAM_ALLOWED_USERS')
        if bot_token and chat_id:
            try:
                requests.post(f'https://api.telegram.org/bot{bot_token}/sendMessage',
                             json={'chat_id': chat_id, 'text': report, 'parse_mode': 'HTML'}, timeout=15)
            except: pass
    return report

# ── Backtest ───────────────────────────────────────────────────
DEFAULT_CASH       = 1_000_000
DEFAULT_COMMISSION = 0.001425
DEFAULT_TAX        = 0.003

def _cfg(key, default):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    try: return type(default)(row['value']) if row and row['value'] else default
    except: return default

def run_backtest(strategy_name, symbol, source='yfinance', period='1y',
                 start_date=None, end_date=None, cash=None, params=None):
    import backtrader as bt
    import pandas as pd
    from strategies import STRATEGIES

    if strategy_name not in STRATEGIES:
        raise ValueError(f'未知策略: {strategy_name}. 可用: {", ".join(STRATEGIES.keys())}')

    strategy_cls = STRATEGIES[strategy_name]
    cash = cash or _cfg('DEFAULT_CASH', DEFAULT_CASH)

    if source == 'db':
        conn = sqlite3.connect(str(DB_PATH))
        q = "SELECT date,open,high,low,close,volume FROM market_data WHERE symbol=?"
        p = [symbol]
        if start_date: q += " AND date >= ?"; p.append(start_date)
        if end_date:   q += " AND date <= ?"; p.append(end_date)
        q += " ORDER BY date ASC"
        df = pd.read_sql_query(q, conn, params=p); conn.close()
        if df.empty: raise ValueError(f'{symbol} 在資料庫中沒有資料')
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.astype(float)
        data = bt.feeds.PandasData(dataname=df)
    else:
        import yfinance as yf
        df = yf.download(symbol, period=period, progress=False)
        if df.empty: raise ValueError(f'{symbol} yfinance 無資料')
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data = bt.feeds.PandasData(dataname=df)

    class MaxDD(bt.Analyzer):
        def __init__(self): self.peak = 0; self.max_dd = 0
        def next(self):
            v = self.strategy.broker.getvalue()
            if v > self.peak: self.peak = v
            dd = (self.peak - v) / self.peak if self.peak > 0 else 0
            if dd > self.max_dd: self.max_dd = dd
        def get_analysis(self): return {'max_drawdown': self.max_dd}

    import io, sys as _sys
    _buf = io.StringIO()
    _old = _sys.stdout; _sys.stdout = _buf
    try:
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(strategy_cls, **(params or {}))
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=_cfg('DEFAULT_COMMISSION', DEFAULT_COMMISSION))
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                            timeframe=bt.TimeFrame.Days, annualize=True)
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        cerebro.addanalyzer(MaxDD, _name='maxdd')
        results = cerebro.run()
    finally:
        _sys.stdout = _old; _buf.close()

    strat        = results[0]
    final_value  = cerebro.broker.getvalue()
    total_return = (final_value - cash) / cash * 100
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', 0) or 0
    max_drawdown = strat.analyzers.maxdd.get_analysis().get('max_drawdown', 0) * 100
    total_trades = strat.analyzers.trades.get_analysis().get('total', {}).get('closed', 0)
    win_rate     = strat.win_rate * 100 if hasattr(strat, 'win_rate') else 0

    conn = get_conn()
    conn.execute("""INSERT INTO backtest_results
        (strategy,symbol,start_date,end_date,initial_cash,final_value,
         total_return,max_drawdown,sharpe_ratio,win_rate,total_trades)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (strategy_name, symbol, start_date or 'N/A', end_date or 'N/A',
         cash, final_value, total_return, max_drawdown, sharpe_ratio, win_rate, total_trades))
    conn.commit(); conn.close()

    return {
        'strategy': strategy_name, 'symbol': symbol,
        'initial_cash': cash, 'final_value': final_value,
        'total_return': total_return, 'max_drawdown': max_drawdown,
        'sharpe_ratio': sharpe_ratio, 'win_rate': win_rate,
        'total_trades': total_trades,
    }

# ── Optimizer ──────────────────────────────────────────────────
DEFAULT_PARAM_GRIDS = {
    'ma_cross':  {'fast_period': [3,5,8,10,13], 'slow_period': [15,20,30,40,60]},
    'rsi':       {'rsi_period': [7,14,21], 'oversold': [20,25,30], 'overbought': [70,75,80]},
    'bollinger': {'period': [15,20,25,30], 'devfactor': [1.5,2.0,2.5]},
    'macd':      {'fast': [8,12,16], 'slow': [21,26,30], 'signal': [5,9,13]},
    'breakout':  {'entry_period': [10,15,20,30], 'exit_period': [5,10,15]},
}

def run_optimizer(strategy_name, symbol, param_grid=None, source='yfinance',
                  period='1y', cash=None, top_n=10, start_date=None, end_date=None):
    from itertools import product as iproduct
    from strategies import STRATEGIES

    if strategy_name not in STRATEGIES:
        raise ValueError(f'未知策略: {strategy_name}')
    if param_grid is None:
        param_grid = DEFAULT_PARAM_GRIDS.get(strategy_name, {})
    if not param_grid:
        raise ValueError(f'{strategy_name} 無參數範圍')

    keys   = list(param_grid.keys())
    combos = [dict(zip(keys, c)) for c in iproduct(*[param_grid[k] for k in keys])]
    print(f'[優化器] {strategy_name} on {symbol}: {len(combos)} 組參數')

    results = []
    for i, params in enumerate(combos, 1):
        try:
            r = run_backtest(strategy_name=strategy_name, symbol=symbol, source=source,
                             period=period, start_date=start_date, end_date=end_date,
                             cash=cash, params=params)
            if r:
                r['params'] = params
                results.append(r)
        except Exception as e:
            print(f'  [{i}/{len(combos)}] {params} 失敗: {e}')

    if not results:
        return {'error': '無有效結果', 'results': []}

    results.sort(key=lambda x: x['total_return'], reverse=True)
    top = results[:top_n]

    conn = get_conn()
    for r in top:
        params_str = ', '.join(f'{k}={v}' for k, v in r['params'].items())
        conn.execute("""INSERT INTO backtest_results
            (strategy,symbol,start_date,end_date,initial_cash,final_value,
             total_return,max_drawdown,sharpe_ratio,win_rate,total_trades)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (f'{strategy_name}|{params_str}', symbol, 'optimizer', datetime.now().isoformat(),
             r['initial_cash'], r['final_value'], r['total_return'], r['max_drawdown'],
             r['sharpe_ratio'], r['win_rate'], r['total_trades']))
    conn.commit(); conn.close()

    return {
        'total_combinations': len(combos),
        'valid_results': len(results),
        'top': top,
        'best_params': top[0]['params'] if top else None,
        'best_return': top[0]['total_return'] if top else None,
    }

# ── Data Download ──────────────────────────────────────────────
def download_data(source, symbol, start=None, end=None, period='1y'):
    from data.fetcher import (
        batch_download_yfinance, batch_download_twse_stock,
        batch_download_taifex, batch_download_tpex_stock,
    )
    if source == 'yfinance':
        records = batch_download_yfinance(symbol, period)
    elif source == 'twse':
        records = batch_download_twse_stock(symbol, start or '2024-01-01', end)
    elif source == 'taifex':
        s = (start or '2024-01-01').replace('-', '/')
        e = (end or datetime.now().strftime('%Y-%m-%d')).replace('-', '/')
        records = batch_download_taifex(symbol, s, e)
    elif source == 'tpex':
        records = batch_download_tpex_stock(symbol, start or '2024-01-01', end)
    else:
        raise ValueError(f'未知資料來源: {source}')
    return {'symbol': symbol, 'source': source, 'records': len(records) if records else 0}

# ══════════════════════════════════════════════════════════════
# API Endpoints
# ══════════════════════════════════════════════════════════════

# ── Read endpoints (existing) ─────────────────────────────────
@app.route("/api/backtests")
def api_backtests():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM backtest_results ORDER BY ts DESC LIMIT 200").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/market/<symbol>")
def api_market(symbol):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 120", (symbol,)
    ).fetchall(); conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/trades")
def api_trades():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT 100").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/symbols")
def api_symbols():
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, COUNT(*) as count, MIN(date) as min_date, MAX(date) as max_date
        FROM market_data GROUP BY symbol ORDER BY symbol
    """).fetchall(); conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/intelligence")
def api_intelligence():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id,title,summary,url,source,sentiment,score,keywords,reason,published_at,analyzed_at
        FROM news_intelligence
        WHERE sentiment IS NOT NULL AND sentiment != 'error'
        ORDER BY analyzed_at DESC LIMIT 100
    """).fetchall(); conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/mood")
def api_mood():
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT sentiment, score FROM news_intelligence WHERE analyzed_at > ? AND sentiment IN ('bullish','bearish','neutral')",
        (cutoff,)
    ).fetchall(); conn.close()
    if not rows:
        return jsonify({'total':0,'bullish':0,'bearish':0,'neutral':0,'avg_score':0,'mood':'unknown'})
    counts = {'bullish':0,'bearish':0,'neutral':0}; score_sum = 0
    for r in rows:
        counts[r['sentiment']] = counts.get(r['sentiment'],0) + 1
        score_sum += (r['score'] or 5)
    total = len(rows)
    dominant = max(counts, key=counts.get)
    return jsonify({'total':total,'bullish':counts['bullish'],'bearish':counts['bearish'],
                    'neutral':counts['neutral'],'avg_score':round(score_sum/total,1),'mood':dominant})

@app.route("/api/tg-messages")
def api_tg_messages():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tg_messages ORDER BY ts DESC LIMIT 100").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/tg-stats")
def api_tg_stats():
    conn = get_conn()
    groups = conn.execute("""
        SELECT group_name, COUNT(*) as msg_count, MAX(ts) as latest_ts
        FROM tg_messages GROUP BY group_name ORDER BY msg_count DESC
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    today = conn.execute("SELECT COUNT(*) FROM tg_messages WHERE ts >= ?",
                        (datetime.now().strftime("%Y-%m-%d"),)).fetchone()[0]
    conn.close()
    return jsonify({"total":total,"today":today,"groups":rows_to_dicts(groups)})

@app.route("/api/chipdata/summary")
def api_chipdata_summary():
    conn = get_conn()
    try:
        latest = conn.execute("SELECT MAX(date) FROM tw_institutional").fetchone()[0]
        if not latest: return jsonify({"latest_date":None,"rows":[]})
        rows = conn.execute("""
            SELECT symbol,foreign_net,trust_net,COALESCE(dealer_net,0) as dealer_net,
                   (COALESCE(foreign_net,0)+COALESCE(trust_net,0)+COALESCE(dealer_net,0)) as total_net
            FROM tw_institutional WHERE date=?
            ORDER BY ABS(COALESCE(foreign_net,0)+COALESCE(trust_net,0)+COALESCE(dealer_net,0)) DESC LIMIT 10
        """, (latest,)).fetchall()
    except:
        return jsonify({"latest_date":None,"rows":[]})
    finally:
        conn.close()
    return jsonify({"latest_date":latest,"rows":rows_to_dicts(rows)})

@app.route("/api/chipdata/<symbol>")
def api_chipdata(symbol):
    conn = get_conn()
    days = int(os.environ.get("CHIP_DAYS", 60))
    inst   = conn.execute("SELECT * FROM tw_institutional WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol,days)).fetchall()
    margin = conn.execute("SELECT * FROM tw_margin WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol,days)).fetchall()
    per    = conn.execute("SELECT * FROM tw_per WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol,days)).fetchall()
    rev    = conn.execute("SELECT * FROM tw_revenue WHERE symbol=? ORDER BY date DESC LIMIT 24", (symbol,)).fetchall()
    conn.close()
    return jsonify({"symbol":symbol,"institutional":rows_to_dicts(inst),"margin":rows_to_dicts(margin),
                    "per":rows_to_dicts(per),"revenue":rows_to_dicts(rev)})

@app.route("/api/chipdata")
def api_chipdata_list():
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, COUNT(*) as days, MIN(date) as from_date, MAX(date) as to_date
        FROM tw_institutional GROUP BY symbol ORDER BY symbol
    """).fetchall(); conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/x-posts")
def api_x_posts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM x_posts ORDER BY ts DESC LIMIT 100").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/x-summaries")
def api_x_summaries():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM x_summaries ORDER BY ts DESC LIMIT 10").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/threads-posts")
def api_threads_posts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM threads_posts ORDER BY id DESC LIMIT 50").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/threads-accounts")
def api_threads_accounts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM threads_accounts ORDER BY username").fetchall()
    conn.close(); return jsonify(rows_to_dicts(rows))

@app.route("/api/strategies")
def api_strategies():
    from strategies import STRATEGIES
    result = []
    for name in STRATEGIES:
        grid = DEFAULT_PARAM_GRIDS.get(name, {})
        combos = 1
        for v in grid.values(): combos *= len(v)
        result.append({'name': name, 'param_grid': grid, 'combinations': combos})
    return jsonify(result)

# ── Settings endpoints ────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    db_vals = {r['key']: r['value'] for r in rows}
    result = {}
    for key in SETTING_KEYS:
        val = db_vals.get(key) or os.environ.get(key, '')
        if key in SENSITIVE_KEYS and val:
            result[key] = '****' + val[-4:] if len(val) > 4 else '****'
        else:
            result[key] = val
    return jsonify(result)

@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.json or {}
    conn = get_conn()
    for key, val in data.items():
        if key not in SETTING_KEYS: continue
        if val and not str(val).startswith('****'):
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, str(val)))
            os.environ[key] = str(val)
    conn.commit(); conn.close()
    return jsonify({"ok": True})

# ── Task endpoints ────────────────────────────────────────────
@app.route("/api/tasks")
def api_tasks():
    with _tasks_lock:
        tasks = sorted(_tasks.values(), key=lambda t: t['created_at'], reverse=True)
    return jsonify(tasks[:50])

@app.route("/api/tasks/<task_id>")
def api_task_get(task_id):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task: return jsonify({'error': 'task not found'}), 404
    return jsonify(task)

# ── Run endpoints ─────────────────────────────────────────────
@app.route("/api/run/backtest", methods=["POST"])
def api_run_backtest():
    d = request.json or {}
    strategy = d.get('strategy', 'ma_cross')
    symbol   = d.get('symbol', 'GC=F')
    source   = d.get('source', 'yfinance')
    period   = d.get('period', '1y')
    start    = d.get('start_date') or None
    end      = d.get('end_date') or None
    cash     = float(d['cash']) if d.get('cash') else None
    params   = d.get('params') or None
    task_id  = create_task(
        f'回測:{strategy}@{symbol}',
        run_backtest, strategy, symbol, source, period, start, end, cash, params
    )
    return jsonify({'task_id': task_id})

@app.route("/api/run/optimize", methods=["POST"])
def api_run_optimize():
    d = request.json or {}
    strategy  = d.get('strategy', 'ma_cross')
    symbol    = d.get('symbol', 'GC=F')
    source    = d.get('source', 'yfinance')
    period    = d.get('period', '2y')
    cash      = float(d['cash']) if d.get('cash') else None
    top_n     = int(d.get('top_n', 10))
    start     = d.get('start_date') or None
    end       = d.get('end_date') or None
    param_grid = d.get('param_grid') or None
    task_id = create_task(
        f'優化:{strategy}@{symbol}',
        run_optimizer, strategy, symbol, param_grid, source, period, cash, top_n, start, end
    )
    return jsonify({'task_id': task_id})

@app.route("/api/run/download", methods=["POST"])
def api_run_download():
    d       = request.json or {}
    source  = d.get('source', 'yfinance')
    symbol  = d.get('symbol', 'GC=F')
    start   = d.get('start_date', '2024-01-01')
    end     = d.get('end_date') or None
    period  = d.get('period', '1y')
    task_id = create_task(
        f'下載:{symbol}({source})',
        download_data, source, symbol, start, end, period
    )
    return jsonify({'task_id': task_id})

@app.route("/api/run/intelligence", methods=["POST"])
def api_run_intelligence():
    d = request.json or {}
    keywords = d.get('keywords') or None
    task_id  = create_task('情報收集+分析', intelligence_cycle, keywords)
    return jsonify({'task_id': task_id})

@app.route("/api/run/x-monitor", methods=["POST"])
def api_run_x_monitor():
    d = request.json or {}
    topics  = d.get('topics') or None
    task_id = create_task('X輿情監控', x_monitor_cycle, topics)
    return jsonify({'task_id': task_id})

@app.route("/api/run/threads", methods=["POST"])
def api_run_threads():
    d = request.json or {}
    username = d.get('username') or None
    if username:
        username = username.lstrip('@').strip()
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO threads_accounts (username, added_at) VALUES (?,?)",
                    (username, datetime.now().isoformat()))
        conn.commit(); conn.close()
    task_id = create_task('Threads監控', threads_cycle)
    return jsonify({'task_id': task_id})

@app.route("/api/run/report", methods=["POST"])
def api_run_report():
    d = request.json or {}
    send_tg = bool(d.get('send_telegram', False))
    task_id = create_task('每日報告', generate_daily_report, send_tg)
    return jsonify({'task_id': task_id})

# ── Threads account management ────────────────────────────────
@app.route("/api/threads-accounts", methods=["POST"])
def api_threads_accounts_add():
    d = request.json or {}
    username = (d.get('username') or '').lstrip('@').strip()
    alias    = d.get('alias', '')
    if not username: return jsonify({'error': 'username required'}), 400
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO threads_accounts (username,alias,added_at) VALUES (?,?,?)",
                (username, alias, datetime.now().isoformat()))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'username': username})

@app.route("/api/threads-accounts/<username>", methods=["DELETE"])
def api_threads_accounts_del(username):
    conn = get_conn()
    conn.execute("DELETE FROM threads_accounts WHERE username=?", (username,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Manifest & Health ─────────────────────────────────────────
@app.route("/api/manifest")
def api_manifest():
    return jsonify({
        "name": "投資系統", "version": "2.0", "port": 18900, "icon": "📊",
        "status": "running",
    })

@app.route("/health")
def health():
    conn = get_conn()
    try:
        symbols   = conn.execute("SELECT COUNT(DISTINCT symbol) FROM market_data").fetchone()[0]
        news      = conn.execute("SELECT COUNT(*) FROM news_intelligence").fetchone()[0]
        backtests = conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
        tasks_running = sum(1 for t in _tasks.values() if t['status'] == 'running')
    finally:
        conn.close()
    return jsonify({
        "status": "ok", "name": "投資系統 v2.0",
        "symbols": symbols, "news": news, "backtests": backtests,
        "tasks_running": tasks_running,
        "timestamp": datetime.now().isoformat(),
    })

if __name__ == "__main__":
    print("=" * 50)
    print("  投資系統 Web App v2.0")
    print("  http://localhost:18900")
    print("=" * 50)
    app.run(host="0.0.0.0", port=18900, debug=False)
