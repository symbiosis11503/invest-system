"""財經日曆模組 — 抓取全球重要經濟數據發布時程

資料來源優先順序：
1. Jin10 (金十數據) — 中文，免費公開 API
2. Investing.com 經濟日曆 — 備用抓取
"""
import sqlite3
import json
import os
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")

logger = logging.getLogger(__name__)

# ── 國家代碼對照表 ──────────────────────────────────────
COUNTRY_MAP_JIN10 = {
    "美国": "US", "中国": "CN", "台湾": "TW", "日本": "JP",
    "欧元区": "EU", "德国": "EU", "法国": "EU", "意大利": "EU",
    "英国": "GB", "加拿大": "CA", "澳大利亚": "AU", "新西兰": "NZ",
    "瑞士": "CH", "韩国": "KR", "印度": "IN", "巴西": "BR",
    "俄罗斯": "RU", "南非": "ZA", "墨西哥": "MX", "土耳其": "TR",
    "香港": "HK", "新加坡": "SG",
}

COUNTRY_NAME_ZH = {
    "US": "美國", "CN": "中國", "TW": "台灣", "JP": "日本",
    "EU": "歐元區", "GB": "英國", "CA": "加拿大", "AU": "澳洲",
    "NZ": "紐西蘭", "CH": "瑞士", "KR": "韓國", "IN": "印度",
    "BR": "巴西", "RU": "俄羅斯", "ZA": "南非", "MX": "墨西哥",
    "TR": "土耳其", "HK": "香港", "SG": "新加坡",
}

COUNTRY_FLAG = {
    "US": "🇺🇸", "CN": "🇨🇳", "TW": "🇹🇼", "JP": "🇯🇵",
    "EU": "🇪🇺", "GB": "🇬🇧", "CA": "🇨🇦", "AU": "🇦🇺",
    "NZ": "🇳🇿", "CH": "🇨🇭", "KR": "🇰🇷", "IN": "🇮🇳",
    "BR": "🇧🇷", "RU": "🇷🇺", "ZA": "🇿🇦", "MX": "🇲🇽",
    "TR": "🇹🇷", "HK": "🇭🇰", "SG": "🇸🇬",
}

# ── 重要性對照 ──────────────────────────────────────────
def star_to_importance(star):
    """Jin10 star 1-5 → high/medium/low"""
    try:
        s = int(star)
    except (TypeError, ValueError):
        return "low"
    if s >= 4:
        return "high"
    elif s >= 2:
        return "medium"
    return "low"


