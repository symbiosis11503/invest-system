#!/usr/bin/env python3
"""
更生人策略回測 v5 — 60 分線 + 加減碼（最大 3 口）+ 回撤控制
不做絕對值優化，用邏輯性的加減碼規則降低回撤
"""

import yfinance as yf
import pandas as pd
import numpy as np


def fetch_60m():
    data = yf.download("^TWII", period="max", interval="60m", progress=False)
    df = pd.DataFrame()
    df["open"] = data[("Open", "^TWII")]
    df["high"] = data[("High", "^TWII")]
    df["low"] = data[("Low", "^TWII")]
    df["close"] = data[("Close", "^TWII")]
    df["volume"] = data[("Volume", "^TWII")]
    df.index = data.index.get_level_values(0)
    df.dropna(inplace=True)
    return df


def calc_indicators(df):
    VWAP_PERIOD = 440
    SMA_PERIOD = 85

    df["vwap"] = df["close"].rolling(VWAP_PERIOD).mean()
    df["sma"] = df["close"].rolling(SMA_PERIOD).mean()
    df["holding_line"] = df["sma"].rolling(2).max()
    df["reflect_line"] = 2 * df["sma"] - df["holding_line"]
    df["holding_bull"] = df["reflect_line"] >= df["vwap"]

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["osc"] = df["dif"] - df["dea"]
    df["ema17"] = df["close"].ewm(span=17, adjust=False).mean()

    ema17_up = df["ema17"] > df["ema17"].shift(1)
    osc_up = df["osc"] > df["osc"].shift(1)
    ema17_down = df["ema17"] < df["ema17"].shift(1)
    osc_down = df["osc"] < df["osc"].shift(1)

    df["macd_str"] = 0
    df.loc[ema17_up & osc_up, "macd_str"] = 1
    df.loc[ema17_down & osc_down, "macd_str"] = -1

    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - sma_tp) / (0.015 * mad)

    # streaks
    df["weak_streak"] = 0
    df["strong_streak"] = 0
    ws = ss = 0
    for i in range(len(df)):
        ws = ws + 1 if df.iloc[i]["macd_str"] == -1 else 0
        ss = ss + 1 if df.iloc[i]["macd_str"] == 1 else 0
        df.iloc[i, df.columns.get_loc("weak_streak")] = ws
        df.iloc[i, df.columns.get_loc("strong_streak")] = ss

    # OSC 趨勢強度（連續 N bars 同向）
    df["osc_rising"] = (df["osc"] > df["osc"].shift(1)).rolling(3).sum() == 3
    df["osc_falling"] = (df["osc"] < df["osc"].shift(1)).rolling(3).sum() == 3

    df.dropna(inplace=True)
    return df


FEE = 2
SLIP = 1
COST_PER_LOT = (FEE + SLIP) * 2  # 來回 6 點/口
POINT_VALUE = 200
MAX_LOTS = 3


