#!/usr/bin/env python3
"""
更生人策略回測 v4 — 60 分線 + 多空雙做
測試：1. 多空都做 2. 只做多 3. 只做空
使用加權指數 60 分鐘 K 線（約 2 年資料）
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
    # 加權指數 60m 沒有成交量，不過濾
    return df


def calc_indicators(df):
    # 持股線（用 bar 數對應，88日 ≈ 88*5=440 bars for 60m）
    # 但 60m 一天約 5 根K，所以等效：
    # 88日 → 440 bars, 17日 → 85 bars
    # 不過直接用原始參數在短週期上效果不好，要調整
    # 改用短週期等效參數：
    VWAP_PERIOD = 440   # 88日等效（用SMA代替VWAP，因為60m沒有成交量）
    SMA_PERIOD = 85     # 17日等效

    # 加權指數 60m 沒成交量，用 SMA 代替 VWAP
    df["vwap"] = df["close"].rolling(VWAP_PERIOD).mean()
    df["sma"] = df["close"].rolling(SMA_PERIOD).mean()
    df["holding_line"] = df["sma"].rolling(2).max()
    df["reflect_line"] = 2 * df["sma"] - df["holding_line"]
    df["holding_bull"] = df["reflect_line"] >= df["vwap"]

    # MACD(12,26,9) 保持不變（這些是 bar 數，不是日數）
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

    # CCI(14)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - sma_tp) / (0.015 * mad)

    # 連續弱勢/強勢 streak
    df["weak_streak"] = 0
    df["strong_streak"] = 0
    ws = 0
    ss = 0
    for i in range(len(df)):
        if df.iloc[i]["macd_str"] == -1:
            ws += 1
        else:
            ws = 0
        if df.iloc[i]["macd_str"] == 1:
            ss += 1
        else:
            ss = 0
        df.iloc[i, df.columns.get_loc("weak_streak")] = ws
        df.iloc[i, df.columns.get_loc("strong_streak")] = ss

    df.dropna(inplace=True)
    return df


# 交易成本（點）
FEE = 2        # 手續費單邊
SLIP = 1       # 滑價單邊
COST = (FEE + SLIP) * 2  # 來回
POINT_VALUE = 200


def backtest_dual(df, mode="both"):
    """
    mode: "both"=多空都做, "long"=只做多, "short"=只做空
    """
    position = 0  # 0=空手, 1=多, -1=空
    entry_price = 0
    max_price = 0
    min_price = 999999
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            # === 做多進場 ===
            if mode in ("both", "long"):
                if (row["holding_bull"] and
                    row["macd_str"] == 1 and prev["macd_str"] != 1):
                    position = 1
                    entry_price = row["close"] + SLIP + FEE
                    max_price = row["close"]
                    trades.append({
                        "type": "LONG",
                        "entry_date": row.name,
                        "entry_price": entry_price,
                        "signal": "多:持股線多+MACD紅",
                    })
                    continue

            # === 做空進場 ===
            if mode in ("both", "short"):
                if (not row["holding_bull"] and
                    row["macd_str"] == -1 and prev["macd_str"] != -1):
                    position = -1
                    entry_price = row["close"] - SLIP - FEE
                    min_price = row["close"]
                    trades.append({
                        "type": "SHORT",
                        "entry_date": row.name,
                        "entry_price": entry_price,
                        "signal": "空:持股線空+MACD綠",
                    })
                    continue

        elif position == 1:
            # === 多單出場 ===
            max_price = max(max_price, row["close"])
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            dd = (row["close"] - max_price) / max_price * 100

            exit_sig = None

            # 持股線翻空
            if not row["holding_bull"] and prev["holding_bull"]:
                exit_sig = "持股線翻空"
            # 連續弱勢 3 bars
            elif row["weak_streak"] >= 3:
                exit_sig = "連續弱勢3bar"
            # 移動停損 2%（60m 用較緊的停損）
            elif dd <= -2:
                exit_sig = f"移動停損({dd:.1f}%)"

            if exit_sig:
                pnl = row["close"] - entry_price - (FEE + SLIP)
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl / entry_price * 100,
                    "exit_signal": exit_sig,
                })
                position = 0

        elif position == -1:
            # === 空單出場 ===
            min_price = min(min_price, row["close"])
            pnl_pct = (entry_price - row["close"]) / entry_price * 100
            bounce = (row["close"] - min_price) / min_price * 100 if min_price > 0 else 0

            exit_sig = None

            # 持股線翻多
            if row["holding_bull"] and not prev["holding_bull"]:
                exit_sig = "持股線翻多"
            # 連續強勢 3 bars
            elif row["strong_streak"] >= 3:
                exit_sig = "連續強勢3bar"
            # 移動停損 2%
            elif bounce >= 2:
                exit_sig = f"移動停損(反彈{bounce:.1f}%)"

            if exit_sig:
                pnl = entry_price - row["close"] - (FEE + SLIP)
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl / entry_price * 100,
                    "exit_signal": exit_sig,
                })
                position = 0

    # 回測結束平倉
    if position != 0 and trades and "exit_date" not in trades[-1]:
        last = df.iloc[-1]["close"]
        if position == 1:
            pnl = last - entry_price - (FEE + SLIP)
        else:
            pnl = entry_price - last - (FEE + SLIP)
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": last,
            "pnl": pnl,
            "pnl_pct": pnl / entry_price * 100,
            "exit_signal": "回測結束",
        })

    return trades


def print_report(trades, name):
    completed = [t for t in trades if "pnl" in t]
    if not completed:
        print(f"\n{'='*60}\n策略: {name}\n無交易")
        return

    longs = [t for t in completed if t["type"] == "LONG"]
    shorts = [t for t in completed if t["type"] == "SHORT"]
    wins = [t for t in completed if t["pnl"] > 0]
    losses = [t for t in completed if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in completed)
    win_rate = len(wins) / len(completed) * 100

    cum = np.cumsum([t["pnl"] for t in completed])
    peak = np.maximum.accumulate(cum)
    max_dd = (cum - peak).min()

    # 平均持有時間（小時）
    hold_hours = []
    for t in completed:
        if "entry_date" in t and "exit_date" in t:
            delta = (t["exit_date"] - t["entry_date"]).total_seconds() / 3600
            hold_hours.append(delta)
    avg_hold_h = np.mean(hold_hours) if hold_hours else 0

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"期間: {completed[0]['entry_date'].strftime('%Y-%m-%d')} ~ {completed[-1].get('exit_date', pd.Timestamp.now()).strftime('%Y-%m-%d')}")
    print(f"交易: {len(completed)}筆 (做多{len(longs)} / 做空{len(shorts)})")
    print(f"勝率: {win_rate:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"總損益: {total_pnl:+.0f}點 ({total_pnl*POINT_VALUE:+,.0f}元)")

    if completed:
        avg = np.mean([t["pnl_pct"] for t in completed])
        mx = max(t["pnl_pct"] for t in completed)
        mn = min(t["pnl_pct"] for t in completed)
        print(f"平均每筆: {avg:+.2f}% | 最大獲利: {mx:+.2f}% | 最大虧損: {mn:+.2f}%")

    print(f"最大回撤: {max_dd:.0f}點 ({max_dd*POINT_VALUE:,.0f}元)")
    print(f"平均持有: {avg_hold_h:.1f}小時")
    print(f"總成本: {len(completed)*COST}點")

    if wins:
        print(f"平均獲利: +{np.mean([t['pnl_pct'] for t in wins]):.2f}%")
    if losses:
        print(f"平均虧損: {np.mean([t['pnl_pct'] for t in losses]):.2f}%")
    if wins and losses and sum(t["pnl"] for t in losses) != 0:
        pf = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses))
        print(f"獲利因子: {pf:.2f}")

    # 多空分別統計
    for label, subset in [("做多", longs), ("做空", shorts)]:
        if not subset:
            continue
        sw = [t for t in subset if t["pnl"] > 0]
        sp = sum(t["pnl"] for t in subset)
        swr = len(sw) / len(subset) * 100 if subset else 0
        print(f"  {label}: {len(subset)}筆, 勝率{swr:.0f}%, 損益{sp:+.0f}點")

    # 月度績效
    print(f"\n--- 月度績效 ---")
    months = {}
    for t in completed:
        key = t["entry_date"].strftime("%Y-%m")
        if key not in months:
            months[key] = {"pnl": 0, "count": 0, "wins": 0}
        months[key]["pnl"] += t["pnl"]
        months[key]["count"] += 1
        if t["pnl"] > 0:
            months[key]["wins"] += 1

    positive_months = sum(1 for m in months.values() if m["pnl"] > 0)
    total_months = len(months)
    print(f"  正報酬月份: {positive_months}/{total_months} ({positive_months/total_months*100:.0f}%)")

    # 按季度彙整
    quarters = {}
    for k, v in months.items():
        y, m = k.split("-")
        q = f"{y}Q{(int(m)-1)//3+1}"
        if q not in quarters:
            quarters[q] = 0
        quarters[q] += v["pnl"]
    for q in sorted(quarters):
        print(f"  {q}: {quarters[q]:+.0f}點 ({quarters[q]*POINT_VALUE:+,.0f}元)")

    # 出場原因
    print(f"\n--- 出場原因 ---")
    reasons = {}
    for t in completed:
        r = t.get("exit_signal", "?")
        if "停損" in r:
            k = "移動停損"
        elif "翻空" in r or "翻多" in r:
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
    for t in completed[-5:]:
        e = t["entry_date"].strftime("%m/%d %H:%M")
        x = t.get("exit_date", pd.Timestamp.now()).strftime("%m/%d %H:%M")
        tp = "多" if t["type"] == "LONG" else "空"
        print(f"  [{tp}] {e}→{x} | {t.get('exit_signal','')[:15]} | {t['pnl']:+.0f}點 ({t['pnl_pct']:+.2f}%)")


def main():
    print("取得 60 分鐘資料...")
    df = fetch_60m()
    print(f"{len(df)} bars ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    print("計算指標...")
    df = calc_indicators(df)
    print(f"有效資料: {len(df)} bars\n")

    print("=" * 60)
    print("更生人策略 v4（60 分線 + 多空）")
    print(f"手續費: {FEE}點/邊 | 滑價: {SLIP}點/邊 | 每點{POINT_VALUE}元")

    t1 = backtest_dual(df, mode="both")
    print_report(t1, "⑦ 60分線 多空雙做")

    t2 = backtest_dual(df, mode="long")
    print_report(t2, "⑧ 60分線 只做多")

    t3 = backtest_dual(df, mode="short")
    print_report(t3, "⑨ 60分線 只做空")

    # Buy & Hold
    first = df.iloc[0]["close"]
    last = df.iloc[-1]["close"]
    bh = (last - first) / first * 100
    print(f"\n{'='*60}")
    print(f"📊 Buy & Hold: {first:.0f} → {last:.0f} ({bh:+.1f}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