# ── DB ──────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_calendar_table():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS economic_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            event_time TEXT,
            country TEXT,
            country_name TEXT,
            event_name TEXT NOT NULL,
            importance TEXT DEFAULT 'low',
            previous TEXT,
            forecast TEXT,
            actual TEXT,
            unit TEXT,
            source TEXT DEFAULT 'jin10',
            raw_id TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(event_date, event_time, event_name, country)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ec_date ON economic_calendar(event_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ec_importance ON economic_calendar(importance)
    """)
    conn.commit()
    conn.close()


# ── Jin10 資料來源 ──────────────────────────────────────

JIN10_CALENDAR_URL = "https://cdn.jin10.com/data/ec/domestic/{date}.json"
JIN10_CALENDAR_URL2 = "https://rili.jin10.com/datas/{ymd_path}/economics.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://rili.jin10.com/",
    "Origin": "https://rili.jin10.com",
}


def fetch_jin10_calendar(target_date: str) -> list:
    """從 Jin10 抓取指定日期的財經日曆

    Args:
        target_date: YYYY-MM-DD 格式

    Returns:
        list of event dicts
    """
    events = []
    dt = datetime.strptime(target_date, "%Y-%m-%d")

    # 嘗試多個 URL 格式
    urls = [
        JIN10_CALENDAR_URL.format(date=target_date),
        JIN10_CALENDAR_URL2.format(ymd_path=f"{dt.year}/{dt.strftime('%m%d')}"),
    ]

    data = None
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    logger.info(f"Jin10 成功: {url}, {len(data)} 筆")
                    break
        except Exception as e:
            logger.debug(f"Jin10 URL 失敗 {url}: {e}")
            continue

    if not data:
        return events

    for item in data:
        if isinstance(item, dict):
            country_cn = item.get("country", "") or ""
            country_code = COUNTRY_MAP_JIN10.get(country_cn, "")
            country_name = COUNTRY_NAME_ZH.get(country_code, country_cn)

            event_time = item.get("time_show", "") or item.get("pub_time", "") or ""
            event_name = item.get("title", "") or item.get("name", "") or ""
            star = item.get("star", 0) or item.get("importance", 0)

            if not event_name:
                continue

            events.append({
                "event_date": target_date,
                "event_time": event_time,
                "country": country_code,
                "country_name": country_name,
                "event_name": event_name,
                "importance": star_to_importance(star),
                "previous": str(item.get("previous", "") or item.get("former", "") or ""),
                "forecast": str(item.get("consensus", "") or item.get("forecast", "") or ""),
                "actual": str(item.get("actual", "") or ""),
                "unit": str(item.get("unit", "") or ""),
                "source": "jin10",
                "raw_id": str(item.get("id", "") or ""),
            })

    return events


# ── Investing.com 備用 ──────────────────────────────────

INVESTING_CALENDAR_URL = "https://www.investing.com/economic-calendar/"

def fetch_investing_calendar(date_from: str, date_to: Optional[str] = None) -> list:
    """從 Investing.com 抓取財經日曆（支援日期範圍）

    API 總是回傳整週數據，所以一次抓取日期範圍更高效。
    從 HTML 的 date header rows 解析每個事件的真實日期。
    """
    if date_to is None:
        date_to = date_from

    events = []

    investing_country_map = {
        "United States": "US", "China": "CN", "Taiwan": "TW",
        "Japan": "JP", "Euro Zone": "EU", "Germany": "EU",
        "United Kingdom": "GB", "Canada": "CA", "Australia": "AU",
        "South Korea": "KR", "Switzerland": "CH", "India": "IN",
        "France": "EU", "Italy": "EU", "Spain": "EU",
        "New Zealand": "NZ", "Brazil": "BR", "Mexico": "MX",
        "Turkey": "TR", "Russia": "RU", "South Africa": "ZA",
        "Hong Kong": "HK", "Singapore": "SG",
    }

    # Month name → number mapping for Investing.com date headers
    month_map = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": INVESTING_CALENDAR_URL,
        }

        resp = requests.get(
            "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData",
            params={
                "dateFrom": date_from,
                "dateTo": date_to,
                "timeZone": 88,  # UTC+8
                "timeFilter": "timeRemain",
                "currentTab": "custom",
                "limit_from": 0,
            },
            headers=headers,
            timeout=15,
        )

        if resp.status_code != 200:
            logger.warning(f"Investing.com HTTP {resp.status_code}")
            return events

        result = resp.json()
        html = result.get("data", "")
        if not html:
            return events

        soup = BeautifulSoup(html, "html.parser")

        # Parse date from theDay header rows and track current date
        current_date = date_from  # fallback
        import re

        for row in soup.find_all("tr"):
            # Check if this is a date header row
            day_cell = row.find("td", class_="theDay")
            if day_cell:
                date_text = day_cell.get_text(strip=True)
                # Parse "Tuesday, March 25, 2026" format
                match = re.search(r"(\w+)\s+(\d+),?\s*(\d{4})", date_text)
                if match:
                    month_name, day, year = match.groups()
                    month_num = month_map.get(month_name, "01")
                    current_date = f"{year}-{month_num}-{day.zfill(2)}"
                continue

            # Check if this is an event row
            if "js-event-item" not in (row.get("class") or []):
                continue

            time_cell = row.find("td", class_="time")
            event_time = time_cell.get_text(strip=True) if time_cell else ""

            flag_span = row.find("span", class_="ceFlags")
            country_text = flag_span.get("title", "") if flag_span else ""
            country_code = investing_country_map.get(country_text, "")

            event_cell = row.find("td", class_="event")
            if event_cell:
                event_a = event_cell.find("a")
                event_name = event_a.get_text(strip=True) if event_a else event_cell.get_text(strip=True)
            else:
                event_name = ""

            sentiment_td = row.find("td", class_="sentiment")
            if sentiment_td:
                bull_icons = sentiment_td.find_all("i", class_="grayFullBullishIcon")
                star_count = len(bull_icons)
            else:
                star_count = 0

            prev_cell = row.find("td", {"id": lambda x: x and "prev" in str(x).lower()})
            fore_cell = row.find("td", {"id": lambda x: x and "fore" in str(x).lower()})
            act_cell = row.find("td", {"id": lambda x: x and "act" in str(x).lower()})

            if not event_name:
                continue

            if star_count >= 3:
                imp = "high"
            elif star_count >= 2:
                imp = "medium"
            else:
                imp = "low"

            events.append({
                "event_date": current_date,
                "event_time": event_time,
                "country": country_code,
                "country_name": COUNTRY_NAME_ZH.get(country_code, country_text),
                "event_name": event_name,
                "importance": imp,
                "previous": prev_cell.get_text(strip=True) if prev_cell else "",
                "forecast": fore_cell.get_text(strip=True) if fore_cell else "",
                "actual": act_cell.get_text(strip=True) if act_cell else "",
                "unit": "",
                "source": "investing",
                "raw_id": row.get("event_attr_id", ""),
            })

    except Exception as e:
        logger.warning(f"Investing.com 抓取失敗: {e}")

    return events


# ── 靜態備用資料（重要經濟事件週期表）────────────────────

RECURRING_EVENTS = [
    # 每月第一個週五
    {"event_name": "美國非農就業人數", "country": "US", "importance": "high",
     "description": "每月第一個週五公布，影響美元、股市、債券"},
    {"event_name": "美國 CPI 消費者物價指數", "country": "US", "importance": "high",
     "description": "每月中旬公布，通膨關鍵指標"},
    {"event_name": "美國 FOMC 利率決議", "country": "US", "importance": "high",
     "description": "每年 8 次，約每 6 週一次"},
    {"event_name": "美國 PPI 生產者物價指數", "country": "US", "importance": "medium",
     "description": "每月中旬公布"},
    {"event_name": "中國 GDP 季度報", "country": "CN", "importance": "high",
     "description": "每季公布"},
    {"event_name": "日本央行利率決議", "country": "JP", "importance": "high",
     "description": "每年 8 次"},
    {"event_name": "歐洲央行利率決議", "country": "EU", "importance": "high",
     "description": "每 6 週一次"},
    {"event_name": "台灣 GDP", "country": "TW", "importance": "high",
     "description": "每季公布"},
    {"event_name": "台灣央行利率決議", "country": "TW", "importance": "high",
     "description": "每季公布"},
]


# ── 主流程 ──────────────────────────────────────────────

def _store_events(conn, events: list) -> tuple:
    """Store events to DB, returns (stored_count, errors)"""
    stored = 0
    errors = []
    for ev in events:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO economic_calendar
                (event_date, event_time, country, country_name, event_name,
                 importance, previous, forecast, actual, unit, source, raw_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """, (
                ev["event_date"], ev["event_time"], ev["country"],
                ev["country_name"], ev["event_name"], ev["importance"],
                ev["previous"], ev["forecast"], ev["actual"],
                ev["unit"], ev["source"], ev["raw_id"],
            ))
            stored += 1
        except Exception as e:
            errors.append(str(e))
    return stored, errors


