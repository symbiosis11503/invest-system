#!/usr/bin/env python3
"""
更生人策略回測 v2 — 修正版
根據 v1 回測結果修正：
- 持股線做大方向（只在多方區間操作）
- MACD 強弱做進場時機（紅=進場）
- MACD 弱勢不直接出場，改為連續弱勢 N 天才出
- CCI 做加碼/減碼訊號
- 加入移動停損（trailing stop）
"""

import yfinance as yf
import pandas as pd
import numpy as np


def fetch_data():
    data = yf.download("^TWII", start="2021-01-01", end="2026-03-31", progress=False)
    df = pd.DataFrame()
    df["open"] = data[("Open", "^TWII")]
    df["high"] = data[("High", "^TWII")]
    df["low"] = data[("Low", "^TWII")]
    df["close"] = data[("Close", "^TWII")]
    df["volume"] = data[("Volume", "^TWII")]
    df.dropna(inplace=True)
    return df


def calc_indicators(df):
    # === 持股線 ===
    df["amount"] = df["volume"] * (df["open"] + df["close"]) / 2
    df["vwap88"] = df["amount"].rolling(88).sum() / df["volume"].rolling(88).sum()
    df["sma17"] = df["close"].rolling(17).mean()
    df["holding_line"] = df["sma17"].rolling(2).max()
    df["reflect_line"] = 2 * df["sma17"] - df["holding_line"]
    df["holding_bull"] = df["reflect_line"] >= df["vwap88"]  # True=多方區間

    # === MACD 強弱 ===
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

    df["macd_str"] = 0  # 藍
    df.loc[ema17_up & osc_up, "macd_str"] = 1      # 紅
    df.loc[ema17_down & osc_down, "macd_str"] = -1  # 綠

    # 連續弱勢天數
    df["weak_streak"] = 0
    streak = 0
    for i in range(len(df)):
        if df.iloc[i]["macd_str"] == -1:
            streak += 1
        else:
            streak = 0
        df.iloc[i, df.columns.get_loc("weak_streak")] = streak

    # === CCI ===
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - sma_tp) / (0.015 * mad)

    df.dropna(inplace=True)
    return df


def backtest_v2_optimized(df):
    """
    修正策略 v2：
    進場：持股線多方 + MACD轉紅
    出場：持股線死叉 OR 連續弱勢3天 OR 移動停損7%
    """
    position = 0
    entry_price = 0
    max_price = 0
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            # 進場: 持股線多方 + MACD紅(強勢)
            if (row["holding_bull"] and
                row["macd_str"] == 1 and prev["macd_str"] != 1):
                position = 1
                entry_price = row["close"]
                max_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "持股線多方 + MACD轉紅"
                })

        elif position == 1:
            max_price = max(max_price, row["close"])
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            drawdown_from_peak = (row["close"] - max_price) / max_price * 100

            exit_signal = None

            # 出場1: 持股線翻空
            if not row["holding_bull"] and prev["holding_bull"]:
                exit_signal = "持股線翻空"

            # 出場2: 連續弱勢3天
            elif row["weak_streak"] >= 3:
                exit_signal = f"連續弱勢{int(row['weak_streak'])}天"

            # 出場3: 移動停損 — 從高點回撤7%
            elif drawdown_from_peak <= -7:
                exit_signal = f"移動停損(從高點回撤{drawdown_from_peak:.1f}%)"

            if exit_signal:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": exit_signal
                })
                position = 0
                entry_price = 0
                max_price = 0

    if position != 0 and trades and "exit_date" not in trades[-1]:
        pnl = df.iloc[-1]["close"] - entry_price
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": df.iloc[-1]["close"],
            "pnl": pnl,
            "pnl_pct": pnl / entry_price * 100,
            "exit_signal": "回測結束平倉"
        })

    return trades


