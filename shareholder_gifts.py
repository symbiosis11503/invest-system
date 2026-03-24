"""股東紀念品追蹤器 — 抓取 + 儲存 + API
來源優先序：
  1. stockgift.tw    — 伺服器端渲染 HTML，資料最完整（含零股寄單、股代電話）
  2. sinotrade.com.tw — __NEXT_DATA__ 內嵌 JSON（僅前 10 筆，但含 odd/div/price）
  3. goodinfo.tw      — 舊版 fallback（易被封鎖）
  4. histock.tw       — 舊版 fallback（易被封鎖）
"""
import sqlite3
import ssl
import os
import json
import time
import re
import urllib.request
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")

# 共用 SSL context（stockgift.tw 憑證有問題）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
       'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

# ── DB ────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_gifts_table():
    """建立 shareholder_gifts 表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shareholder_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_id TEXT NOT NULL,
            stock_name TEXT,
            meeting_date TEXT,
            last_buy_date TEXT,
            fractional_eligible TEXT DEFAULT '未知',
            gift_item TEXT,
            gift_value REAL,
            year INTEGER NOT NULL,
            source_url TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(stock_id, year)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gifts_year ON shareholder_gifts(year)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gifts_last_buy ON shareholder_gifts(last_buy_date)
    """)
    conn.commit()
    conn.close()


def upsert_gift(gift: dict):
    """插入或更新一筆紀念品資料"""
    conn = get_conn()
    conn.execute("""
        INSERT INTO shareholder_gifts
            (stock_id, stock_name, meeting_date, last_buy_date,
             fractional_eligible, gift_item, gift_value, year, source_url, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(stock_id, year) DO UPDATE SET
            stock_name = excluded.stock_name,
            meeting_date = COALESCE(excluded.meeting_date, meeting_date),
            last_buy_date = COALESCE(excluded.last_buy_date, last_buy_date),
            fractional_eligible = COALESCE(excluded.fractional_eligible, fractional_eligible),
            gift_item = COALESCE(excluded.gift_item, gift_item),
            gift_value = COALESCE(excluded.gift_value, gift_value),
            source_url = COALESCE(excluded.source_url, source_url),
            updated_at = datetime('now','localtime')
    """, (
        gift.get('stock_id'), gift.get('stock_name'),
        gift.get('meeting_date'), gift.get('last_buy_date'),
        gift.get('fractional_eligible', '未知'),
        gift.get('gift_item'), gift.get('gift_value'),
        gift.get('year', date.today().year),
        gift.get('source_url')
    ))
    conn.commit()
    conn.close()


def upsert_gifts_batch(gifts: list):
    """批次 upsert"""
    conn = get_conn()
    for g in gifts:
        conn.execute("""
            INSERT INTO shareholder_gifts
                (stock_id, stock_name, meeting_date, last_buy_date,
                 fractional_eligible, gift_item, gift_value, year, source_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(stock_id, year) DO UPDATE SET
                stock_name = excluded.stock_name,
                meeting_date = COALESCE(excluded.meeting_date, meeting_date),
                last_buy_date = COALESCE(excluded.last_buy_date, last_buy_date),
                fractional_eligible = COALESCE(excluded.fractional_eligible, fractional_eligible),
                gift_item = COALESCE(excluded.gift_item, gift_item),
                gift_value = COALESCE(excluded.gift_value, gift_value),
                source_url = COALESCE(excluded.source_url, source_url),
                updated_at = datetime('now','localtime')
        """, (
            g.get('stock_id'), g.get('stock_name'),
            g.get('meeting_date'), g.get('last_buy_date'),
            g.get('fractional_eligible', '未知'),
            g.get('gift_item'), g.get('gift_value'),
            g.get('year', date.today().year),
            g.get('source_url')
        ))
    conn.commit()
    conn.close()
    return len(gifts)


# ── 日期/數值解析 ─────────────────────────────────────

