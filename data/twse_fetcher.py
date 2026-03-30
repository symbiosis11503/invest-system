"""TWSE OpenAPI 公開資料抓取器 — PER/EPS/月營收/重大公告/融資融券/借券/月均價/外資類股/除權息"""
import requests
import json
import logging
import sqlite3
import re
import time
import os
from datetime import datetime
import urllib3
urllib3.disable_warnings()

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'db', 'trades.db')
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# TWSE OpenAPI 端點（免費、無須認證、JSON）
API = {
    "per": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d",
    "eps": "https://openapi.twse.com.tw/v1/opendata/t187ap14_L",
    "revenue": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "news": "https://openapi.twse.com.tw/v1/news/newsList",
    # Phase 2
    "stock_day_avg": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_AVG_ALL",
    "sbl": "https://openapi.twse.com.tw/v1/SBL/TWT96U",
    "qfiis_cat": "https://openapi.twse.com.tw/v1/fund/MI_QFIIS_cat",
    "yearly_trade": "https://openapi.twse.com.tw/v1/exchangeReport/FMNPTK_ALL",
    "ex_dividend": "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    """建立所有指標表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tw_eps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            year INTEGER,
            quarter INTEGER,
            eps REAL,
            revenue REAL,
            profit REAL,
            date TEXT,
            UNIQUE(symbol, year, quarter)
        );
        CREATE TABLE IF NOT EXISTS tw_director_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT,
            director_name TEXT,
            shares_held INTEGER,
            share_pct REAL,
            pledge_pct REAL,
            UNIQUE(symbol, date, director_name)
        );
        CREATE TABLE IF NOT EXISTS tw_major_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            date TEXT,
            title TEXT,
            content TEXT,
            source TEXT DEFAULT 'MOPS',
            UNIQUE(symbol, date, title)
        );
    """)
    conn.commit()
    conn.close()
    print("Tables ready")


def fetch_per():
    """從 TWSE OpenAPI 抓 PER/PBR/殖利率（每日更新）"""
    try:
        resp = requests.get(API["per"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        count = 0
        for d in data:
            code = d.get("Code", "")
            per = d.get("PEratio", "")
            dy = d.get("DividendYield", "")
            pbr = d.get("PBratio", "")

            if not code:
                continue

            try:
                per_val = float(per) if per else None
                dy_val = float(dy) if dy else 0
                pbr_val = float(pbr) if pbr else 0

                conn.execute("""
                    INSERT OR REPLACE INTO tw_per (symbol, date, per, pbr, dividend_yield)
                    VALUES (?, date('now','localtime'), ?, ?, ?)
                """, (code, per_val, pbr_val, dy_val))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"PER/PBR updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_per error: {e}")
        return 0


def fetch_quarterly_eps():
    """從 TWSE OpenAPI 抓季度 EPS（t187ap14_L）

    此 API 回傳最新公布的季度 EPS，含營收/營業利益/稅後淨利。
    民國年 → 西元年: +1911
    """
    try:
        resp = requests.get(API["eps"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        count = 0
        for d in data:
            code = d.get("公司代號", "").strip()
            if not re.match(r'^\d{4}$', code):
                continue

            roc_year = d.get("年度", "")
            quarter = d.get("季別", "")
            eps_str = d.get("基本每股盈餘(元)", "")
            rev_str = d.get("營業收入", "")
            profit_str = d.get("稅後淨利", "")

            try:
                year = int(roc_year) + 1911
                q = int(quarter)
                eps_val = float(eps_str) if eps_str else None
                rev_val = float(rev_str.replace(",", "")) * 1000 if rev_str else 0  # 千元
                profit_val = float(profit_str.replace(",", "")) * 1000 if profit_str else 0

                conn.execute("""
                    INSERT OR REPLACE INTO tw_eps (symbol, year, quarter, eps, revenue, profit, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (code, year, q, eps_val, rev_val, profit_val, f"{year}-Q{q}"))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"EPS updated: {count} stocks (latest quarter)")
        return count
    except Exception as e:
        print(f"fetch_quarterly_eps error: {e}")
        return 0