def backtest_v5(df, mode="both"):
    """
    簡化加減碼策略 v5b：
    - 進場 1 口
    - 獲利站穩（>0.5% + 持股線方向不變）→ 加到 2 口
    - 大趨勢確認（>1.5% + MACD強勢）→ 加到 3 口
    - 不做中途減碼，出場時一次全平（省成本）
    - 口數越多停損越緊（1口2%/2口1.5%/3口1.2%）
    - 連虧 3 筆後降回 1 口不加碼
    """
    lots = 0
    direction = 0
    avg_price = 0
    max_price = 0
    min_price = 999999
    open_entries = []

    cum_pnl = 0
    peak_pnl = 0
    consecutive_losses = 0
    restrict_mode = False

    events = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # === 無持倉 ===
        if lots == 0:
            entered = False
            new_dir = 0

            if mode in ("both", "long"):
                if (row["holding_bull"] and
                    row["macd_str"] == 1 and prev["macd_str"] != 1):
                    entered = True
                    new_dir = 1

            if not entered and mode in ("both", "short"):
                if (not row["holding_bull"] and
                    row["macd_str"] == -1 and prev["macd_str"] != -1):
                    entered = True
                    new_dir = -1

            if entered:
                direction = new_dir
                lots = 1
                price = row["close"] + (SLIP + FEE) * direction
                avg_price = price
                max_price = row["close"]
                min_price = row["close"]
                open_entries = [{"date": row.name, "price": price, "lots": 1}]
                events.append({
                    "type": "ENTRY", "date": row.name, "direction": direction,
                    "lots": 1, "price": price,
                    "signal": f"{'多' if new_dir == 1 else '空'}:1口",
                })

        # === 有持倉 ===
        elif lots > 0:
            max_price = max(max_price, row["close"])
            min_price = min(min_price, row["close"])

            if direction == 1:
                unrealized_pct = (row["close"] - avg_price) / avg_price * 100
                dd_from_peak = (row["close"] - max_price) / max_price * 100
            else:
                unrealized_pct = (avg_price - row["close"]) / avg_price * 100
                dd_from_peak = (min_price - row["close"]) / min_price * 100

            # === 加碼（不在限制模式下）===
            if not restrict_mode and lots < MAX_LOTS:

                # 加到 2 口：獲利 > 0.5% + 持股線方向不變
                if lots == 1 and unrealized_pct > 0.5:
                    trend_ok = (direction == 1 and row["holding_bull"]) or \
                               (direction == -1 and not row["holding_bull"])
                    if trend_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 1 + add_price * 1) / 2
                        lots = 2
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 2,
                                       "price": add_price, "signal": "加碼到2口(獲利+趨勢穩)"})

                # 加到 3 口：獲利 > 1.5% + MACD 強勢
                if lots == 2 and unrealized_pct > 1.5:
                    macd_ok = (direction == 1 and row["macd_str"] == 1) or \
                              (direction == -1 and row["macd_str"] == -1)
                    if macd_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 2 + add_price * 1) / 3
                        lots = 3
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 3,
                                       "price": add_price, "signal": "加碼到3口(MACD強勢)"})

            # === 出場（一次全平，不做中途減碼）===
            exit_sig = None

            # 持股線反轉
            if direction == 1 and not row["holding_bull"] and prev["holding_bull"]:
                exit_sig = "持股線翻空"
            elif direction == -1 and row["holding_bull"] and not prev["holding_bull"]:
                exit_sig = "持股線翻多"

            # 連續弱勢/強勢
            if not exit_sig:
                if direction == 1 and row["weak_streak"] >= 3:
                    exit_sig = "連續弱勢3bar"
                elif direction == -1 and row["strong_streak"] >= 3:
                    exit_sig = "連續強勢3bar"

            # 移動停損（口數越多越緊）
            if not exit_sig:
                stop_pct = {1: -2.0, 2: -1.5, 3: -1.2}[lots]
                if dd_from_peak <= stop_pct:
                    exit_sig = f"移動停損({dd_from_peak:.1f}%/{lots}口)"

            if exit_sig:
                exit_price = row["close"] - (SLIP + FEE) * direction
                pnl = (exit_price - avg_price) * direction * lots
                pnl_pct = (exit_price - avg_price) / avg_price * direction * 100

                cum_pnl += pnl
                if cum_pnl > peak_pnl:
                    peak_pnl = cum_pnl

                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                restrict_mode = consecutive_losses >= 3

                events.append({
                    "type": "EXIT", "date": row.name, "direction": direction,
                    "lots": lots, "price": exit_price, "signal": exit_sig,
                    "pnl": pnl, "pnl_pct": pnl_pct, "avg_price": avg_price,
                    "entry_date": open_entries[0]["date"],
                    "max_lots": lots, "cum_pnl": cum_pnl,
                })
                lots = 0
                direction = 0

    # 回測結束平倉
    if lots > 0:
        last = df.iloc[-1]["close"]
        exit_price = last - (SLIP + FEE) * direction
        pnl = (exit_price - avg_price) * direction * lots
        cum_pnl += pnl
        events.append({
            "type": "EXIT", "date": df.index[-1], "direction": direction,
            "lots": lots, "price": exit_price, "signal": "回測結束",
            "pnl": pnl, "pnl_pct": (exit_price - avg_price) / avg_price * direction * 100,
            "avg_price": avg_price, "entry_date": open_entries[0]["date"],
            "max_lots": lots, "cum_pnl": cum_pnl,
        })

    return events


