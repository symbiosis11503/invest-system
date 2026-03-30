"""
台股 / 台期 歷史資料批次下載器
來源：
  - 台灣證交所 (TWSE) — 上市個股日行情
  - 櫃買中心 (TPEx) — 上櫃 / 興櫃個股日行情
  - 台灣期交所 (TAIFEX) — 期貨日行情
  - yfinance — 國際市場 / 補充資料
"""
import time
import json
import logging
import sqlite3
import ssl
from datetime import datetime, timedelta
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DB_PATH, DATA_DIR


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================
# 台灣證交所 (TWSE) — 個股日行情
# ============================================

def fetch_twse_daily(date_str):
    """
    抓取證交所某日全市場行情
    date_str: 'YYYYMMDD' 格式，例如 '20260101'
    回傳: list of dict
    """
    url = f'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999'

    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
        data = resp.json()
    except Exception as e:
        print(f'  [TWSE] {date_str} 抓取失敗: {e}')
        return []

    if data.get('stat') != 'OK':
        return []

    # TWSE API 格式: data9 (舊) 或 tables[8].data (新, 2026+)
    rows = data.get('data9')
    if rows is None:
        tables = data.get('tables', [])
        if len(tables) > 8 and tables[8].get('data'):
            rows = tables[8]['data']
    if not rows:
        return []

    results = []
    for row in rows:
        try:
            symbol = row[0].strip()  # 證券代號
            name = row[1].strip()    # 證券名稱
            volume = int(row[2].replace(',', ''))  # 成交股數
            open_p = float(row[5].replace(',', '')) if row[5] != '--' else None
            high_p = float(row[6].replace(',', '')) if row[6] != '--' else None
            low_p = float(row[7].replace(',', '')) if row[7] != '--' else None
            close_p = float(row[8].replace(',', '')) if row[8] != '--' else None

            if open_p and close_p:
                results.append({
                    'symbol': symbol,
                    'name': name,
                    'date': f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}',
                    'open': open_p,
                    'high': high_p,
                    'low': low_p,
                    'close': close_p,
                    'volume': volume,
                })
        except (ValueError, IndexError):
            continue

    return results


def fetch_twse_stock(symbol, start_date, end_date):
    """
    抓取單一股票的歷史日行情
    symbol: 股票代號，例如 '2330'
    start_date, end_date: 'YYYY-MM-DD'
    """
    results = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    while current <= end:
        date_str = current.strftime('%Y%m%d')
        ym = current.strftime('%Y%m')
        url = f'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={date_str}&stockNo={symbol}'

        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
            data = resp.json()
        except Exception as e:
            print(f'  [TWSE] {symbol} {ym} 失敗: {e}')
            current = current.replace(day=1) + timedelta(days=32)
            current = current.replace(day=1)
            time.sleep(3)
            continue

        if data.get('stat') == 'OK' and 'data' in data:
            for row in data['data']:
                try:
                    # 日期格式: 115/01/02 (民國年)
                    parts = row[0].split('/')
                    y = int(parts[0]) + 1911
                    m = int(parts[1])
                    d = int(parts[2])
                    date = f'{y}-{m:02d}-{d:02d}'

                    volume = int(row[1].replace(',', ''))
                    open_p = float(row[3].replace(',', ''))
                    high_p = float(row[4].replace(',', ''))
                    low_p = float(row[5].replace(',', ''))
                    close_p = float(row[6].replace(',', ''))

                    results.append({
                        'symbol': symbol,
                        'date': date,
                        'open': open_p,
                        'high': high_p,
                        'low': low_p,
                        'close': close_p,
                        'volume': volume,
                    })
                except (ValueError, IndexError):
                    continue

        # 下個月
        current = current.replace(day=1) + timedelta(days=32)
        current = current.replace(day=1)
        time.sleep(3)  # 避免被封鎖

    return results


# ============================================
# 櫃買中心 (TPEx) — 上櫃個股日行情
# ============================================

def _to_minguo(date_str):
    """西元 YYYY-MM-DD 轉民國 YYY/MM/DD"""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    return f'{dt.year - 1911}/{dt.month:02d}/{dt.day:02d}'


