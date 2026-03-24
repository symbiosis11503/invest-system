"""
FinMind API 整合模組
台股籌碼面 + 基本面 + 技術面資料
文件: https://finmind.github.io/

免費額度: 未註冊 300次/hr, 註冊 600次/hr
"""
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

import requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH, load_env

load_env()

API_URL = 'https://api.finmindtrade.com/api/v4/data'
_session = requests.Session()
_session.headers.update({'User-Agent': 'Mozilla/5.0'})


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_finmind_db():
    """建立 FinMind 相關資料表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tw_institutional (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            foreign_buy INTEGER DEFAULT 0,
            foreign_sell INTEGER DEFAULT 0,
            foreign_net INTEGER DEFAULT 0,
            trust_buy INTEGER DEFAULT 0,
            trust_sell INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_buy INTEGER DEFAULT 0,
            dealer_sell INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            total_net INTEGER DEFAULT 0,
            UNIQUE(date, symbol)
        );

        CREATE TABLE IF NOT EXISTS tw_margin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            margin_buy INTEGER DEFAULT 0,
            margin_sell INTEGER DEFAULT 0,
            margin_balance INTEGER DEFAULT 0,
            short_buy INTEGER DEFAULT 0,
            short_sell INTEGER DEFAULT 0,
            short_balance INTEGER DEFAULT 0,
            UNIQUE(date, symbol)
        );

        CREATE TABLE IF NOT EXISTS tw_revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            revenue REAL DEFAULT 0,
            revenue_yoy REAL DEFAULT 0,
            revenue_mom REAL DEFAULT 0,
            UNIQUE(date, symbol)
        );

        CREATE TABLE IF NOT EXISTS tw_per (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            per REAL,
            pbr REAL,
            dividend_yield REAL,
            UNIQUE(date, symbol)
        );
    """)
    conn.commit()
    conn.close()


def _fetch(dataset, params):
    """通用 FinMind API 呼叫"""
    params['dataset'] = dataset
    try:
        resp = _session.get(API_URL, params=params, timeout=30)
        data = resp.json()
        if data.get('status') != 200:
            print(f"  [FinMind] {dataset} 錯誤: {data.get('msg', 'unknown')}")
            return []
        return data.get('data', [])
    except Exception as e:
        print(f"  [FinMind] {dataset} 失敗: {e}")
        return []


# ============================================
# 三大法人買賣超
# ============================================

