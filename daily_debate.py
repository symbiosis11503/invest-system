#!/usr/bin/env python3
"""每日辯論報告 — 自動對異動股做多角色辯論分析

每日執行：
1. 找出當日法人大量買超/賣超前 5 檔
2. 對每檔做看多/看空/仲裁辯論
3. 推播結果到 TG + 存檔

用法：
  python daily_debate.py              # 分析法人異動 top 5
  python daily_debate.py 2330 2412    # 指定股票
  python daily_debate.py --tg         # 結果推送 TG
"""
import json
import os
import sys
import sqlite3
import requests
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from investment_debate import run_debate, format_debate_report

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db/trades.db")


def get_top_movers(limit=5):
    """找出最近法人大幅買賣超的股票"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 找最近交易日有法人大量異動的股票
    rows = conn.execute("""
        SELECT i.symbol, n.name_zh,
               i.foreign_net, i.trust_net, i.dealer_net, i.total_net,
               i.date
        FROM tw_institutional i
        LEFT JOIN symbol_names n ON n.symbol = i.symbol
        WHERE i.date = (SELECT MAX(date) FROM tw_institutional)
        AND ABS(i.total_net) > 500
        ORDER BY ABS(i.total_net) DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def send_to_tg(text, chat_id=None):
    """推播到 TG"""
    bot_token = os.environ.get('TG_BOT_TOKEN', '8585052129:AAGqJyRNJGxL7bUPr1VuRGtbB2eSFIBCcEM')
    chat_id = chat_id or os.environ.get('TG_CHAT_ID', '6927318445')
    try:
        # TG 訊息長度限制 4096，超過就分段
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=10,
            )
    except Exception as e:
        print(f"TG 推播失敗: {e}")


def main():
    args = sys.argv[1:]
    push_tg = "--tg" in args
    args = [a for a in args if a != "--tg"]

    # 決定分析哪些股票
    if args:
        symbols = args
        print(f"指定分析: {', '.join(symbols)}")
    else:
        movers = get_top_movers(5)
        if not movers:
            print("沒有找到法人異動資料")
            return
        symbols = [m["symbol"] for m in movers]
        print(f"法人異動 Top {len(symbols)}: {', '.join(symbols)}")
        for m in movers:
            name = m.get('name_zh', m['symbol'])
            print(f"  {name}({m['symbol']}): 法人合計 {m['total_net']:+,}")

    # 逐檔辯論
    results = []
    for sym in symbols:
        print(f"\n{'='*40}")
        print(f"辯論分析 {sym}...")
        try:
            result = run_debate(sym)
            results.append(result)
            report = format_debate_report(result)
            print(report)

            if push_tg:
                name = result.get("name", sym)
                tg_text = f"📊 *{name} ({sym}) 辯論報告*\n\n"
                tg_text += f"🐂 看多：\n{result['debate']['bull']['response'][:500]}\n\n"
                tg_text += f"🐻 看空：\n{result['debate']['bear']['response'][:500]}\n\n"
                tg_text += f"⚖️ 仲裁：\n{result['debate']['arbiter']['response'][:500]}\n\n"
                tg_text += f"系統評分: {result['data'].get('score', 'N/A')}/10"
                send_to_tg(tg_text)
        except Exception as e:
            print(f"  分析失敗: {e}")

    # 存檔
    if results:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"daily_debate_{date.today().isoformat()}.json")
        with open(out_path, "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n報告已存: {out_path}")


if __name__ == "__main__":
    main()
