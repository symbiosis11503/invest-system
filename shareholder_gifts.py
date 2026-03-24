"""股東紀念品追蹤器 — 抓取 + 儲存 + API"""
import sqlite3
import os
import json
import time
import re
from datetime import datetime, date
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")

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


# ── Fetcher: Goodinfo ─────────────────────────────────

def _goodinfo_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://goodinfo.tw/tw/index.asp',
        'Connection': 'keep-alive',
    }


def _parse_tw_date(s: str) -> str | None:
    """解析民國或西元日期 → YYYY-MM-DD"""
    if not s or not s.strip():
        return None
    s = s.strip().replace('/', '-')
    # 2026-06-15 format
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 115/06/15 民國 format
    m = re.match(r'^(\d{2,3})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        yr = int(m.group(1))
        if yr < 200:
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


def fetch_from_goodinfo(year=None):
    """從 Goodinfo 抓股東紀念品清單"""
    if year is None:
        year = date.today().year

    try:
        from curl_cffi import requests as cffi_requests
        use_cffi = True
    except ImportError:
        import requests
        use_cffi = False

    # Goodinfo 有上市 + 上櫃
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
            # 找包含紀念品資料的表格
            tables = soup.find_all('table', {'id': re.compile(r'tblStockList|tblDetail')})
            if not tables:
                tables = soup.find_all('table', class_=re.compile(r'solid_1_padding_4'))
            if not tables:
                # fallback: 找所有有 '代號' 標頭的表格
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
                        # 零股欄位
                        frac = rec.get('零股', rec.get('零股可領', '')).strip()
                        if frac:
                            if frac in ('可', 'Y', '是', 'O', '○'):
                                gift['fractional_eligible'] = 'Y'
                            elif frac in ('否', 'N', '不可', 'X', '×'):
                                gift['fractional_eligible'] = 'N'
                        results.append(gift)

            print(f"[goodinfo] {market}: parsed {len(results)} records")
            time.sleep(3)  # 禮貌延遲

        except Exception as e:
            print(f"[goodinfo] {market} error: {e}")
            continue

    return results


# ── Fetcher: HiStock ──────────────────────────────────

def fetch_from_histock(year=None):
    """從 HiStock 抓股東紀念品 (備用)"""
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
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
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

        # 找 table
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
    """抓取股東紀念品，嘗試多個來源"""
    if year is None:
        year = date.today().year

    init_gifts_table()

    # 來源 1: Goodinfo
    gifts = fetch_from_goodinfo(year)

    # 來源 2: HiStock (如果 Goodinfo 沒抓到)
    if not gifts:
        print("[fetch] Goodinfo failed, trying HiStock...")
        gifts = fetch_from_histock(year)

    if gifts:
        count = upsert_gifts_batch(gifts)
        print(f"[fetch] Saved {count} shareholder gifts for {year}")
        return count

    print(f"[fetch] No gifts fetched for {year}. Sources may be blocked.")
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
    """查詢所有紀念品"""
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
    conn.close()
    return [dict(r) for r in rows]


def get_upcoming_gifts(days=30):
    """查詢即將截止買進的紀念品"""
    conn = get_conn()
    today = date.today().isoformat()
    future = (date.today() + __import__('datetime').timedelta(days=days)).isoformat()
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