def fetch_monthly_revenue():
    """從 TWSE OpenAPI 抓最新月營收（t187ap05_L）

    更新 tw_revenue 表，含 YoY/MoM。
    """
    try:
        resp = requests.get(API["revenue"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        count = 0
        for d in data:
            code = d.get("公司代號", "").strip()
            if not re.match(r'^\d{4}$', code):
                continue

            date_str = d.get("資料年月", "")  # e.g. "11502"
            rev_str = d.get("營業收入-當月營收", "")
            yoy_str = d.get("營業收入-去年同月增減(%)", "")
            mom_str = d.get("營業收入-上月比較增減(%)", "")

            try:
                # 民國年月 → 西元年月
                if len(date_str) >= 4:
                    roc_y = int(date_str[:3])
                    m = int(date_str[3:])
                    date_fmt = f"{roc_y + 1911}-{m:02d}"
                else:
                    continue

                rev_val = float(rev_str.replace(",", "")) * 1000 if rev_str else 0
                yoy_val = float(yoy_str) if yoy_str else 0
                mom_val = float(mom_str) if mom_str else 0

                conn.execute("""
                    INSERT OR REPLACE INTO tw_revenue (symbol, date, revenue, revenue_yoy, revenue_mom)
                    VALUES (?, ?, ?, ?, ?)
                """, (code, date_fmt, rev_val, yoy_val, mom_val))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"Monthly revenue updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_monthly_revenue error: {e}")
        return 0


def fetch_major_announcements():
    """從 TWSE OpenAPI 抓重大訊息"""
    try:
        resp = requests.get(API["news"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        count = 0
        for d in data:
            title = d.get("title", "")
            date = d.get("date", "")
            code_match = re.search(r'(\d{4})', title)
            symbol = code_match.group(1) if code_match else None

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO tw_major_announcements (symbol, date, title, content)
                    VALUES (?, ?, ?, ?)
                """, (symbol, date, title, d.get("content", "")))
                count += 1
            except Exception as e:
                logging.debug(f"announcement insert skip: {e}")
                continue

        conn.commit()
        conn.close()
        print(f"Announcements: {count} new")
        return count
    except Exception as e:
        print(f"fetch_announcements error: {e}")
        return 0


def fetch_holiday_schedule():
    """從 TWSE OpenAPI 抓休市日曆，存入 DB，回傳休市日列表"""
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
            timeout=15, verify=False, headers=HEADERS
        )
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_holidays (
                date TEXT PRIMARY KEY,
                name TEXT,
                weekday TEXT,
                description TEXT,
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)

        holidays = []
        for item in data:
            roc_date = item.get("Date", "")
            if len(roc_date) != 7:
                continue
            year = int(roc_date[:3]) + 1911
            month = roc_date[3:5]
            day = roc_date[5:7]
            date_str = f"{year}-{month}-{day}"
            name = item.get("Name", "")
            desc = item.get("Description", "")

            # 只存非交易日（排除「開始交易」的標記）
            if "開始交易" in name:
                continue

            conn.execute("""
                INSERT OR REPLACE INTO tw_holidays (date, name, weekday, description)
                VALUES (?, ?, ?, ?)
            """, (date_str, name, item.get("Weekday", ""), desc))
            holidays.append(date_str)

        conn.commit()
        conn.close()
        print(f"Holiday schedule: {len(holidays)} days saved")
        return holidays
    except Exception as e:
        print(f"fetch_holiday_schedule error: {e}")
        return []


def is_trading_day(date_str=None):
    """檢查指定日期是否為交易日（非週末 + 非休市日）

    Args:
        date_str: YYYY-MM-DD 格式，預設今天
    Returns:
        bool: True = 交易日
    """
    from datetime import date
    if date_str is None:
        d = date.today()
        date_str = d.strftime("%Y-%m-%d")
    else:
        d = date.fromisoformat(date_str)

    # 週末不交易
    if d.weekday() >= 5:
        return False

    # 查 DB 休市日
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM tw_holidays WHERE date = ?", (date_str,)
        ).fetchone()
        conn.close()
        return row is None
    except Exception:
        # DB 沒有 tw_holidays 表，退回只檢查週末
        return True


def fetch_margin_trading():
    """從 TWSE OpenAPI 抓融資融券（每日更新）"""
    try:
        resp = requests.get(
            "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
            timeout=15, verify=False, headers=HEADERS
        )
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_margin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                symbol TEXT,
                margin_buy INTEGER,
                margin_sell INTEGER,
                margin_balance INTEGER,
                short_sell INTEGER,
                short_buy INTEGER,
                short_balance INTEGER,
                UNIQUE(date, symbol)
            )
        """)

        count = 0
        today = datetime.now().strftime("%Y-%m-%d")

        def to_int(v):
            return int(str(v).replace(",", "")) if v and str(v).strip() else 0

        for d in data:
            code = d.get("股票代號", "").strip()
            if not re.match(r'^\d{4}$', code):
                continue
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO tw_margin
                    (date, symbol, margin_buy, margin_sell, margin_balance,
                     short_sell, short_buy, short_balance)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    today, code,
                    to_int(d.get("融資買進")),
                    to_int(d.get("融資賣出")),
                    to_int(d.get("融資今日餘額")),
                    to_int(d.get("融券賣出")),
                    to_int(d.get("融券買進")),
                    to_int(d.get("融券今日餘額")),
                ))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"Margin trading updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_margin_trading error: {e}")
        return 0