def backtest_v2_conservative(df):
    """
    保守版：持股線做大方向，MACD做進場，只用持股線出場+停損
    """
    position = 0
    entry_price = 0
    max_price = 0
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            if (row["holding_bull"] and
                row["macd_str"] == 1 and prev["macd_str"] != 1):
                position = 1
                entry_price = row["close"]
                max_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "持股線多方 + MACD轉紅"
                })

        elif position == 1:
            max_price = max(max_price, row["close"])
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            drawdown_from_peak = (row["close"] - max_price) / max_price * 100

            exit_signal = None

            # 只用持股線出場
            if not row["holding_bull"] and prev["holding_bull"]:
                exit_signal = "持股線翻空"

            # 移動停損 10%
            elif drawdown_from_peak <= -10:
                exit_signal = f"移動停損({drawdown_from_peak:.1f}%)"

            if exit_signal:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": exit_signal
                })
                position = 0
                entry_price = 0
                max_price = 0

    if position != 0 and trades and "exit_date" not in trades[-1]:
        pnl = df.iloc[-1]["close"] - entry_price
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": df.iloc[-1]["close"],
            "pnl": pnl,
            "pnl_pct": pnl / entry_price * 100,
            "exit_signal": "回測結束平倉"
        })

    return trades


def backtest_v2_aggressive(df):
    """
    積極版：多重進場（MACD紅 + CCI超跌回升），MACD弱勢+持股線雙確認出場
    """
    position = 0
    entry_price = 0
    max_price = 0
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            entered = False

            # 進場A: 持股線多方 + MACD轉紅
            if (row["holding_bull"] and
                row["macd_str"] == 1 and prev["macd_str"] != 1):
                entered = True
                sig = "持股線多方 + MACD轉紅"

            # 進場B: 持股線多方 + CCI從超跌回升(-200以下回到-200以上) + MACD非弱勢
            elif (row["holding_bull"] and
                  row["cci"] >= -200 and prev["cci"] < -200 and
                  row["macd_str"] >= 0):
                entered = True
                sig = "CCI超跌回升 + 持股線多方"

            # 進場C: 持股線剛金叉 + MACD紅或藍
            elif (row["holding_bull"] and not prev["holding_bull"] and
                  row["macd_str"] >= 0):
                entered = True
                sig = "持股線金叉 + MACD非弱勢"

            if entered:
                position = 1
                entry_price = row["close"]
                max_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": sig
                })

        elif position == 1:
            max_price = max(max_price, row["close"])
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            drawdown_from_peak = (row["close"] - max_price) / max_price * 100

            exit_signal = None

            # 出場1: 持股線翻空（主出場）
            if not row["holding_bull"] and prev["holding_bull"]:
                exit_signal = "持股線翻空"

            # 出場2: 連續弱勢5天 + 已獲利 → 保護利潤
            elif row["weak_streak"] >= 5 and pnl_pct > 2:
                exit_signal = f"連續弱勢{int(row['weak_streak'])}天(保護利潤)"

            # 出場3: 移動停損 8%
            elif drawdown_from_peak <= -8:
                exit_signal = f"移動停損({drawdown_from_peak:.1f}%)"

            # 出場4: CCI 極端過熱 + MACD轉弱
            elif row["cci"] > 200 and row["macd_str"] == -1:
                exit_signal = "CCI過熱 + MACD轉弱"

            if exit_signal:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": exit_signal
                })
                position = 0
                entry_price = 0
                max_price = 0

    if position != 0 and trades and "exit_date" not in trades[-1]:
        pnl = df.iloc[-1]["close"] - entry_price
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": df.iloc[-1]["close"],
            "pnl": pnl,
            "pnl_pct": pnl / entry_price * 100,
            "exit_signal": "回測結束平倉"
        })

    return trades


