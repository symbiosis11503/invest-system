#!/usr/bin/env python3
"""
更生人策略回測 v6 — 多時間框架（MTF）
60 分線交易，4 小時 + 日線做趨勢過濾
只在高週期趨勢方向一致時進場
"""

import yfinance as yf
import pandas as pd
import numpy as np


FEE = 2
SLIP = 1
POINT_VALUE = 200
MAX_LOTS = 3


def fetch_data():
    """取得 60m 和日線資料"""
    df_60m = yf.download("^TWII", period="max", interval="60m", progress=False)
    df_1d = yf.download("^TWII", start="2023-01-01", end="2026-03-31", interval="1d", progress=False)

    def clean(data, ticker="^TWII"):
        df = pd.DataFrame()
        df["open"] = data[("Open", ticker)]
        df["high"] = data[("High", ticker)]
        df["low"] = data[("Low", ticker)]
        df["close"] = data[("Close", ticker)]
        df["volume"] = data[("Volume", ticker)]
        df.index = data.index.get_level_values(0)
        df.dropna(inplace=True)
        return df

    return clean(df_60m), clean(df_1d)


def resample_to_4h(df_60m):
    """60m → 4h K 線"""
    df = df_60m.copy()
    df.index = pd.to_datetime(df.index)
    # 確保有 timezone info 移除（如果有的話）
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    resampled = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return resampled


def calc_trend(df, label=""):
    """計算趨勢指標（持股線 + MACD 強弱）"""
    # 持股線（使用原始參數，依 timeframe 調整）
    if label == "60m":
        vwap_p, sma_p = 440, 85  # 88日*5, 17日*5
    elif label == "4h":
        vwap_p, sma_p = 110, 21  # 88日*1.25, 17日*1.25
    else:  # daily
        vwap_p, sma_p = 88, 17

    df["vwap"] = df["close"].rolling(vwap_p).mean()
    df["sma"] = df["close"].rolling(sma_p).mean()
    df["holding_line"] = df["sma"].rolling(2).max()
    df["reflect_line"] = 2 * df["sma"] - df["holding_line"]
    df["holding_bull"] = df["reflect_line"] >= df["vwap"]

    # MACD 強弱
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

    # Streaks
    df["weak_streak"] = 0
    df["strong_streak"] = 0
    ws = ss = 0
    for i in range(len(df)):
        ws = ws + 1 if df.iloc[i]["macd_str"] == -1 else 0
        ss = ss + 1 if df.iloc[i]["macd_str"] == 1 else 0
        df.iloc[i, df.columns.get_loc("weak_streak")] = ws
        df.iloc[i, df.columns.get_loc("strong_streak")] = ss

    df.dropna(inplace=True)
    return df


def merge_mtf(df_60m, df_4h, df_1d):
    """將高週期趨勢合併到 60m"""
    # 4h 趨勢：取最近的 4h bar
    df_4h_trend = df_4h[["holding_bull", "macd_str"]].copy()
    df_4h_trend.columns = ["h4_bull", "h4_macd"]

    # 日線趨勢
    df_1d_trend = df_1d[["holding_bull", "macd_str"]].copy()
    df_1d_trend.columns = ["d1_bull", "d1_macd"]

    # 對齊：用 asof merge（取<=當前時間的最近一筆）
    df = df_60m.copy()
    df.index = pd.to_datetime(df.index)

    # 去 timezone
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    if df_4h_trend.index.tz is not None:
        df_4h_trend.index = df_4h_trend.index.tz_localize(None)
    if df_1d_trend.index.tz is not None:
        df_1d_trend.index = df_1d_trend.index.tz_localize(None)

    df = pd.merge_asof(df, df_4h_trend, left_index=True, right_index=True)
    df = pd.merge_asof(df, df_1d_trend, left_index=True, right_index=True)

    df.dropna(inplace=True)
    return df