def fetch_and_store(days: int = 7) -> dict:
    """抓取未來 N 天的財經日曆並存入 DB

    策略：
    1. 先嘗試 Jin10 逐日抓取
    2. 若 Jin10 無資料，用 Investing.com 一次抓取整個日期範圍（避免重複）

    Returns:
        dict with stats
    """
    init_calendar_table()
    conn = get_conn()

    total_fetched = 0
    total_stored = 0
    errors = []
    sources_used = set()

    today = datetime.now()
    date_from = today.strftime("%Y-%m-%d")
    date_to = (today + timedelta(days=days - 1)).strftime("%Y-%m-%d")

    # Phase 1: 嘗試 Jin10 逐日
    jin10_dates_covered = set()
    for i in range(days):
        target_date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        events = fetch_jin10_calendar(target_date)
        if events:
            sources_used.add("jin10")
            jin10_dates_covered.add(target_date)
            total_fetched += len(events)
            stored, errs = _store_events(conn, events)
            total_stored += stored
            errors.extend(errs)

    # Phase 2: Investing.com 補齊（一次查詢整個範圍，避免重複）
    if len(jin10_dates_covered) < days:
        events = fetch_investing_calendar(date_from, date_to)
        if events:
            sources_used.add("investing")
            # 只存 Jin10 未覆蓋的日期
            filtered = [e for e in events if e["event_date"] not in jin10_dates_covered]
            total_fetched += len(filtered)
            stored, errs = _store_events(conn, filtered)
            total_stored += stored
            errors.extend(errs)

    conn.commit()
    conn.close()

    return {
        "fetched": total_fetched,
        "stored": total_stored,
        "days": days,
        "sources": list(sources_used),
        "errors": errors[:5],
    }