def fetch_institutional(symbol, start_date, end_date=None):
    """取得個股三大法人買賣超"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 [FinMind] 法人買賣超 {symbol} ({start_date} ~ {end_date})')
    rows = _fetch('TaiwanStockInstitutionalInvestorsBuySell', {
        'data_id': symbol,
        'start_date': start_date,
        'end_date': end_date,
    })

    if not rows:
        return 0

    daily = {}
    for r in rows:
        date = r.get('date', '')
        if date not in daily:
            daily[date] = {
                'date': date, 'symbol': symbol,
                'foreign_buy': 0, 'foreign_sell': 0, 'foreign_net': 0,
                'trust_buy': 0, 'trust_sell': 0, 'trust_net': 0,
                'dealer_buy': 0, 'dealer_sell': 0, 'dealer_net': 0,
            }
        name = r.get('name', '')
        buy = int(r.get('buy', 0))
        sell = int(r.get('sell', 0))

        if '外資' in name or 'Foreign' in name:
            daily[date]['foreign_buy'] += buy
            daily[date]['foreign_sell'] += sell
            daily[date]['foreign_net'] += buy - sell
        elif '投信' in name or 'Investment Trust' in name:
            daily[date]['trust_buy'] += buy
            daily[date]['trust_sell'] += sell
            daily[date]['trust_net'] += buy - sell
        elif '自營商' in name or 'Dealer' in name:
            daily[date]['dealer_buy'] += buy
            daily[date]['dealer_sell'] += sell
            daily[date]['dealer_net'] += buy - sell

    for d in daily.values():
        d['total_net'] = d['foreign_net'] + d['trust_net'] + d['dealer_net']

    rows_to_insert = [
        (d['date'], d['symbol'],
         d['foreign_buy'], d['foreign_sell'], d['foreign_net'],
         d['trust_buy'], d['trust_sell'], d['trust_net'],
         d['dealer_buy'], d['dealer_sell'], d['dealer_net'],
         d['total_net'])
        for d in daily.values()
    ]

    conn = get_conn()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO tw_institutional
            (date, symbol, foreign_buy, foreign_sell, foreign_net,
             trust_buy, trust_sell, trust_net,
             dealer_buy, dealer_sell, dealer_net, total_net)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows_to_insert)
        count = len(rows_to_insert)
        conn.commit()
    except Exception as e:
        print(f'  [DB] 法人寫入失敗: {e}')
        count = 0
    finally:
        conn.close()

    print(f'  ✅ {count} 筆')
    return count


# ============================================
# 融資融券
# ============================================

def fetch_margin(symbol, start_date, end_date=None):
    """取得個股融資融券"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 [FinMind] 融資融券 {symbol} ({start_date} ~ {end_date})')
    rows = _fetch('TaiwanStockMarginPurchaseShortSale', {
        'data_id': symbol,
        'start_date': start_date,
        'end_date': end_date,
    })

    rows_to_insert = [
        (
            r.get('date', ''),
            symbol,
            int(r.get('MarginPurchaseBuy', 0)),
            int(r.get('MarginPurchaseSell', 0)),
            int(r.get('MarginPurchaseTodayBalance', 0)),
            int(r.get('ShortSaleBuy', 0)),
            int(r.get('ShortSaleSell', 0)),
            int(r.get('ShortSaleTodayBalance', 0)),
        )
        for r in rows
    ]

    conn = get_conn()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO tw_margin
            (date, symbol, margin_buy, margin_sell, margin_balance,
             short_buy, short_sell, short_balance)
            VALUES (?,?,?,?,?,?,?,?)
        """, rows_to_insert)
        count = len(rows_to_insert)
        conn.commit()
    except Exception as e:
        print(f'  [DB] 融資寫入失敗: {e}')
        count = 0
    finally:
        conn.close()

    print(f'  ✅ {count} 筆')
    return count


# ============================================
# 月營收
# ============================================

def fetch_revenue(symbol, start_date, end_date=None):
    """取得個股月營收"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 [FinMind] 月營收 {symbol} ({start_date} ~ {end_date})')
    rows = _fetch('TaiwanStockMonthRevenue', {
        'data_id': symbol,
        'start_date': start_date,
        'end_date': end_date,
    })

    rows_to_insert = [
        (
            r.get('date', ''),
            symbol,
            float(r.get('revenue', 0)),
            float(r.get('revenue_year_growth_rate', 0)),
            float(r.get('revenue_month_growth_rate', 0)),
        )
        for r in rows
    ]

    conn = get_conn()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO tw_revenue
            (date, symbol, revenue, revenue_yoy, revenue_mom)
            VALUES (?,?,?,?,?)
        """, rows_to_insert)
        count = len(rows_to_insert)
        conn.commit()
    except Exception as e:
        print(f'  [DB] 營收寫入失敗: {e}')
        count = 0
    finally:
        conn.close()

    print(f'  ✅ {count} 筆')
    return count


# ============================================
# 本益比 / 股價淨值比 / 殖利率
# ============================================

def fetch_per(symbol, start_date, end_date=None):
    """取得個股本益比/淨值比/殖利率"""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 [FinMind] PER/PBR {symbol} ({start_date} ~ {end_date})')
    rows = _fetch('TaiwanStockPER', {
        'data_id': symbol,
        'start_date': start_date,
        'end_date': end_date,
    })

    rows_to_insert = [
        (
            r.get('date', ''),
            symbol,
            float(r.get('PER', 0)) if r.get('PER') else None,
            float(r.get('PBR', 0)) if r.get('PBR') else None,
            float(r.get('dividend_yield', 0)) if r.get('dividend_yield') else None,
        )
        for r in rows
    ]

    conn = get_conn()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO tw_per
            (date, symbol, per, pbr, dividend_yield)
            VALUES (?,?,?,?,?)
        """, rows_to_insert)
        count = len(rows_to_insert)
        conn.commit()
    except Exception as e:
        print(f'  [DB] PER 寫入失敗: {e}')
        count = 0
    finally:
        conn.close()

    print(f'  ✅ {count} 筆')
    return count


# ============================================
# 批次下載（4 種類型並行）
# ============================================

def batch_download(symbol, start_date='2024-01-01'):
    """一次下載某股票的所有籌碼面資料（4 種類型並行）"""
    print(f'\n=== 批次下載 {symbol} 籌碼資料 ===')

    tasks = [
        (fetch_institutional, symbol, start_date),
        (fetch_margin, symbol, start_date),
        (fetch_revenue, symbol, start_date),
        (fetch_per, symbol, start_date),
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn, sym, sd): fn.__name__
                   for fn, sym, sd in tasks}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f'  [{name}] 失敗: {e}')

    print(f'=== {symbol} 完成 ===\n')


# ============================================
# CLI
# ============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='FinMind 台股籌碼資料下載')
    parser.add_argument('symbols', nargs='*', default=['2330'],
                        help='股票代號（預設 2330）')
    parser.add_argument('--start', default='2024-01-01', help='起始日期')
    parser.add_argument('--type', choices=['all', 'inst', 'margin', 'revenue', 'per'],
                        default='all', help='資料類型')
    parser.add_argument('--workers', type=int, default=2, help='並行股票數（預設 2）')
    args = parser.parse_args()

    init_finmind_db()

    fn_map = {
        'inst': fetch_institutional,
        'margin': fetch_margin,
        'revenue': fetch_revenue,
        'per': fetch_per,
    }

    if args.type == 'all':
        # 多股票並行（每支股票內部 4 種類型並行）
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(batch_download, sym, args.start): sym
                       for sym in args.symbols}
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f'  [{sym}] 失敗: {e}')
    else:
        fn = fn_map[args.type]
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fn, sym, args.start): sym
                       for sym in args.symbols}
            for future in as_completed(futures):
                sym = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f'  [{sym}] 失敗: {e}')