def backtest_mtf(df, mode="both", max_loss_per_lot=200, require_daily=True, require_4h=True):
    """
    多時間框架回測：
    - 進場：60m 訊號 + 4h 趨勢一致 + 日線趨勢一致
    - 出場：同 v5（固定停損 + 移動停損 + 連續弱勢 + 持股線反轉）
    - 加減碼：同 v5b
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

            # 做多：60m 訊號 + 高週期過濾
            if mode in ("both", "long"):
                if (row["holding_bull"] and
                    row["macd_str"] == 1 and prev["macd_str"] != 1):
                    # 高週期過濾
                    h4_ok = (not require_4h) or row["h4_bull"]
                    d1_ok = (not require_daily) or row["d1_bull"]
                    if h4_ok and d1_ok:
                        entered = True
                        new_dir = 1

            # 做空：60m 訊號 + 高週期過濾
            if not entered and mode in ("both", "short"):
                if (not row["holding_bull"] and
                    row["macd_str"] == -1 and prev["macd_str"] != -1):
                    h4_ok = (not require_4h) or (not row["h4_bull"])
                    d1_ok = (not require_daily) or (not row["d1_bull"])
                    if h4_ok and d1_ok:
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

                # 記錄趨勢狀態
                h4 = "多" if row["h4_bull"] else "空"
                d1 = "多" if row["d1_bull"] else "空"
                sig = f"{'多' if new_dir == 1 else '空'}:1口(4h{h4}/日{d1})"
                events.append({
                    "type": "ENTRY", "date": row.name, "direction": direction,
                    "lots": 1, "price": price, "signal": sig,
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

            # 加碼（高週期趨勢仍一致才加）
            if not restrict_mode and lots < MAX_LOTS:
                htf_aligned = False
                if direction == 1:
                    htf_aligned = row["h4_bull"] and row["d1_bull"]
                else:
                    htf_aligned = (not row["h4_bull"]) and (not row["d1_bull"])

                if lots == 1 and unrealized_pct > 0.5 and htf_aligned:
                    trend_ok = (direction == 1 and row["holding_bull"]) or \
                               (direction == -1 and not row["holding_bull"])
                    if trend_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 1 + add_price * 1) / 2
                        lots = 2
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 2,
                                       "price": add_price, "signal": "加碼2口(MTF一致)"})

                if lots == 2 and unrealized_pct > 1.5 and htf_aligned:
                    macd_ok = (direction == 1 and row["macd_str"] == 1) or \
                              (direction == -1 and row["macd_str"] == -1)
                    if macd_ok:
                        add_price = row["close"] + (SLIP + FEE) * direction
                        avg_price = (avg_price * 2 + add_price * 1) / 3
                        lots = 3
                        open_entries.append({"date": row.name, "price": add_price, "lots": 1})
                        events.append({"type": "ADD", "date": row.name, "lots": 3,
                                       "price": add_price, "signal": "加碼3口(MTF+MACD)"})

            # 出場
            exit_sig = None

            # 固定停損
            if unrealized_pts <= -max_loss_per_lot:
                exit_sig = f"固定停損({unrealized_pts:.0f}點)"

            # 高週期反轉 → 提前出場（不等60m訊號）
            if not exit_sig:
                if direction == 1 and not row["d1_bull"] and prev.get("d1_bull", True):
                    exit_sig = "日線翻空"
                elif direction == -1 and row["d1_bull"] and not prev.get("d1_bull", False):
                    exit_sig = "日線翻多"

            # 60m 持股線反轉
            if not exit_sig:
                if direction == 1 and not row["holding_bull"] and prev["holding_bull"]:
                    exit_sig = "60m持股線翻空"
                elif direction == -1 and row["holding_bull"] and not prev["holding_bull"]:
                    exit_sig = "60m持股線翻多"

            # 連續弱勢/強勢
            if not exit_sig:
                if direction == 1 and row["weak_streak"] >= 3:
                    exit_sig = "連續弱勢3bar"
                elif direction == -1 and row["strong_streak"] >= 3:
                    exit_sig = "連續強勢3bar"

            # 移動停損
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

    if not exits:
        print(f"\n{'='*60}\n策略: {name}\n無交易")
        return

    wins = [e for e in exits if e["pnl"] > 0]
    losses = [e for e in exits if e["pnl"] <= 0]
    total_pnl = sum(e["pnl"] for e in exits)
    longs = [e for e in exits if e["direction"] == 1]
    shorts = [e for e in exits if e["direction"] == -1]

    cum = np.cumsum([e["pnl"] for e in exits])
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"交易: {len(exits)}筆 (多{len(longs)}/空{len(shorts)}) | 加碼: {len(adds)}次")
    print(f"勝率: {len(wins)/len(exits)*100:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"總損益: {total_pnl:+,.0f}點 ({total_pnl*POINT_VALUE:+,.0f}元)")
    if exits:
        print(f"平均: {np.mean([e['pnl'] for e in exits]):+,.0f}點 | 最大獲利: {max(e['pnl'] for e in exits):+,.0f} | 最大虧損: {min(e['pnl'] for e in exits):+,.0f}")
    print(f"最大回撤: {max_dd:,.0f}點 ({max_dd*POINT_VALUE:,.0f}元)")
    if total_pnl > 0 and max_dd != 0:
        print(f"Recovery: {total_pnl/abs(max_dd):.2f}")
    if wins and losses and sum(e["pnl"] for e in losses) != 0:
        pf = abs(sum(e["pnl"] for e in wins) / sum(e["pnl"] for e in losses))
        print(f"獲利因子: {pf:.2f}")

    # 口數
    for k in sorted(set(e.get("max_lots", 1) for e in exits)):
        sub = [e for e in exits if e.get("max_lots", 1) == k]
        print(f"  {k}口: {len(sub)}筆, {sum(e['pnl'] for e in sub):+,.0f}點")

    # 多空
    for label, sub in [("做多", longs), ("做空", shorts)]:
        if sub:
            sw = len([e for e in sub if e["pnl"] > 0])
            print(f"  {label}: {len(sub)}筆, 勝率{sw/len(sub)*100:.0f}%, {sum(e['pnl'] for e in sub):+,.0f}點")

    # 月度
    monthly = {}
    for e in exits:
        k = e["date"].strftime("%Y-%m")
        monthly[k] = monthly.get(k, 0) + e["pnl"]
    running = 0
    pos_m = sum(1 for v in monthly.values() if v > 0)
    print(f"\n  正報酬月: {pos_m}/{len(monthly)} ({pos_m/len(monthly)*100:.0f}%)" if monthly else "")

    # 季度
    quarters = {}
    for k, v in monthly.items():
        y, m = k.split("-")
        q = f"{y}Q{(int(m)-1)//3+1}"
        quarters[q] = quarters.get(q, 0) + v
    for q in sorted(quarters):
        print(f"  {q}: {quarters[q]:+,.0f}點")

    # 出場原因
    reasons = {}
    for e in exits:
        r = e["signal"]
        if "固定停損" in r: k = "固定停損"
        elif "移動停損" in r: k = "移動停損"
        elif "日線" in r: k = "日線反轉"
        elif "持股線" in r or "翻" in r: k = "60m持股線反轉"
        elif "弱勢" in r or "強勢" in r: k = "連續動能反轉"
        else: k = r
        reasons[k] = reasons.get(k, 0) + 1
    print(f"\n  出場: ", end="")
    print(" | ".join(f"{k}:{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))

    # 最近交易
    print(f"\n  最近 3 筆:")
    for e in exits[-3:]:
        d = "多" if e["direction"] == 1 else "空"
        entry = e["entry_date"].strftime("%m/%d")
        ex = e["date"].strftime("%m/%d")
        print(f"    [{d}{e.get('max_lots',1)}口] {entry}→{ex} | {e['signal'][:18]} | {e['pnl']:+,.0f}點")


def main():
    print("取得多時間框架資料...")
    df_60m_raw, df_1d_raw = fetch_data()
    print(f"60m: {len(df_60m_raw)} bars | 日線: {len(df_1d_raw)} bars")

    # 生成 4h
    df_4h_raw = resample_to_4h(df_60m_raw)
    print(f"4h (resample): {len(df_4h_raw)} bars")

    # 計算各時間框架指標
    print("計算指標...")
    df_60m = calc_trend(df_60m_raw, "60m")
    df_4h = calc_trend(df_4h_raw, "4h")
    df_1d = calc_trend(df_1d_raw, "daily")

    # 合併
    df = merge_mtf(df_60m, df_4h, df_1d)
    print(f"合併後有效: {len(df)} bars\n")

    print("=" * 60)
    print("更生人策略 v6 — 多時間框架（MTF）")
    print(f"60m交易 + 4h/日線趨勢過濾 | 最大{MAX_LOTS}口 | 停損200點/口")

    # 不同 MTF 組合測試
    configs = [
        ("⑭ 雙做 無過濾(v5c基準)", "both", False, False),
        ("⑮ 雙做 +4h過濾", "both", False, True),
        ("⑯ 雙做 +日線過濾", "both", True, False),
        ("⑰ 雙做 +4h+日線雙過濾", "both", True, True),
        ("⑱ 只做多 +4h+日線雙過濾", "long", True, True),
        ("⑲ 只做多 +日線過濾", "long", True, False),
    ]

    results = []
    for name, mode, req_d, req_4h in configs:
        evts = backtest_mtf(df, mode=mode, max_loss_per_lot=200,
                            require_daily=req_d, require_4h=req_4h)
        print_report(evts, name)

        exits = [e for e in evts if e["type"] == "EXIT"]
        pnl = sum(e["pnl"] for e in exits)
        cum = np.cumsum([e["pnl"] for e in exits]) if exits else np.array([0])
        dd = (cum - np.maximum.accumulate(cum)).min() if len(cum) > 0 else 0
        results.append((name, len(exits), pnl, dd))

    # 總覽
    print(f"\n{'='*60}")
    print("總覽對比:")
    print(f"{'策略':<35} {'交易':>4} {'損益':>8} {'回撤':>8} {'損益/回撤':>8}")
    for name, cnt, pnl, dd in results:
        ratio = pnl / abs(dd) if dd != 0 else 0
        print(f"  {name:<33} {cnt:>4} {pnl:>+8,.0f} {dd:>8,.0f} {ratio:>8.2f}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