def print_report(trades, name):
    if not trades:
        print(f"\n{'='*60}\n策略: {name}\n無交易")
        return

    completed = [t for t in trades if "pnl" in t]
    if not completed:
        print(f"\n{'='*60}\n策略: {name}\n無已完成交易")
        return

    wins = [t for t in completed if t["pnl"] > 0]
    losses = [t for t in completed if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in completed)
    avg_pnl_pct = np.mean([t["pnl_pct"] for t in completed])
    max_win = max(t["pnl_pct"] for t in completed)
    max_loss = min(t["pnl_pct"] for t in completed)
    win_rate = len(wins) / len(completed) * 100

    cum_pnl = np.cumsum([t["pnl"] for t in completed])
    peak = np.maximum.accumulate(cum_pnl)
    max_drawdown = (cum_pnl - peak).min()

    hold_days = []
    for t in completed:
        if "entry_date" in t and "exit_date" in t:
            hold_days.append((t["exit_date"] - t["entry_date"]).days)
    avg_hold = np.mean(hold_days) if hold_days else 0

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"期間: {completed[0]['entry_date'].strftime('%Y-%m-%d')} ~ {completed[-1].get('exit_date', pd.Timestamp.now()).strftime('%Y-%m-%d')}")
    print(f"交易: {len(completed)}筆 | 勝率: {win_rate:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"總損益: {total_pnl:+.0f}點 | 平均每筆: {avg_pnl_pct:+.2f}%")
    print(f"最大獲利: {max_win:+.2f}% | 最大虧損: {max_loss:+.2f}%")
    print(f"最大回撤: {max_drawdown:.0f}點 | 平均持有: {avg_hold:.0f}天")

    if wins:
        print(f"平均獲利: +{np.mean([t['pnl_pct'] for t in wins]):.2f}%")
    if losses:
        print(f"平均虧損: {np.mean([t['pnl_pct'] for t in losses]):.2f}%")
    if wins and losses and sum(t["pnl"] for t in losses) != 0:
        pf = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses))
        print(f"獲利因子: {pf:.2f}")

    # 年度
    print(f"\n--- 年度績效 ---")
    years = sorted(set(t["entry_date"].year for t in completed))
    for y in years:
        yt = [t for t in completed if t["entry_date"].year == y]
        yp = sum(t["pnl"] for t in yt)
        yw = len([t for t in yt if t["pnl"] > 0])
        print(f"  {y}: {len(yt)}筆, {yp:+.0f}點, 勝率{yw/len(yt)*100:.0f}%")

    # 出場原因統計
    print(f"\n--- 出場原因 ---")
    exit_reasons = {}
    for t in completed:
        r = t.get("exit_signal", "unknown")
        # 簡化分類
        if "停損" in r:
            key = "移動停損"
        elif "翻空" in r:
            key = "持股線翻空"
        elif "弱勢" in r:
            key = "連續弱勢"
        elif "CCI" in r:
            key = "CCI過熱"
        elif "回測" in r:
            key = "回測結束"
        else:
            key = r
        exit_reasons[key] = exit_reasons.get(key, 0) + 1
    for k, v in sorted(exit_reasons.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}次")

    # 最近交易
    print(f"\n--- 最近 5 筆 ---")
    for t in completed[-5:]:
        e = t["entry_date"].strftime("%m/%d")
        x = t.get("exit_date", pd.Timestamp.now()).strftime("%m/%d")
        y = t["entry_date"].year
        print(f"  {y}/{e}→{x} | {t['signal'][:20]} → {t.get('exit_signal','')[:20]} | {t['pnl_pct']:+.2f}%")


def main():
    print("取得資料中...")
    df = fetch_data()
    print(f"{len(df)} 筆 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    df = calc_indicators(df)
    print(f"有效資料: {len(df)} 筆\n")

    print("=" * 60)
    print("更生人策略 v2 回測（修正版）")
    print("修正重點: 持股線做方向，MACD做時機，避免互相干擾")

    t1 = backtest_v2_optimized(df)
    print_report(t1, "④ 平衡版（持股線方向+MACD進場+連續弱勢3天出+移動停損7%）")

    t2 = backtest_v2_conservative(df)
    print_report(t2, "⑤ 保守版（持股線方向+MACD進場+只用持股線出場+停損10%）")

    t3 = backtest_v2_aggressive(df)
    print_report(t3, "⑥ 積極版（多重進場+CCI+連續弱勢5天保護利潤+停損8%）")

    # Buy & Hold
    first_price = df.iloc[0]["close"]
    last_price = df.iloc[-1]["close"]
    bh = (last_price - first_price) / first_price * 100
    print(f"\n{'='*60}")
    print(f"📊 Buy & Hold: {first_price:.0f} → {last_price:.0f} ({bh:+.1f}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
