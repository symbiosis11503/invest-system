#!/usr/bin/env python3
"""投資分析聚合器 — 自動調用所有 API 生成個股分析報告

用法：
  python investment_analyst.py 2330      # 分析台積電
  python investment_analyst.py 2412 2317 # 分析多檔
"""
import json
import sqlite3
import sys
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db/trades.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def analyze_stock(symbol):
    """綜合分析一檔股票"""
    conn = get_conn()
    report = {"symbol": symbol, "timestamp": datetime.now().isoformat()}

    # 1. 基本資料
    name_row = conn.execute(
        "SELECT name_zh, exchange, category FROM symbol_names WHERE symbol=?",
        (symbol,)).fetchone()
    report["name"] = dict(name_row) if name_row else {"name_zh": symbol}

    # 2. PER/PBR/殖利率
    per_row = conn.execute(
        "SELECT per, pbr, dividend_yield, date FROM tw_per WHERE symbol=? ORDER BY date DESC LIMIT 1",
        (symbol,)).fetchone()
    report["valuation"] = dict(per_row) if per_row else {}

    # 3. EPS
    eps_rows = conn.execute(
        "SELECT year, quarter, eps, revenue, profit FROM tw_eps WHERE symbol=? ORDER BY year DESC, quarter DESC LIMIT 4",
        (symbol,)).fetchall()
    report["eps"] = [dict(r) for r in eps_rows]
    if eps_rows:
        recent_eps = [r["eps"] for r in eps_rows if r["eps"] is not None]
        report["annual_eps"] = round(sum(recent_eps), 2) if recent_eps else None

    # 4. 法人動向
    inst_rows = conn.execute(
        "SELECT date, foreign_net, trust_net, dealer_net, total_net FROM tw_institutional WHERE symbol=? ORDER BY date DESC LIMIT 20",
        (symbol,)).fetchall()
    report["institutional"] = [dict(r) for r in inst_rows[:5]]

    # 外資連買天數
    foreign_streak = 0
    foreign_total = 0
    for r in inst_rows:
        if r["foreign_net"] and r["foreign_net"] > 0:
            foreign_streak += 1
            foreign_total += r["foreign_net"]
        else:
            break
    report["foreign_buy_streak"] = {"days": foreign_streak, "total": foreign_total}

    # 5. 融資融券
    margin_row = conn.execute(
        "SELECT margin_balance, short_balance, date FROM tw_margin WHERE symbol=? ORDER BY date DESC LIMIT 1",
        (symbol,)).fetchone()
    report["margin"] = dict(margin_row) if margin_row else {}

    # 6. 月營收
    rev_rows = conn.execute(
        "SELECT date, revenue, revenue_yoy, revenue_mom FROM tw_revenue WHERE symbol=? ORDER BY date DESC LIMIT 6",
        (symbol,)).fetchall()
    report["revenue"] = [dict(r) for r in rev_rows]

    # 營收連成長
    rev_growth_streak = 0
    for r in rev_rows:
        if r["revenue_yoy"] and r["revenue_yoy"] > 0:
            rev_growth_streak += 1
        else:
            break
    report["revenue_growth_streak"] = rev_growth_streak

    # 7. 最近股價
    price_rows = conn.execute(
        "SELECT date, close, volume FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 5",
        (symbol,)).fetchall()
    report["recent_prices"] = [dict(r) for r in price_rows]

    conn.close()

    # 8. 綜合評分
    report["score"] = calculate_score(report)
    report["summary"] = generate_summary(report)

    return report


def calculate_score(report):
    """計算綜合評分 (1-10)"""
    score = 5.0  # 基準

    # PER 評分
    per = report.get("valuation", {}).get("per")
    if per:
        per = float(per)
        if per < 10:
            score += 1.5  # 便宜
        elif per < 15:
            score += 0.5
        elif per > 30:
            score -= 1.0  # 貴

    # 殖利率評分
    dy = report.get("valuation", {}).get("dividend_yield")
    if dy:
        dy = float(dy)
        if dy > 5:
            score += 1.0
        elif dy > 3:
            score += 0.5

    # 外資連買
    streak = report.get("foreign_buy_streak", {}).get("days", 0)
    if streak >= 10:
        score += 1.5
    elif streak >= 5:
        score += 1.0
    elif streak >= 3:
        score += 0.5

    # 營收成長
    growth = report.get("revenue_growth_streak", 0)
    if growth >= 6:
        score += 1.0
    elif growth >= 3:
        score += 0.5

    # EPS
    annual_eps = report.get("annual_eps")
    if annual_eps and annual_eps > 10:
        score += 0.5
    elif annual_eps and annual_eps < 0:
        score -= 1.0

    return round(min(max(score, 1), 10), 1)


def generate_summary(report):
    """生成文字摘要"""
    name = report.get("name", {}).get("name_zh", report["symbol"])
    score = report.get("score", 5)
    per = report.get("valuation", {}).get("per", "--")
    dy = report.get("valuation", {}).get("dividend_yield", "--")
    eps = report.get("annual_eps", "--")
    streak = report.get("foreign_buy_streak", {}).get("days", 0)
    growth = report.get("revenue_growth_streak", 0)

    sentiment = "看多" if score >= 7 else "看空" if score <= 3 else "中性"

    lines = [
        f"【{name} ({report['symbol']})】評分: {score}/10 ({sentiment})",
        f"PER: {per} | 殖利率: {dy}% | 年化EPS: {eps}",
    ]
    if streak > 0:
        lines.append(f"外資連買 {streak} 天")
    if growth > 0:
        lines.append(f"營收連成長 {growth} 月")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python investment_analyst.py <symbol> [symbol2] ...")
        return

    symbols = sys.argv[1:]
    for sym in symbols:
        report = analyze_stock(sym)
        print(report["summary"])
        print()
        # Also save JSON
        out_path = os.path.join(os.path.dirname(__file__), "logs", f"analysis_{sym}.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    main()