def fetch_stock_day_avg():
    """從 TWSE OpenAPI 抓個股收盤價及月均價（STOCK_DAY_AVG_ALL）"""
    try:
        resp = requests.get(API["stock_day_avg"], timeout=30, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_stock_day_avg (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                symbol TEXT,
                name TEXT,
                closing_price REAL,
                monthly_avg_price REAL,
                UNIQUE(date, symbol)
            )
        """)

        count = 0
        for d in data:
            code = d.get("Code", "").strip()
            if not re.match(r'^\d{4,6}$', code):
                continue
            try:
                roc_date = d.get("Date", "")
                if len(roc_date) == 7:
                    year = int(roc_date[:3]) + 1911
                    date_str = f"{year}-{roc_date[3:5]}-{roc_date[5:7]}"
                else:
                    continue
                close = float(d.get("ClosingPrice", "0").replace(",", "")) if d.get("ClosingPrice") else None
                avg = float(d.get("MonthlyAveragePrice", "0").replace(",", "")) if d.get("MonthlyAveragePrice") else None
                conn.execute("""
                    INSERT OR REPLACE INTO tw_stock_day_avg (date, symbol, name, closing_price, monthly_avg_price)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, code, d.get("Name", ""), close, avg))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"Stock day avg updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_stock_day_avg error: {e}")
        return 0


def fetch_sbl():
    """從 TWSE OpenAPI 抓借券賣出可用量（TWT96U — 放空指標）"""
    try:
        resp = requests.get(API["sbl"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_sbl (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                symbol TEXT,
                available_volume INTEGER,
                market TEXT DEFAULT 'TWSE',
                UNIQUE(date, symbol, market)
            )
        """)

        count = 0
        today = datetime.now().strftime("%Y-%m-%d")

        def to_int(v):
            return int(str(v).replace(",", "")) if v and str(v).strip() else 0

        for d in data:
            # TWSE listed
            twse_code = d.get("TWSECode", "").strip()
            if re.match(r'^\d{4,6}$', twse_code):
                conn.execute("""
                    INSERT OR IGNORE INTO tw_sbl (date, symbol, available_volume, market)
                    VALUES (?, ?, ?, 'TWSE')
                """, (today, twse_code, to_int(d.get("TWSEAvailableVolume"))))
                count += 1
            # OTC listed
            gretai_code = d.get("GRETAICode", "").strip()
            if re.match(r'^\d{4,6}$', gretai_code):
                conn.execute("""
                    INSERT OR IGNORE INTO tw_sbl (date, symbol, available_volume, market)
                    VALUES (?, ?, ?, 'OTC')
                """, (today, gretai_code, to_int(d.get("GRETAIAvailableVolume"))))
                count += 1

        conn.commit()
        conn.close()
        print(f"SBL (short selling) updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_sbl error: {e}")
        return 0


def fetch_qfiis_cat():
    """從 TWSE OpenAPI 抓外資持股類股比率（MI_QFIIS_cat）"""
    try:
        resp = requests.get(API["qfiis_cat"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_qfiis_cat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                industry TEXT,
                stock_count INTEGER,
                total_shares INTEGER,
                foreign_shares INTEGER,
                percentage REAL,
                UNIQUE(date, industry)
            )
        """)

        count = 0
        today = datetime.now().strftime("%Y-%m-%d")

        def to_int(v):
            return int(str(v).replace(",", "")) if v and str(v).strip() else 0

        for d in data:
            industry = d.get("IndustryCat", "").strip()
            if not industry:
                continue
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO tw_qfiis_cat (date, industry, stock_count, total_shares, foreign_shares, percentage)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    today, industry,
                    to_int(d.get("Numbers")),
                    to_int(d.get("ShareNumber")),
                    to_int(d.get("ForeignMainlandAreaShare")),
                    float(d.get("Percentage", "0")) if d.get("Percentage") else 0,
                ))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"QFIIS category updated: {count} industries")
        return count
    except Exception as e:
        print(f"fetch_qfiis_cat error: {e}")
        return 0