def fetch_tpex_otc_stock(symbol, start_date, end_date):
    """
    抓取上櫃個股歷史日行情（櫃買中心）
    symbol: 股票代號，例如 '6510'
    start_date, end_date: 'YYYY-MM-DD'
    回傳: list of dict
    """
    results = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    while current <= end:
        minguo_date = _to_minguo(current.strftime('%Y-%m-%d'))
        url = 'https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php'
        params = {
            'l': 'zh-tw',
            'd': minguo_date,
            'stkno': symbol,
        }

        try:
            resp = requests.get(url, params=params,
                                headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
            data = resp.json()
        except Exception as e:
            print(f'  [TPEx OTC] {symbol} {minguo_date} 失敗: {e}')
            current = current.replace(day=1) + timedelta(days=32)
            current = current.replace(day=1)
            time.sleep(3)
            continue

        if data.get('aaData'):
            for row in data['aaData']:
                try:
                    # 日期格式: 114/01/02 (民國年)
                    parts = row[0].split('/')
                    y = int(parts[0]) + 1911
                    m = int(parts[1])
                    d = int(parts[2])
                    date = f'{y}-{m:02d}-{d:02d}'

                    volume = int(row[1].replace(',', ''))
                    close_p = float(row[2].replace(',', ''))
                    open_p = float(row[4].replace(',', ''))
                    high_p = float(row[5].replace(',', ''))
                    low_p = float(row[6].replace(',', ''))

                    if open_p and close_p:
                        results.append({
                            'symbol': symbol,
                            'date': date,
                            'open': open_p,
                            'high': high_p,
                            'low': low_p,
                            'close': close_p,
                            'volume': volume,
                        })
                except (ValueError, IndexError):
                    continue

        # 下個月
        current = current.replace(day=1) + timedelta(days=32)
        current = current.replace(day=1)
        time.sleep(3)

    return results


# ============================================
# 櫃買中心 (TPEx) — 興櫃個股日行情
# ============================================

def fetch_tpex_emerging(symbol, start_date, end_date):
    """
    抓取興櫃個股歷史日行情（櫃買中心）
    symbol: 股票代號，例如 '7814'
    start_date, end_date: 'YYYY-MM-DD'
    回傳: list of dict
    """
    results = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    while current <= end:
        minguo_date = _to_minguo(current.strftime('%Y-%m-%d'))
        url = 'https://www.tpex.org.tw/web/emergingstock/single_historical/result.php'
        params = {
            'l': 'zh-tw',
            'd': minguo_date,
            'stkno': symbol,
        }

        try:
            resp = requests.get(url, params=params,
                                headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
            data = resp.json()
        except Exception as e:
            print(f'  [TPEx Emerging] {symbol} {minguo_date} 失敗: {e}')
            current = current.replace(day=1) + timedelta(days=32)
            current = current.replace(day=1)
            time.sleep(3)
            continue

        if data.get('aaData'):
            for row in data['aaData']:
                try:
                    # 日期格式: 114/01/02 (民國年)
                    parts = row[0].split('/')
                    y = int(parts[0]) + 1911
                    m = int(parts[1])
                    d = int(parts[2])
                    date = f'{y}-{m:02d}-{d:02d}'

                    volume = int(row[1].replace(',', '')) if row[1].replace(',', '').strip() else 0
                    close_p = float(row[2].replace(',', '')) if row[2].replace(',', '').strip() else None
                    open_p = float(row[4].replace(',', '')) if row[4].replace(',', '').strip() else None
                    high_p = float(row[5].replace(',', '')) if row[5].replace(',', '').strip() else None
                    low_p = float(row[6].replace(',', '')) if row[6].replace(',', '').strip() else None

                    if open_p and close_p:
                        results.append({
                            'symbol': symbol,
                            'date': date,
                            'open': open_p,
                            'high': high_p,
                            'low': low_p,
                            'close': close_p,
                            'volume': volume,
                        })
                except (ValueError, IndexError):
                    continue

        # 下個月
        current = current.replace(day=1) + timedelta(days=32)
        current = current.replace(day=1)
        time.sleep(3)

    return results


# ============================================
# 台灣期交所 (TAIFEX) — 期貨日行情
# ============================================

def fetch_taifex_futures(product_id, start_date, end_date):
    """
    抓取期交所期貨日行情
    product_id: 'TX' (台指期), 'MTX' (小台), 'TE' (電子期), 'TF' (金融期)
    start_date, end_date: 'YYYY/MM/DD'
    """
    results = []
    current = datetime.strptime(start_date, '%Y/%m/%d')
    end = datetime.strptime(end_date, '%Y/%m/%d')

    while current <= end:
        # 期交所每次最多查 1 個月
        month_end = (current.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        if month_end > end:
            month_end = end

        q_start = current.strftime('%Y/%m/%d')
        q_end = month_end.strftime('%Y/%m/%d')

        url = 'https://www.taifex.com.tw/cht/3/futDataDown'
        post_data = {
            'down_type': '1',
            'commodity_id': product_id,
            'queryStartDate': q_start,
            'queryEndDate': q_end,
        }

        try:
            resp = requests.post(url, data=post_data,
                                 headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            content = resp.content.decode('big5', errors='ignore')
        except Exception as e:
            print(f'  [TAIFEX] {product_id} {q_start}~{q_end} 失敗: {e}')
            current = month_end + timedelta(days=1)
            time.sleep(3)
            continue

        # 解析 CSV（期交所回傳的是逗號分隔）
        lines = content.strip().split('\n')
        for line in lines[1:]:  # 跳過 header
            cols = [c.strip().strip('"') for c in line.split(',')]
            if len(cols) < 10:
                continue
            try:
                date_raw = cols[0].strip()  # YYYY/MM/DD
                contract = cols[1].strip()  # 契約月份
                open_p = float(cols[3]) if cols[3] else None
                high_p = float(cols[4]) if cols[4] else None
                low_p = float(cols[5]) if cols[5] else None
                close_p = float(cols[6]) if cols[6] else None
                volume = int(cols[7]) if cols[7] else 0

                if open_p and close_p and volume > 0:
                    # 轉日期格式
                    date = date_raw.replace('/', '-')
                    results.append({
                        'symbol': f'{product_id}_{contract}',
                        'date': date,
                        'open': open_p,
                        'high': high_p,
                        'low': low_p,
                        'close': close_p,
                        'volume': volume,
                    })
            except (ValueError, IndexError):
                continue

        current = month_end + timedelta(days=1)
        time.sleep(3)

    return results


# ============================================
# yfinance — 國際市場
# ============================================

def fetch_yfinance(symbol, period='1y'):
    """
    用 yfinance 抓取國際市場資料
    symbol: 'GC=F' (黃金), 'MGC=F' (微型黃金), '^TWII' (加權指數), 'BTC-USD'
    period: '1d','5d','1mo','3mo','6mo','1y','2y','5y','10y','max'
    """
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)

    results = []
    for date, row in df.iterrows():
        results.append({
            'symbol': symbol,
            'date': date.strftime('%Y-%m-%d'),
            'open': round(row['Open'], 2),
            'high': round(row['High'], 2),
            'low': round(row['Low'], 2),
            'close': round(row['Close'], 2),
            'volume': int(row['Volume']),
        })
    return results


# ============================================
# 儲存到 SQLite
# ============================================

def save_to_db(records, source='twse'):
    """批次存入 market_data 表"""
    if not records:
        return 0

    conn = get_conn()
    count = 0
    for r in records:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO market_data
                   (symbol, date, open, high, low, close, volume, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (r['symbol'], r['date'], r['open'], r['high'],
                 r['low'], r['close'], r['volume'], source)
            )
            count += 1
        except Exception as e:
            logging.debug(f"market_data insert skip: {e}")
            continue
    conn.commit()
    conn.close()
    return count


# ============================================
# 批次下載入口
# ============================================

def batch_download_twse_stock(symbol, start='2024-01-01', end=None):
    """批次下載台股個股歷史資料"""
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 下載台股 {symbol} ({start} ~ {end})...')
    records = fetch_twse_stock(symbol, start, end)
    saved = save_to_db(records, source='twse')
    print(f'✅ {symbol}: 共 {len(records)} 筆，存入 {saved} 筆')
    return records


def batch_download_taifex(product_id='TX', start='2024/01/01', end=None):
    """批次下載台灣期貨歷史資料"""
    if end is None:
        end = datetime.now().strftime('%Y/%m/%d')

    print(f'📥 下載期貨 {product_id} ({start} ~ {end})...')
    records = fetch_taifex_futures(product_id, start, end)
    saved = save_to_db(records, source='taifex')
    print(f'✅ {product_id}: 共 {len(records)} 筆，存入 {saved} 筆')
    return records


def batch_download_tpex_stock(symbol, start='2024-01-01', end=None):
    """批次下載上櫃個股歷史資料"""
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 下載上櫃 {symbol} ({start} ~ {end})...')
    records = fetch_tpex_otc_stock(symbol, start, end)
    saved = save_to_db(records, source='tpex_otc')
    print(f'✅ {symbol}: 共 {len(records)} 筆，存入 {saved} 筆')
    return records


def batch_download_tpex_emerging(symbol, start='2024-01-01', end=None):
    """批次下載興櫃個股歷史資料"""
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')

    print(f'📥 下載興櫃 {symbol} ({start} ~ {end})...')
    records = fetch_tpex_emerging(symbol, start, end)
    saved = save_to_db(records, source='tpex_emerging')
    print(f'✅ {symbol}: 共 {len(records)} 筆，存入 {saved} 筆')
    return records


def batch_download_yfinance(symbol, period='1y'):
    """批次下載 yfinance 資料"""
    print(f'📥 下載 {symbol} (yfinance, {period})...')
    records = fetch_yfinance(symbol, period)
    saved = save_to_db(records, source='yfinance')
    print(f'✅ {symbol}: 共 {len(records)} 筆，存入 {saved} 筆')
    return records


# ============================================
# CLI 入口
# ============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='台股/台期/國際 歷史資料下載器')
    parser.add_argument('--twse', nargs='+', help='上市股票代號，例如 2330 2317')
    parser.add_argument('--otc', nargs='+', help='上櫃股票代號，例如 6510 5765')
    parser.add_argument('--emerging', nargs='+', help='興櫃股票代號，例如 7814')
    parser.add_argument('--taifex', nargs='+', help='期貨代號，例如 TX MTX')
    parser.add_argument('--yf', nargs='+', help='yfinance 代號，例如 GC=F BTC-USD')
    parser.add_argument('--start', default='2024-01-01', help='起始日 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='結束日 YYYY-MM-DD')
    parser.add_argument('--period', default='1y', help='yfinance 期間')
    args = parser.parse_args()

    if args.twse:
        for sym in args.twse:
            batch_download_twse_stock(sym, args.start, args.end)

    if args.otc:
        for sym in args.otc:
            batch_download_tpex_stock(sym, args.start, args.end)

    if args.emerging:
        for sym in args.emerging:
            batch_download_tpex_emerging(sym, args.start, args.end)

    if args.taifex:
        start_taifex = args.start.replace('-', '/')
        end_taifex = args.end.replace('-', '/') if args.end else None
        for prod in args.taifex:
            batch_download_taifex(prod, start_taifex, end_taifex)

    if args.yf:
        for sym in args.yf:
            batch_download_yfinance(sym, args.period)

    if not (args.twse or args.otc or args.emerging or args.taifex or args.yf):
        # 預設下載：台指期 + 台積電 + 微型黃金
        print('=== 預設批次下載 ===')
        batch_download_taifex('TX', '2024/01/01')
        batch_download_taifex('MTX', '2024/01/01')
        batch_download_twse_stock('2330', '2024-01-01')
        batch_download_yfinance('GC=F', '2y')
        batch_download_yfinance('MGC=F', '1y')
        batch_download_yfinance('BTC-USD', '1y')
        print('\n=== 下載完成 ===')
