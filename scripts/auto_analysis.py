#!/usr/bin/env python3
"""自動分析 — 每日法人異動 Top 10 股票分析

產出結構化報告，可用於 TG 推播或 Threads 發文。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investment_analyst import analyze_stock, get_conn
from datetime import datetime
import json


def get_top_movers(limit=10):
    """取得法人買賣超最大的股票"""
    conn = get_conn()
    latest_date = conn.execute("SELECT MAX(date) FROM tw_institutional").fetchone()[0]
    if not latest_date:
        return []

    rows = conn.execute("""
        SELECT i.symbol, i.total_net, COALESCE(n.name_zh, i.symbol) as name_zh
        FROM tw_institutional i
        LEFT JOIN symbol_names n ON n.symbol = i.symbol
        WHERE i.date = ?
        ORDER BY ABS(i.total_net) DESC LIMIT ?
    """, (latest_date, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def run_daily_analysis():
    """對 Top 10 異動股做分析"""
    movers = get_top_movers(10)
    if not movers:
        print("無籌碼資料")
        return

    print(f"=== 每日投資分析 {datetime.now().strftime('%Y-%m-%d')} ===\n")

    reports = []
    for m in movers:
        report = analyze_stock(m["symbol"])
        reports.append(report)
        print(report["summary"])
        net = m["total_net"]
        direction = "買超" if net > 0 else "賣超"
        print(f"法人{direction}: {abs(net):,} 張")
        print()

    # 找最值得關注的（score 最高且外資買超）
    best = sorted(
        [r for r in reports if r.get("foreign_buy_streak", {}).get("days", 0) > 0],
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    if best:
        top = best[0]
        print(f"\n🔥 今日最值得關注: {top['name'].get('name_zh', '')} ({top['symbol']})")
        print(f"   評分 {top['score']}/10 | 外資連買 {top['foreign_buy_streak']['days']} 天")

    # 保存報告
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "logs", f"daily_analysis_{datetime.now().strftime('%Y%m%d')}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "movers": movers, "reports": reports},
                  f, ensure_ascii=False, indent=2, default=str)
    print(f"\n報告已保存: {out_path}")


if __name__ == "__main__":
    run_daily_analysis()