def get_events(date_from: Optional[str] = None, date_to: Optional[str] = None,
               country: Optional[str] = None, importance: Optional[str] = None,
               limit: int = 200) -> list:
    """查詢財經日曆事件"""
    init_calendar_table()
    conn = get_conn()

    conditions = []
    params = []

    if date_from:
        conditions.append("event_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("event_date <= ?")
        params.append(date_to)
    if country:
        countries = [c.strip().upper() for c in country.split(",")]
        placeholders = ",".join("?" * len(countries))
        conditions.append(f"country IN ({placeholders})")
        params.extend(countries)
    if importance:
        conditions.append("importance = ?")
        params.append(importance)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    rows = conn.execute(f"""
        SELECT * FROM economic_calendar
        {where}
        ORDER BY event_date ASC,
                 CASE importance WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                 event_time ASC
        LIMIT ?
    """, params + [limit]).fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        d["country_flag"] = COUNTRY_FLAG.get(d.get("country", ""), "")
        results.append(d)

    return results


def get_today_events() -> list:
    """取得今天的事件"""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_events(date_from=today, date_to=today)


def get_upcoming_events(days: int = 7) -> list:
    """取得未來 N 天事件"""
    today = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    return get_events(date_from=today, date_to=end)


# ── CLI 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("正在抓取財經日曆...")
    result = fetch_and_store(days=7)
    print(f"完成: 抓取 {result['fetched']} 筆, 儲存 {result['stored']} 筆")
    print(f"來源: {', '.join(result['sources']) or '無'}")
    if result['errors']:
        print(f"錯誤: {result['errors']}")

    print("\n=== 今日事件 ===")
    for ev in get_today_events():
        flag = COUNTRY_FLAG.get(ev['country'], '')
        imp = {"high": "★★★", "medium": "★★", "low": "★"}.get(ev['importance'], "")
        print(f"  {ev['event_time'] or '--:--'} {flag} {ev['event_name']} {imp}")

    print("\n=== 未來 7 天高重要性事件 ===")
    for ev in get_upcoming_events(7):
        if ev['importance'] == 'high':
            flag = COUNTRY_FLAG.get(ev['country'], '')
            print(f"  {ev['event_date']} {ev['event_time'] or '--:--'} {flag} {ev['event_name']}")