def backtest_v5c(df, mode="both", max_loss_per_lot=200):
    """
    v5c: 加減碼 + 固定點數停損
    - 單筆虧損達 max_loss_per_lot * 口數 → 立刻全平
    - 其餘邏輯同 v5b
    """
    lots = 0
    direction = 0
    avg_price = 0
    max_price = 0
    min_price = 999999
    open_entries = []

    cum_pnl = 0
    peak_pnl = 0
    consecutive_losses = 0
    restrict_mode = False

    events = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if lots == 0:
            entered = False
            new_dir = 0

            if mode in ("both", "long"):
                if (row["holding_bull"] and
                    row["macd_str"] == 1 and prev["macd_str"] != 1):
                    entered = True
                    new_dir = 1

            if not entered and mode in ("both", "short"):
                if (not row["holding_bull"] and
                    row["macd_str"] == -1 and prev["macd_str"] != -1):
                    entered = True
                    new_dir = -1

            if entered:
                direction = new_dir
                lots = 1
                price = row["close"] + (SLIP + FEE) * direction
                avg_price = price
                max_price = row["close"]
                min_price = row["close"]
                open_entries = [{"date": row.name, "price": price, "lots": 1}]
                events.append({
                    "type": "ENTRY", "date": row.name, "direction": direction,
                    "lots": 1, "price": price,
                    "signal": f"{'多' if new_dir == 1 else '空'}:1口",
                })

        elif lots > 0:
            max_price = max(max_price, row["close"])
            min_price = min(min_price, row["close"])

            if direction == 1:
                unrealized_pct = (row["close"] - avg_price) / avg_price * 100
                unrealized_pts = row["close"] - avg_price
                dd_from_peak = (row["close"] - max_price) / max_price * 100
            else:
                unrealized_pct = (avg_price - row["close"]) / avg_price * 100
                unrealized_pts = avg_price - row["close"]
                dd_from_peak = (min_price - row["close"]) / min_price * 100

            # 加碼（同 v5b）
            if not restrict_mode and lots < MAX_LOTS:
                if lots == 1 and unrealized_pct > 0.5:
                    trend_ok = (direction == 1 and row["holding_bull"]) or \
                               (direction == -1 and not row["holding_bull"])
                    if trend_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 1 + add_price * 1) / 2
                        lots = 2
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 2,
                                       "price": add_price, "signal": "加碼到2口"})

                if lots == 2 and unrealized_pct > 1.5:
                    macd_ok = (direction == 1 and row["macd_str"] == 1) or \
                              (direction == -1 and row["macd_str"] == -1)
                    if macd_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 2 + add_price * 1) / 3
                        lots = 3
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 3,
                                       "price": add_price, "signal": "加碼到3口"})

            # 出場判斷
            exit_sig = None

            # ★ 固定點數停損：虧損達 max_loss_per_lot 點/口
            if unrealized_pts <= -max_loss_per_lot:
                exit_sig = f"固定停損({unrealized_pts:.0f}點/{lots}口)"

            # 持股線反轉
            if not exit_sig:
                if direction == 1 and not row["holding_bull"] and prev["holding_bull"]:
                    exit_sig = "持股線翻空"
                elif direction == -1 and row["holding_bull"] and not prev["holding_bull"]:
                    exit_sig = "持股線翻多"

            # 連續弱勢/強勢
            if not exit_sig:
                if direction == 1 and row["weak_streak"] >= 3:
                    exit_sig = "連續弱勢3bar"
                elif direction == -1 and row["strong_streak"] >= 3:
                    exit_sig = "連續強勢3bar"

            # 移動停損（口數越多越緊）
            if not exit_sig:
                stop_pct = {1: -2.0, 2: -1.5, 3: -1.2}[lots]
                if dd_from_peak <= stop_pct:
                    exit_sig = f"移動停損({dd_from_peak:.1f}%/{lots}口)"

            if exit_sig:
                exit_price = row["close"] - (SLIP + FEE) * direction
                pnl = (exit_price - avg_price) * direction * lots
                pnl_pct = (exit_price - avg_price) / avg_price * direction * 100

                cum_pnl += pnl
                if cum_pnl > peak_pnl:
                    peak_pnl = cum_pnl

                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                restrict_mode = consecutive_losses >= 3

                events.append({
                    "type": "EXIT", "date": row.name, "direction": direction,
                    "lots": lots, "price": exit_price, "signal": exit_sig,
                    "pnl": pnl, "pnl_pct": pnl_pct, "avg_price": avg_price,
                    "entry_date": open_entries[0]["date"],
                    "max_lots": lots, "cum_pnl": cum_pnl,
                })
                lots = 0
                direction = 0

    if lots > 0:
        last = df.iloc[-1]["close"]
        exit_price = last - (SLIP + FEE) * direction
        pnl = (exit_price - avg_price) * direction * lots
        cum_pnl += pnl
        events.append({
            "type": "EXIT", "date": df.index[-1], "direction": direction,
            "lots": lots, "price": exit_price, "signal": "回測結束",
            "pnl": pnl, "pnl_pct": (exit_price - avg_price) / avg_price * direction * 100,
            "avg_price": avg_price, "entry_date": open_entries[0]["date"],
            "max_lots": lots, "cum_pnl": cum_pnl,
        })

    return events