def _parse_tw_date(s: str) -> str | None:
    """解析民國或西元日期 → YYYY-MM-DD
    支援格式: 26/04/28, 115/06/15, 2026-06-15, 2026/06/15
    stockgift.tw 用 YY/MM/DD (西元後兩碼)，goodinfo 用民國年 115/06/15
    """
    if not s or not s.strip():
        return None
    s = s.strip().replace('/', '-')
    # 2026-06-15 format
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 2 or 3 digit year
    m = re.match(r'^(\d{2,3})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        yr = int(m.group(1))
        if yr < 100:
            # 西元後兩碼: 26 → 2026 (stockgift.tw 格式)
            yr += 2000
        elif yr < 200:
            # 民國年: 115 → 2026 (goodinfo 格式)
            yr += 1911
        return f"{yr}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _parse_value(s: str) -> float | None:
    """解析估值數字"""
    if not s or not s.strip():
        return None
    s = s.strip().replace(',', '').replace('元', '').replace('NT$', '').replace('$', '')
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _http_get(url: str, timeout: int = 20) -> str | None:
    """共用 HTTP GET，回傳 HTML/text"""
    req = urllib.request.Request(url, headers={
        'User-Agent': _UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
        return resp.read().decode('utf-8')
    except Exception as e:
        print(f"[http] GET {url} failed: {e}")
        return None


# ── Fetcher 1: stockgift.tw (主要來源) ─────────────────

def fetch_from_stockgift(year=None):
    """從 stockgift.tw 抓股東紀念品 — 伺服器端渲染，資料最完整
    Table 0: 已公告紀念品 (含品項、收購價、零股寄單、股代電話)
    Table 1: 未公告紀念品 (含上次紀念品、歷史發放次數)
    """
    if year is None:
        year = date.today().year

    url = 'https://stockgift.tw/STOCK/Stock/Info'
    html = _http_get(url)
    if not html:
        return []

    if '紀念品' not in html:
        print("[stockgift] blocked or empty response")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables:
        print("[stockgift] no tables found")
        return []

    results = []

    # ── Table 0: 已公告 ──
    # Headers: 持有, 股號, 股名, 股價, 最後買進日, 股東會日期, 委託截止日,
    #          紀念品, 平台收購價, 平台代領費, 新增日期, 過往條件, 備註, 性質, 零股寄單, 股代, 股代電話
    if len(tables) >= 1:
        rows = tables[0].find_all('tr')
        # 跳過前兩行（雙重 header）
        for row in rows[2:]:
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) < 8:
                continue

            sid = texts[1].strip()
            if not re.match(r'^\d{4,6}$', sid):
                continue

            # 股名可能帶有尾碼數字（如 "旭品1"、"南仁湖5"），清理之
            stock_name = re.sub(r'\d+$', '', texts[2].strip())

            gift_item = texts[7].strip() if len(texts) > 7 else None
            if gift_item in ('', '尚未公布', '尚未公告'):
                gift_item = None

            # 收購價作為估值參考
            gift_value = _parse_value(texts[8]) if len(texts) > 8 else None

            # 零股寄單
            frac = texts[14].strip() if len(texts) > 14 else ''
            if frac in ('是', '可', 'Y', 'O'):
                frac_eligible = 'Y'
            elif frac in ('否', '不可', 'N', 'X'):
                frac_eligible = 'N'
            else:
                frac_eligible = '未知'

            gift = {
                'stock_id': sid,
                'stock_name': stock_name,
                'meeting_date': _parse_tw_date(texts[5] if len(texts) > 5 else ''),
                'last_buy_date': _parse_tw_date(texts[4] if len(texts) > 4 else ''),
                'fractional_eligible': frac_eligible,
                'gift_item': gift_item,
                'gift_value': gift_value,
                'year': year,
                'source_url': url,
            }
            results.append(gift)

    # ── Table 1: 未公告（補充尚未公告但已知日期的紀念品） ──
    if len(tables) >= 2:
        rows = tables[1].find_all('tr')
        existing_ids = {r['stock_id'] for r in results}
        for row in rows[2:]:
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            if len(texts) < 6:
                continue

            # Table 1 結構: 持有, 股號(含歷史), 股名, 股價, 最後買進日, 股東會日期, ...
            # 股號欄位可能包含歷史資訊，需要特殊解析
            raw_id = texts[1].strip()
            # 從 "(3011)今皓\n..." 格式提取 ID，或直接取 4-6 碼數字
            sid_match = re.match(r'^\(?(\d{4,6})\)?', raw_id)
            if not sid_match:
                continue
            sid = sid_match.group(1)

            if sid in existing_ids:
                continue  # 已在 Table 0

            stock_name = re.sub(r'\d+$', '', texts[2].strip())

            # 上次紀念品 (Table 1 col 9)
            last_gift = texts[9].strip() if len(texts) > 9 else ''

            gift = {
                'stock_id': sid,
                'stock_name': stock_name,
                'meeting_date': _parse_tw_date(texts[5] if len(texts) > 5 else ''),
                'last_buy_date': _parse_tw_date(texts[4] if len(texts) > 4 else ''),
                'fractional_eligible': '未知',
                'gift_item': f'(未公告，上次: {last_gift})' if last_gift else None,
                'gift_value': None,
                'year': year,
                'source_url': url,
            }
            results.append(gift)

    announced = sum(1 for r in results if r['gift_item'] and '未公告' not in str(r['gift_item']))
    print(f"[stockgift] parsed {len(results)} records ({announced} announced)")
    return results


# ── Fetcher 2: sinotrade.com.tw (永豐金證券) ──────────

def fetch_from_sinotrade(year=None):
    """從 sinotrade.com.tw/richclub/tools/gifts 抓取
    利用 Next.js __NEXT_DATA__ 內嵌的 Apollo state JSON
    注意：僅含前 10 筆（伺服器端渲染的第一頁），但欄位乾淨
    """
    if year is None:
        year = date.today().year

    url = 'https://www.sinotrade.com.tw/richclub/tools/gifts'
    html = _http_get(url)
    if not html:
        return []

    # 提取 __NEXT_DATA__
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL
    )
    if not match:
        print("[sinotrade] no __NEXT_DATA__ found")
        return []

    try:
        data = json.loads(match.group(1))
        page_props = data.get('props', {}).get('pageProps', {})
        souvenir_list = page_props.get('list', {})
        filtered = souvenir_list.get('filtered', [])
        total = souvenir_list.get('total', 0)
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[sinotrade] JSON parse error: {e}")
        return []

    results = []
    for item in filtered:
        souvenir = item.get('souvenir', '').strip()
        if not souvenir or souvenir == '尚未公佈':
            souvenir = None

        # lastTransAt: "2026-04-28T00:00:00.000Z"
        last_trans = item.get('lastTransAt', '')
        last_buy = None
        if last_trans:
            m = re.match(r'^(\d{4}-\d{2}-\d{2})', last_trans)
            if m:
                last_buy = m.group(1)

        gift = {
            'stock_id': item.get('code', ''),
            'stock_name': item.get('name', ''),
            'meeting_date': None,  # sinotrade 不提供開會日
            'last_buy_date': last_buy,
            'fractional_eligible': 'Y' if item.get('odd') else 'N',
            'gift_item': souvenir,
            'gift_value': None,
            'year': year,
            'source_url': url,
        }
        if gift['stock_id']:
            results.append(gift)

    print(f"[sinotrade] parsed {len(results)} records (total on site: {total})")
    return results


# ── Fetcher 3: Goodinfo (舊版 fallback) ──────────────

def _goodinfo_headers():
    return {
        'User-Agent': _UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://goodinfo.tw/tw/index.asp',
        'Connection': 'keep-alive',
    }


def fetch_from_goodinfo(year=None):
    """從 Goodinfo 抓股東紀念品清單（易被封鎖）"""
    if year is None:
        year = date.today().year

    try:
        from curl_cffi import requests as cffi_requests
        use_cffi = True
    except ImportError:
        import requests
        use_cffi = False

    results = []
    for market in ['上市', '上櫃']:
        url = f'https://goodinfo.tw/tw/StockList.asp?MARKET_CAT={market}&INDUSTRY_CAT=股東會紀念品'
        try:
            if use_cffi:
                resp = cffi_requests.get(url, headers=_goodinfo_headers(),
                                         impersonate="chrome", timeout=30)
            else:
                import requests
                resp = requests.get(url, headers=_goodinfo_headers(), timeout=30)

            if resp.status_code != 200:
                print(f"[goodinfo] {market} HTTP {resp.status_code}")
                continue

            html = resp.text
            if len(html) < 1000 or '紀念品' not in html:
                print(f"[goodinfo] {market} — blocked or empty response")
                continue

            soup = BeautifulSoup(html, 'html.parser')
            tables = soup.find_all('table', {'id': re.compile(r'tblStockList|tblDetail')})
            if not tables:
                tables = soup.find_all('table', class_=re.compile(r'solid_1_padding_4'))
            if not tables:
                for t in soup.find_all('table'):
                    ths = [th.get_text(strip=True) for th in t.find_all('th')]
                    if '代號' in ths or '股票代號' in ths:
                        tables = [t]
                        break

            for table in tables:
                rows = table.find_all('tr')
                headers = []
                for row in rows:
                    cells = row.find_all(['th', 'td'])
                    texts = [c.get_text(strip=True) for c in cells]
                    if not headers and ('代號' in texts or '股票代號' in texts):
                        headers = texts
                        continue
                    if headers and len(texts) >= len(headers):
                        rec = dict(zip(headers, texts))
                        sid = rec.get('代號', rec.get('股票代號', '')).strip()
                        if not sid or not re.match(r'^\d{4,6}$', sid):
                            continue
                        gift = {
                            'stock_id': sid,
                            'stock_name': rec.get('名稱', rec.get('公司名稱', '')).strip(),
                            'meeting_date': _parse_tw_date(rec.get('股東會日期', rec.get('召開日', ''))),
                            'last_buy_date': _parse_tw_date(rec.get('最後買進日', '')),
                            'fractional_eligible': '未知',
                            'gift_item': rec.get('紀念品', rec.get('紀念品品項', '')).strip() or None,
                            'gift_value': _parse_value(rec.get('紀念品估值', rec.get('估值', ''))),
                            'year': year,
                            'source_url': url,
                        }
                        frac = rec.get('零股', rec.get('零股可領', '')).strip()
                        if frac:
                            if frac in ('可', 'Y', '是', 'O', '○'):
                                gift['fractional_eligible'] = 'Y'
                            elif frac in ('否', 'N', '不可', 'X', '×'):
                                gift['fractional_eligible'] = 'N'
                        results.append(gift)

            print(f"[goodinfo] {market}: parsed {len(results)} records")
            time.sleep(3)

        except Exception as e:
            print(f"[goodinfo] {market} error: {e}")
            continue

    return results


# ── Fetcher 4: HiStock (舊版 fallback) ──────────────

def fetch_from_histock(year=None):
    """從 HiStock 抓股東紀念品（易被封鎖）"""
    if year is None:
        year = date.today().year

    try:
        from curl_cffi import requests as cffi_requests
        use_cffi = True
    except ImportError:
        import requests
        use_cffi = False

    url = f'https://histock.tw/stock/shareholdergift.aspx?y={year}'
    headers = {
        'User-Agent': _UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-TW,zh;q=0.9',
    }

    try:
        if use_cffi:
            resp = cffi_requests.get(url, headers=headers, impersonate="chrome", timeout=30)
        else:
            import requests
            resp = requests.get(url, headers=headers, timeout=30)

        if resp.status_code != 200:
            print(f"[histock] HTTP {resp.status_code}")
            return []

        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')
        results = []

        table = soup.find('table', class_=re.compile(r'gvTB|tb-stock'))
        if not table:
            for t in soup.find_all('table'):
                text = t.get_text()
                if '紀念品' in text and '代號' in text:
                    table = t
                    break

        if not table:
            print("[histock] no table found")
            return []

        rows = table.find_all('tr')
        headers = []
        for row in rows:
            cells = row.find_all(['th', 'td'])
            texts = [c.get_text(strip=True) for c in cells]
            if not headers and any('代號' in t for t in texts):
                headers = texts
                continue
            if headers and len(texts) >= 3:
                rec = dict(zip(headers, texts))
                sid = ''
                for key in ['代號', '股票代號', '股號']:
                    if key in rec:
                        sid = rec[key].strip()
                        break
                if not sid or not re.match(r'^\d{4,6}$', sid):
                    continue
                gift = {
                    'stock_id': sid,
                    'stock_name': rec.get('名稱', rec.get('股票', rec.get('公司', ''))).strip(),
                    'meeting_date': _parse_tw_date(rec.get('股東會日期', rec.get('開會日', ''))),
                    'last_buy_date': _parse_tw_date(rec.get('最後買進日', '')),
                    'fractional_eligible': '未知',
                    'gift_item': rec.get('紀念品', rec.get('贈品', '')).strip() or None,
                    'gift_value': _parse_value(rec.get('價值', rec.get('估值', ''))),
                    'year': year,
                    'source_url': url,
                }
                results.append(gift)

        print(f"[histock] parsed {len(results)} records")
        return results

    except Exception as e:
        print(f"[histock] error: {e}")
        return []


# ── 主要入口 ──────────────────────────────────────────

def fetch_gifts(year=None):
    """抓取股東紀念品，依序嘗試多個來源
    優先序: stockgift.tw → sinotrade → goodinfo → histock
    """
    if year is None:
        year = date.today().year

    init_gifts_table()

    # 來源 1: stockgift.tw (主力)
    print("[fetch] Trying stockgift.tw...")
    gifts = fetch_from_stockgift(year)

    # 來源 2: sinotrade (補充，合併進 gifts)
    if len(gifts) < 50:
        print("[fetch] stockgift.tw insufficient, trying sinotrade...")
        sino_gifts = fetch_from_sinotrade(year)
        if sino_gifts:
            existing_ids = {g['stock_id'] for g in gifts}
            for sg in sino_gifts:
                if sg['stock_id'] not in existing_ids:
                    gifts.append(sg)
            print(f"[fetch] merged sinotrade, total: {len(gifts)}")

    # 來源 3: Goodinfo fallback
    if not gifts:
        print("[fetch] Primary sources failed, trying Goodinfo...")
        gifts = fetch_from_goodinfo(year)

    # 來源 4: HiStock fallback
    if not gifts:
        print("[fetch] Goodinfo failed, trying HiStock...")
        gifts = fetch_from_histock(year)

    if gifts:
        # 只保留有實際紀念品名稱的記錄（排除純「未公告」）
        valid_gifts = [g for g in gifts if g.get('gift_item')]
        count = upsert_gifts_batch(valid_gifts) if valid_gifts else 0
        print(f"[fetch] Saved {count} shareholder gifts for {year} (total parsed: {len(gifts)})")
        return count

    print(f"[fetch] No gifts fetched for {year}. All sources failed.")
    print("[fetch] You can manually import via import_from_json()")
    return 0


def import_from_json(filepath: str):
    """從 JSON 檔案匯入紀念品資料
    JSON 格式: [{"stock_id": "2330", "stock_name": "台積電", ...}, ...]
    """
    init_gifts_table()
    with open(filepath, 'r', encoding='utf-8') as f:
        gifts = json.load(f)
    count = upsert_gifts_batch(gifts)
    print(f"[import] Imported {count} records from {filepath}")
    return count


def import_sample_data():
    """匯入範例資料（用於開發測試）"""
    init_gifts_table()
    samples = [
        {"stock_id": "2412", "stock_name": "中華電", "meeting_date": "2026-06-18", "last_buy_date": "2026-04-17", "fractional_eligible": "Y", "gift_item": "環保餐具組", "gift_value": 50, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1101", "stock_name": "台泥", "meeting_date": "2026-06-20", "last_buy_date": "2026-04-19", "fractional_eligible": "Y", "gift_item": "購物袋", "gift_value": 30, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1216", "stock_name": "統一", "meeting_date": "2026-06-25", "last_buy_date": "2026-04-24", "fractional_eligible": "Y", "gift_item": "統一麵禮盒", "gift_value": 80, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2002", "stock_name": "中鋼", "meeting_date": "2026-06-27", "last_buy_date": "2026-04-24", "fractional_eligible": "Y", "gift_item": "中鋼碗組", "gift_value": 120, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1802", "stock_name": "台玻", "meeting_date": "2026-06-13", "last_buy_date": "2026-04-10", "fractional_eligible": "N", "gift_item": "玻璃保鮮盒", "gift_value": 150, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "9910", "stock_name": "豐泰", "meeting_date": "2026-06-17", "last_buy_date": "2026-04-16", "fractional_eligible": "Y", "gift_item": "運動毛巾", "gift_value": 60, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1301", "stock_name": "台塑", "meeting_date": "2026-06-19", "last_buy_date": "2026-04-17", "fractional_eligible": "Y", "gift_item": "洗衣精禮盒", "gift_value": 100, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2207", "stock_name": "和泰車", "meeting_date": "2026-06-12", "last_buy_date": "2026-04-09", "fractional_eligible": "N", "gift_item": "模型車", "gift_value": 200, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2912", "stock_name": "統一超", "meeting_date": "2026-06-16", "last_buy_date": "2026-04-14", "fractional_eligible": "Y", "gift_item": "7-11商品卡", "gift_value": 100, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2885", "stock_name": "元大金", "meeting_date": "2026-06-10", "last_buy_date": "2026-04-08", "fractional_eligible": "Y", "gift_item": "不鏽鋼保溫杯", "gift_value": 90, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2884", "stock_name": "玉山金", "meeting_date": "2026-06-11", "last_buy_date": "2026-04-09", "fractional_eligible": "Y", "gift_item": "收納盒", "gift_value": 40, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2892", "stock_name": "第一金", "meeting_date": "2026-06-24", "last_buy_date": "2026-04-23", "fractional_eligible": "Y", "gift_item": "毛毯", "gift_value": 70, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "5880", "stock_name": "合庫金", "meeting_date": "2026-06-26", "last_buy_date": "2026-04-24", "fractional_eligible": "Y", "gift_item": "柔膚巾禮盒", "gift_value": 55, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2801", "stock_name": "彰銀", "meeting_date": "2026-06-23", "last_buy_date": "2026-04-22", "fractional_eligible": "N", "gift_item": "面紙禮盒", "gift_value": 35, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "6505", "stock_name": "台塑化", "meeting_date": "2026-06-19", "last_buy_date": "2026-04-17", "fractional_eligible": "Y", "gift_item": "擦拭布組", "gift_value": 45, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "3045", "stock_name": "台灣大", "meeting_date": "2026-06-15", "last_buy_date": "2026-04-13", "fractional_eligible": "Y", "gift_item": "手機架", "gift_value": 65, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1326", "stock_name": "台化", "meeting_date": "2026-06-19", "last_buy_date": "2026-04-17", "fractional_eligible": "Y", "gift_item": "清潔劑禮盒", "gift_value": 85, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "2105", "stock_name": "正新", "meeting_date": "2026-05-30", "last_buy_date": "2026-03-28", "fractional_eligible": "Y", "gift_item": "鑰匙圈", "gift_value": 25, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1102", "stock_name": "亞泥", "meeting_date": "2026-06-05", "last_buy_date": "2026-04-02", "fractional_eligible": "Y", "gift_item": "環保杯", "gift_value": 75, "year": 2026, "source_url": "https://goodinfo.tw"},
        {"stock_id": "1402", "stock_name": "遠東新", "meeting_date": "2026-06-08", "last_buy_date": "2026-04-07", "fractional_eligible": "N", "gift_item": "毛巾禮盒", "gift_value": 60, "year": 2026, "source_url": "https://goodinfo.tw"},
    ]
    count = upsert_gifts_batch(samples)
    print(f"[sample] Imported {count} sample records")
    return count


def get_all_gifts(year=None, month=None):
    """查詢所有紀念品，含最新股價"""
    conn = get_conn()
    sql = "SELECT * FROM shareholder_gifts WHERE 1=1"
    params = []
    if year:
        sql += " AND year = ?"
        params.append(year)
    if month:
        sql += " AND CAST(SUBSTR(meeting_date, 6, 2) AS INTEGER) = ?"
        params.append(month)
    sql += " ORDER BY last_buy_date ASC, meeting_date ASC"
    rows = conn.execute(sql, params).fetchall()
    gifts = [dict(r) for r in rows]

    # Batch fetch latest prices from market_data
    if gifts:
        stock_ids = list({g['stock_id'] for g in gifts})
        placeholders = ','.join('?' for _ in stock_ids)
        price_rows = conn.execute(f"""
            SELECT symbol, close FROM market_data
            WHERE symbol IN ({placeholders})
            AND date = (SELECT MAX(date) FROM market_data WHERE symbol = market_data.symbol)
        """, stock_ids).fetchall()
        price_map = {r['symbol']: r['close'] for r in price_rows}
        for g in gifts:
            g['last_price'] = price_map.get(g['stock_id'])

    conn.close()
    return gifts


def get_upcoming_gifts(days=30):
    """查詢即將截止買進的紀念品"""
    conn = get_conn()
    today = date.today().isoformat()
    future = (date.today() + timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT * FROM shareholder_gifts
        WHERE last_buy_date >= ? AND last_buy_date <= ?
        ORDER BY last_buy_date ASC
    """, (today, future)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── CLI ───────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    init_gifts_table()

    if len(sys.argv) > 1 and sys.argv[1] == '--sample':
        import_sample_data()
    elif len(sys.argv) > 1 and sys.argv[1] == '--import' and len(sys.argv) > 2:
        import_from_json(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == '--stockgift':
        # 單獨測試 stockgift.tw
        gifts = fetch_from_stockgift()
        print(f"Got {len(gifts)} from stockgift.tw")
        for g in gifts[:5]:
            print(f"  {g['stock_id']} {g['stock_name']} | {g['gift_item']} | 最後買進: {g['last_buy_date']}")
    elif len(sys.argv) > 1 and sys.argv[1] == '--sinotrade':
        # 單獨測試 sinotrade
        gifts = fetch_from_sinotrade()
        print(f"Got {len(gifts)} from sinotrade")
        for g in gifts[:5]:
            print(f"  {g['stock_id']} {g['stock_name']} | {g['gift_item']} | 最後買進: {g['last_buy_date']}")
    else:
        year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
        count = fetch_gifts(year)
        if count == 0:
            print("No data from web sources. Loading sample data...")
            import_sample_data()

    # 顯示結果
    gifts = get_all_gifts()
    print(f"\n=== 共 {len(gifts)} 筆紀念品資料 ===")
    for g in gifts[:5]:
        print(f"  {g['stock_id']} {g['stock_name']} | {g['gift_item']} | 最後買進: {g['last_buy_date']}")
    if len(gifts) > 5:
        print(f"  ... 還有 {len(gifts) - 5} 筆")
