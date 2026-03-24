"""
分點主力 — 券商分點進出資料
資料來源: fubon-ebrokerdj.fbs.com.tw (嘉實資訊)
每日收盤後更新，抓取各券商對個股的買賣超排行

用法:
    python broker_trading.py 2330            # 近1日
    python broker_trading.py 2330 --period 3 # 近10日
    python broker_trading.py 2330 2317 --period 2
"""
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import sys
sys.path.insert(0, str(Path(__file__).parent))
from config import DB_PATH

FUBON_URL = 'https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_{stock}_{period}.djhtm'
FUBON_DATE_URL = 'https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={stock}&e={start}&f={end}'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

# period mapping: value -> (label, approx_days)
PERIOD_MAP = {
    1: ('近一日', 1),
    2: ('近五日', 5),
    3: ('近十日', 10),
    4: ('近20日', 20),
    5: ('近40日', 40),
    6: ('近60日', 60),
    7: ('近120日', 120),
    8: ('近240日', 240),
}


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_broker_table():
    """建立分點主力資料表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tw_broker_trading (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fetch_date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            period INTEGER NOT NULL,
            side TEXT NOT NULL,
            rank INTEGER NOT NULL,
            broker_id TEXT,
            broker_name TEXT NOT NULL,
            buy_qty INTEGER DEFAULT 0,
            sell_qty INTEGER DEFAULT 0,
            net_qty INTEGER DEFAULT 0,
            pct TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(fetch_date, stock_id, period, side, rank)
        );
        CREATE INDEX IF NOT EXISTS idx_broker_stock ON tw_broker_trading(stock_id, fetch_date);
    """)
    conn.commit()
    conn.close()


def _parse_number(s):
    """解析數字字串 (移除逗號)"""
    if not s:
        return 0
    return int(s.replace(',', '').strip())