def print_report(events, name):
    exits = [e for e in events if e["type"] == "EXIT"]
    adds = [e for e in events if e["type"] == "ADD"]
    reduces = [e for e in events if e["type"] == "REDUCE"]

    if not exits:
        print(f"\n{'='*60}\n策略: {name}\n無交易")
        return

    wins = [e for e in exits if e["pnl"] > 0]
    losses = [e for e in exits if e["pnl"] <= 0]
    total_pnl = sum(e["pnl"] for e in exits) + sum(e.get("pnl", 0) for e in reduces)
    longs = [e for e in exits if e["direction"] == 1]
    shorts = [e for e in exits if e["direction"] == -1]

    # 回撤計算
    cum = []
    running = 0
    for e in events:
        if "pnl" in e:
            running += e["pnl"]
        cum.append(running)
    cum = np.array(cum)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    max_dd = dd.min()
    max_dd_idx = np.argmin(dd)

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"期間: {exits[0]['entry_date'].strftime('%Y-%m-%d')} ~ {exits[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"完整交易: {len(exits)}筆 (多{len(longs)}/空{len(shorts)})")
    print(f"加碼次數: {len(adds)} | 減碼次數: {len(reduces)}")
    print(f"勝率: {len(wins)/len(exits)*100:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"")
    print(f"總損益: {total_pnl:+,.0f}點 ({total_pnl*POINT_VALUE:+,.0f}元)")
    if exits:
        avg_pnl = np.mean([e["pnl"] for e in exits])
        print(f"平均每筆: {avg_pnl:+,.0f}點")
        print(f"最大獲利: {max(e['pnl'] for e in exits):+,.0f}點 ({max(e['pnl_pct'] for e in exits):+.2f}%)")
        print(f"最大虧損: {min(e['pnl'] for e in exits):+,.0f}點 ({min(e['pnl_pct'] for e in exits):+.2f}%)")

    print(f"")
    print(f"最大回撤: {max_dd:,.0f}點 ({max_dd*POINT_VALUE:,.0f}元)")
    if total_pnl > 0 and max_dd != 0:
        print(f"Recovery Factor: {total_pnl/abs(max_dd):.2f}")
    if wins and losses and sum(e["pnl"] for e in losses) != 0:
        pf = abs(sum(e["pnl"] for e in wins) / sum(e["pnl"] for e in losses))
        print(f"獲利因子: {pf:.2f}")

    # 口數分佈
    print(f"\n--- 口數分佈 ---")
    lot_dist = {}
    for e in exits:
        ml = e.get("max_lots", 1)
        lot_dist[ml] = lot_dist.get(ml, 0) + 1
    for k in sorted(lot_dist):
        subset = [e for e in exits if e.get("max_lots", 1) == k]
        sp = sum(e["pnl"] for e in subset)
        print(f"  最大{k}口: {lot_dist[k]}筆, 損益{sp:+,.0f}點")

    # 多空分別
    for label, subset in [("做多", longs), ("做空", shorts)]:
        if not subset:
            continue
        sw = [e for e in subset if e["pnl"] > 0]
        sp = sum(e["pnl"] for e in subset)
        print(f"  {label}: {len(subset)}筆, 勝率{len(sw)/len(subset)*100:.0f}%, {sp:+,.0f}點")

    # 月度
    print(f"\n--- 月度損益 ---")
    monthly = {}
    for e in events:
        if "pnl" not in e:
            continue
        key = e["date"].strftime("%Y-%m")
        monthly[key] = monthly.get(key, 0) + e["pnl"]

    running = 0
    pos_m = 0
    for k in sorted(monthly):
        running += monthly[k]
        if monthly[k] > 0:
            pos_m += 1
        bar = "█" * max(1, int(abs(monthly[k]) / 100))
        icon = "🟢" if monthly[k] >= 0 else "🔴"
        print(f"  {k} | {monthly[k]:>+7,.0f}點 | 累計{running:>+8,.0f} | {icon} {bar}")
    print(f"  正報酬月: {pos_m}/{len(monthly)} ({pos_m/len(monthly)*100:.0f}%)")

    # 出場原因
    print(f"\n--- 出場原因 ---")
    reasons = {}
    for e in exits:
        r = e["signal"]
        if "停損" in r:
            k = "移動停損"
        elif "翻" in r:
            k = "持股線反轉"
        elif "弱勢" in r or "強勢" in r:
            k = "連續動能反轉"
        else:
            k = r
        reasons[k] = reasons.get(k, 0) + 1
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}次")

    # 最近交易
    print(f"\n--- 最近 5 筆 ---")
    for e in exits[-5:]:
        d = "多" if e["direction"] == 1 else "空"
        entry = e["entry_date"].strftime("%m/%d")
        exit_d = e["date"].strftime("%m/%d")
        ml = e.get("max_lots", 1)
        print(f"  [{d}{ml}口] {entry}→{exit_d} | {e['signal'][:18]} | {e['pnl']:+,.0f}點 ({e['pnl_pct']:+.2f}%)")