def fetch_yearly_trade():
    """從 TWSE OpenAPI 抓年度成交資訊（FMNPTK_ALL — 年高低點/均價）"""
    def to_float(v):
        return float(str(v).replace(",", "")) if v and str(v).strip() else None

    try:
        resp = requests.get(API["yearly_trade"], timeout=30, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_yearly_trade (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER,
                symbol TEXT,
                name TEXT,
                trade_volume INTEGER,
                trade_value INTEGER,
                transactions INTEGER,
                highest_price REAL,
                highest_date TEXT,
                lowest_price REAL,
                lowest_date TEXT,
                avg_closing_price REAL,
                UNIQUE(year, symbol)
            )
        """)

        count = 0

        def to_int(v):
            return int(str(v).replace(",", "")) if v and str(v).strip() else 0

        for d in data:
            code = d.get("Code", "").strip()
            if not re.match(r'^\d{4,6}$', code):
                continue
            try:
                roc_year = int(d.get("Year", "0"))
                year = roc_year + 1911

                conn.execute("""
                    INSERT OR REPLACE INTO tw_yearly_trade
                    (year, symbol, name, trade_volume, trade_value, transactions,
                     highest_price, highest_date, lowest_price, lowest_date, avg_closing_price)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    year, code, d.get("Name", ""),
                    to_int(d.get("TradeVolume")),
                    to_int(d.get("TradeValue")),
                    to_int(d.get("Transaction")),
                    to_float(d.get("HighestPrice")),
                    d.get("HDate", ""),
                    to_float(d.get("LowestPrice")),
                    d.get("LDate", ""),
                    to_float(d.get("AvgClosingPrice")),
                ))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"Yearly trade info updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_yearly_trade error: {e}")
        return 0


def fetch_ex_dividend():
    """從 TWSE OpenAPI 抓除權除息預告（TWT48U_ALL）"""
    def to_float(v):
        return float(str(v).replace(",", "")) if v and str(v).strip() else 0

    try:
        resp = requests.get(API["ex_dividend"], timeout=15, verify=False, headers=HEADERS)
        data = resp.json()

        conn = get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tw_ex_dividend (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                symbol TEXT,
                name TEXT,
                ex_type TEXT,
                stock_dividend_ratio REAL,
                cash_dividend REAL,
                UNIQUE(date, symbol, ex_type)
            )
        """)

        count = 0
        for d in data:
            code = d.get("Code", "").strip()
            if not re.match(r'^\d{4,6}$', code):
                continue
            try:
                roc_date = d.get("Date", "")
                if len(roc_date) == 7:
                    year = int(roc_date[:3]) + 1911
                    date_str = f"{year}-{roc_date[3:5]}-{roc_date[5:7]}"
                else:
                    continue

                conn.execute("""
                    INSERT OR REPLACE INTO tw_ex_dividend (date, symbol, name, ex_type, stock_dividend_ratio, cash_dividend)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    date_str, code, d.get("Name", ""),
                    d.get("Exdividend", ""),
                    to_float(d.get("StockDividendRatio")),
                    to_float(d.get("CashDividend")),
                ))
                count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()
        conn.close()
        print(f"Ex-dividend schedule updated: {count} stocks")
        return count
    except Exception as e:
        print(f"fetch_ex_dividend error: {e}")
        return 0


def fetch_all():
    """一次抓所有可用資料"""
    print(f"=== TWSE Fetch All @ {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    init_tables()
    results = {}
    results["holidays"] = len(fetch_holiday_schedule())
    time.sleep(1)
    results["per"] = fetch_per()
    time.sleep(1)
    results["eps"] = fetch_quarterly_eps()
    time.sleep(1)
    results["revenue"] = fetch_monthly_revenue()
    time.sleep(1)
    results["announcements"] = fetch_major_announcements()
    time.sleep(1)
    results["margin"] = fetch_margin_trading()
    time.sleep(2)
    # Phase 2
    results["stock_day_avg"] = fetch_stock_day_avg()
    time.sleep(2)
    results["sbl"] = fetch_sbl()
    time.sleep(2)
    results["qfiis_cat"] = fetch_qfiis_cat()
    time.sleep(2)
    results["yearly_trade"] = fetch_yearly_trade()
    time.sleep(2)
    results["ex_dividend"] = fetch_ex_dividend()
    print(f"\nResults: {json.dumps(results)}")
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--check-trading-day":
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        trading = is_trading_day(date_arg)
        target = date_arg or datetime.now().strftime("%Y-%m-%d")
        print(f"{target}: {'TRADING DAY' if trading else 'NOT TRADING'}")
        sys.exit(0 if trading else 1)
    fetch_all()