def _parse_broker_html(html):
    """解析 fubon 分點主力 HTML，回傳 (buy_list, sell_list, meta)"""
    buy_list = []
    sell_list = []
    meta = {}

    # 取得更新日期
    date_match = re.search(r'最後更新日[：:]\s*([\d/]+)', html)
    if date_match:
        meta['last_update'] = date_match.group(1).replace('/', '-')

    # 找所有資料列 (TR 包含 t4t1 和 t3n1)
    rows = re.findall(r'<TR>\s*(.*?)\s*</TR>', html, re.DOTALL | re.IGNORECASE)

    for row in rows:
        cells = re.findall(r'<TD[^>]*>(.*?)</TD>', row, re.DOTALL | re.IGNORECASE)
        if len(cells) != 10:
            continue

        # 左邊5欄: 買超券商
        buy_broker_match = re.search(r'BHID=([^"\']+)["\']>([^<]+)</a>', cells[0])
        if buy_broker_match:
            broker_id = buy_broker_match.group(1)
            broker_name = buy_broker_match.group(2).strip()
            buy_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[1]))
            sell_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[2]))
            net_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[3]))
            pct = re.sub(r'<[^>]+>', '', cells[4]).strip()
            buy_list.append({
                'broker_id': broker_id,
                'broker_name': broker_name,
                'buy_qty': buy_qty,
                'sell_qty': sell_qty,
                'net_qty': net_qty,
                'pct': pct,
            })

        # 右邊5欄: 賣超券商
        sell_broker_match = re.search(r'BHID=([^"\']+)["\']>([^<]+)</a>', cells[5])
        if sell_broker_match:
            broker_id = sell_broker_match.group(1)
            broker_name = sell_broker_match.group(2).strip()
            buy_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[6]))
            sell_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[7]))
            net_qty = _parse_number(re.sub(r'<[^>]+>', '', cells[8]))
            pct = re.sub(r'<[^>]+>', '', cells[9]).strip()
            sell_list.append({
                'broker_id': broker_id,
                'broker_name': broker_name,
                'buy_qty': buy_qty,
                'sell_qty': sell_qty,
                'net_qty': net_qty,
                'pct': pct,
            })

    # 合計
    total_buy_match = re.search(r'合計買超張數.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL | re.IGNORECASE)
    total_sell_match = re.search(r'合計賣超張數.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL | re.IGNORECASE)
    avg_buy_match = re.search(r'平均買超成本.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL | re.IGNORECASE)
    avg_sell_match = re.search(r'平均賣超成本.*?<td[^>]*>([^<]+)</td>', html, re.DOTALL | re.IGNORECASE)

    if total_buy_match:
        meta['total_buy'] = _parse_number(total_buy_match.group(1))
    if total_sell_match:
        meta['total_sell'] = _parse_number(total_sell_match.group(1))
    if avg_buy_match:
        meta['avg_buy_cost'] = avg_buy_match.group(1).strip().replace(',', '')
    if avg_sell_match:
        meta['avg_sell_cost'] = avg_sell_match.group(1).strip().replace(',', '')

    return buy_list, sell_list, meta


def fetch_broker_trading(stock_id, period=1):
    """
    抓取個股分點主力資料

    Args:
        stock_id: 股票代號 (e.g. '2330')
        period: 1=近1日, 2=近5日, 3=近10日, 4=近20日, 5=近40日, 6=近60日

    Returns:
        dict with keys: buy_list, sell_list, meta, stock_id, period
    """
    label = PERIOD_MAP.get(period, ('未知', 0))[0]
    print(f'  [分點主力] {stock_id} {label} (period={period})')

    url = FUBON_URL.format(stock=stock_id, period=period)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, verify=False)
        resp.encoding = 'big5'
        html = resp.text
    except Exception as e:
        print(f'  [分點主力] 請求失敗: {e}')
        return None

    buy_list, sell_list, meta = _parse_broker_html(html)

    if not buy_list and not sell_list:
        print(f'  [分點主力] 無資料或解析失敗')
        return None

    print(f'  [分點主力] 買超 {len(buy_list)} 家, 賣超 {len(sell_list)} 家')

    result = {
        'stock_id': stock_id,
        'period': period,
        'period_label': label,
        'buy_list': buy_list,
        'sell_list': sell_list,
        'meta': meta,
    }

    # 存入 DB
    _save_to_db(result)

    return result


def _save_to_db(result):
    """儲存分點資料到 SQLite"""
    conn = get_conn()
    today = datetime.now().strftime('%Y-%m-%d')
    stock_id = result['stock_id']
    period = result['period']

    count = 0
    for rank, item in enumerate(result['buy_list'], 1):
        try:
            conn.execute("""
                INSERT OR REPLACE INTO tw_broker_trading
                (fetch_date, stock_id, period, side, rank, broker_id, broker_name,
                 buy_qty, sell_qty, net_qty, pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (today, stock_id, period, 'buy', rank,
                  item['broker_id'], item['broker_name'],
                  item['buy_qty'], item['sell_qty'], item['net_qty'], item['pct']))
            count += 1
        except Exception:
            continue

    for rank, item in enumerate(result['sell_list'], 1):
        try:
            conn.execute("""
                INSERT OR REPLACE INTO tw_broker_trading
                (fetch_date, stock_id, period, side, rank, broker_id, broker_name,
                 buy_qty, sell_qty, net_qty, pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (today, stock_id, period, 'sell', rank,
                  item['broker_id'], item['broker_name'],
                  item['buy_qty'], item['sell_qty'], item['net_qty'], item['pct']))
            count += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    print(f'  [分點主力] 已存 {count} 筆')


def get_broker_trading(stock_id, period=1):
    """
    從 DB 讀取分點資料，若無則即時抓取

    Returns:
        dict with buy_list, sell_list, meta
    """
    conn = get_conn()
    today = datetime.now().strftime('%Y-%m-%d')

    # 檢查今日是否已有資料
    existing = conn.execute(
        "SELECT COUNT(*) as cnt FROM tw_broker_trading WHERE stock_id=? AND period=? AND fetch_date=?",
        (stock_id, period, today)
    ).fetchone()

    if existing and existing['cnt'] > 0:
        # 從 DB 讀取
        buy_rows = conn.execute(
            """SELECT * FROM tw_broker_trading
               WHERE stock_id=? AND period=? AND fetch_date=? AND side='buy'
               ORDER BY rank""",
            (stock_id, period, today)
        ).fetchall()
        sell_rows = conn.execute(
            """SELECT * FROM tw_broker_trading
               WHERE stock_id=? AND period=? AND fetch_date=? AND side='sell'
               ORDER BY rank""",
            (stock_id, period, today)
        ).fetchall()
        conn.close()

        return {
            'stock_id': stock_id,
            'period': period,
            'period_label': PERIOD_MAP.get(period, ('未知', 0))[0],
            'buy_list': [dict(r) for r in buy_rows],
            'sell_list': [dict(r) for r in sell_rows],
            'meta': {},
            'from_cache': True,
        }

    conn.close()

    # 即時抓取
    return fetch_broker_trading(stock_id, period)


def get_broker_history(stock_id, broker_name=None, days=30):
    """查詢某券商對某股票的歷史進出"""
    conn = get_conn()
    if broker_name:
        rows = conn.execute(
            """SELECT * FROM tw_broker_trading
               WHERE stock_id=? AND broker_name LIKE ? AND period=1
               ORDER BY fetch_date DESC LIMIT ?""",
            (stock_id, f'%{broker_name}%', days)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM tw_broker_trading
               WHERE stock_id=? AND period=1
               ORDER BY fetch_date DESC LIMIT ?""",
            (stock_id, days * 30)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================
# CLI
# ============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='分點主力資料下載')
    parser.add_argument('symbols', nargs='*', default=['2330'],
                        help='股票代號（預設 2330）')
    parser.add_argument('--period', type=int, default=1, choices=range(1, 9),
                        help='期間: 1=近1日, 2=近5日, 3=近10日, 4=近20日, 5=近40日, 6=近60日')
    args = parser.parse_args()

    init_broker_table()

    for sym in args.symbols:
        result = fetch_broker_trading(sym, args.period)
        if result:
            print(f'\n=== {sym} 買超 TOP ===')
            for item in result['buy_list']:
                print(f"  {item['broker_name']:12s}  買:{item['buy_qty']:>10,}  賣:{item['sell_qty']:>10,}  超:{item['net_qty']:>10,}  {item['pct']}")
            print(f'\n=== {sym} 賣超 TOP ===')
            for item in result['sell_list']:
                print(f"  {item['broker_name']:12s}  買:{item['buy_qty']:>10,}  賣:{item['sell_qty']:>10,}  超:{item['net_qty']:>10,}  {item['pct']}")
            if result['meta']:
                print(f"\n合計買超: {result['meta'].get('total_buy', '?')} 張")
                print(f"合計賣超: {result['meta'].get('total_sell', '?')} 張")
                print(f"平均買超成本: {result['meta'].get('avg_buy_cost', '?')}")
                print(f"平均賣超成本: {result['meta'].get('avg_sell_cost', '?')}")
        time.sleep(3)