def main():
    print("取得 60 分鐘資料...")
    df = fetch_60m()
    print(f"{len(df)} bars")

    print("計算指標...")
    df = calc_indicators(df)
    print(f"有效: {len(df)} bars\n")

    print("=" * 60)
    print("更生人策略 v5（加減碼 + 回撤控制）")
    print(f"最大 {MAX_LOTS} 口 | 手續費 {FEE}點/邊 | 滑價 {SLIP}點/邊")

    e1 = backtest_v5(df, mode="both")
    print_report(e1, "⑩ 多空雙做（加減碼）")

    e2 = backtest_v5(df, mode="long")
    print_report(e2, "⑪ 只做多（加減碼）")

    # v5c: 加固定點數停損
    for max_loss_pts in [200, 300, 400]:
        e5c = backtest_v5c(df, mode="both", max_loss_per_lot=max_loss_pts)
        print_report(e5c, f"⑬ 雙做+加減碼+單筆停損{max_loss_pts}點/口")

    # 對比
    print(f"\n{'='*60}")
    print("總覽對比:")
    from backtest_revive_v4_intraday import backtest_dual, calc_indicators as ci4, fetch_60m as f4
    df4 = f4()
    df4 = ci4(df4)

    results = []
    for name, evts in [("v4固定1口雙做", None), ("v5加減碼雙做", e1), ("v5只做多", e2)]:
        if evts is None:
            t4 = backtest_dual(df4, mode="both")
            c = [t for t in t4 if "pnl" in t]
            pnl = sum(t["pnl"] for t in c)
            cum = np.cumsum([t["pnl"] for t in c])
        else:
            c = [e for e in evts if "pnl" in e]
            pnl = sum(e["pnl"] for e in c)
            cum = np.cumsum([e["pnl"] for e in c])
        dd = (cum - np.maximum.accumulate(cum)).min() if len(cum) > 0 else 0
        print(f"  {name}: {pnl:+,.0f}點, 回撤{dd:,.0f}點")

    for max_loss_pts in [200, 300, 400]:
        e5c = backtest_v5c(df, mode="both", max_loss_per_lot=max_loss_pts)
        c = [e for e in e5c if "pnl" in e]
        pnl = sum(e["pnl"] for e in c)
        cum = np.cumsum([e["pnl"] for e in c])
        dd = (cum - np.maximum.accumulate(cum)).min() if len(cum) > 0 else 0
        print(f"  v5c停損{max_loss_pts}點/口: {pnl:+,.0f}點, 回撤{dd:,.0f}點")

    print(f"{'='*60}")


if __name__ == "__main__":
    main()
