#!/usr/bin/env python3
"""
更生人策略回測 — 台指期 5 年
策略指標：
1. 持股線 (revive-holdingLine): 88日VWAP, 17SMA, highest(17SMA,2), 反射線
2. MACD 強弱 (revive-macd): MACD(12,26,9) + 17EMA 強弱判斷
3. 超級CCI 三部曲
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime


def fetch_data():
    """取得台灣加權指數 5 年日線資料（代替台指期）"""
    data = yf.download("^TWII", start="2021-01-01", end="2026-03-31", progress=False)
    df = pd.DataFrame()
    df["open"] = data[("Open", "^TWII")]
    df["high"] = data[("High", "^TWII")]
    df["low"] = data[("Low", "^TWII")]
    df["close"] = data[("Close", "^TWII")]
    df["volume"] = data[("Volume", "^TWII")]
    df.dropna(inplace=True)
    return df


def calc_holding_line(df):
    """持股線指標 — 4 條線"""
    # 成交金額 = volume * (open + close) / 2
    df["amount"] = df["volume"] * (df["open"] + df["close"]) / 2

    # 線1: 88日 VWAP = sum(amount, 88) / sum(volume, 88)
    df["vwap88"] = df["amount"].rolling(88).sum() / df["volume"].rolling(88).sum()

    # 線2: 17日 SMA
    df["sma17"] = df["close"].rolling(17).mean()

    # 線3: 近2期 17MA 最高值
    df["holding_line"] = df["sma17"].rolling(2).max()

    # 線4: 反射線 = 2 * sma17 - holding_line
    df["reflect_line"] = 2 * df["sma17"] - df["holding_line"]

    # 多空判斷: 反射線 >= 88VWAP → golden
    df["holding_signal"] = np.where(df["reflect_line"] >= df["vwap88"], 1, -1)

    return df


def calc_macd_strength(df):
    """MACD 強弱指標"""
    # 標準 MACD(12, 26, 9)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["osc"] = df["dif"] - df["dea"]

    # 17日 EMA
    df["ema17"] = df["close"].ewm(span=17, adjust=False).mean()

    # 強弱判定
    ema17_up = df["ema17"] > df["ema17"].shift(1)
    osc_up = df["osc"] > df["osc"].shift(1)
    ema17_down = df["ema17"] < df["ema17"].shift(1)
    osc_down = df["osc"] < df["osc"].shift(1)

    # 紅=強(1), 藍=普通(0), 綠=弱(-1)
    df["macd_strength"] = 0  # 藍(普通)
    df.loc[ema17_up & osc_up, "macd_strength"] = 1    # 紅(強勢)
    df.loc[ema17_down & osc_down, "macd_strength"] = -1  # 綠(弱勢)

    return df


def calc_super_cci(df, period=14):
    """超級CCI"""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - sma_tp) / (0.015 * mad)
    return df


def backtest_combined(df):
    """組合策略回測"""
    position = 0  # 0=空手, 1=多, -1=空
    entry_price = 0
    trades = []
    equity = [0]

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # === 進場條件 ===
        if position == 0:
            # 做多: 持股線金叉 + MACD強勢(紅) 或 普通(藍)
            if (row["holding_signal"] == 1 and
                prev["holding_signal"] == -1 and
                row["macd_strength"] >= 0):
                position = 1
                entry_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "持股線金叉 + MACD非弱勢"
                })

            # 做多(CCI): CCI從超跌區回升 + 持股線多方
            elif (row["cci"] >= -200 and prev["cci"] < -200 and
                  row["holding_signal"] == 1):
                position = 1
                entry_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "CCI二部曲 + 持股線多方"
                })

        # === 出場條件 ===
        elif position == 1:
            # 停損/停利
            pnl_pct = (row["close"] - entry_price) / entry_price * 100

            # 出場: 持股線死叉
            if row["holding_signal"] == -1 and prev["holding_signal"] == 1:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": "持股線死叉"
                })
                position = 0
                entry_price = 0

            # 出場: MACD 轉弱勢(綠)
            elif row["macd_strength"] == -1 and prev["macd_strength"] != -1:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": "MACD轉弱勢"
                })
                position = 0
                entry_price = 0

            # 停損 -5%
            elif pnl_pct <= -5:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": "停損-5%"
                })
                position = 0
                entry_price = 0

    # 如果最後還有持倉，以最後收盤價平倉
    if position != 0 and trades and "exit_date" not in trades[-1]:
        pnl = df.iloc[-1]["close"] - entry_price
        pnl_pct = pnl / entry_price * 100
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": df.iloc[-1]["close"],
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_signal": "回測結束平倉"
        })

    return trades


def backtest_holding_only(df):
    """純持股線策略"""
    position = 0
    entry_price = 0
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            if row["holding_signal"] == 1 and prev["holding_signal"] == -1:
                position = 1
                entry_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "持股線金叉"
                })
        elif position == 1:
            if row["holding_signal"] == -1 and prev["holding_signal"] == 1:
                pnl = row["close"] - entry_price
                pnl_pct = pnl / entry_price * 100
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "exit_signal": "持股線死叉"
                })
                position = 0
                entry_price = 0

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


def backtest_macd_strength_only(df):
    """純 MACD 強弱策略"""
    position = 0
    entry_price = 0
    trades = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        if position == 0:
            # 進場：藍轉紅
            if row["macd_strength"] == 1 and prev["macd_strength"] != 1:
                position = 1
                entry_price = row["close"]
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": "MACD轉強勢(紅)"
                })
        elif position == 1:
            # 出場：轉弱勢(綠)
            if row["macd_strength"] == -1 and prev["macd_strength"] != -1:
                pnl = row["close"] - entry_price
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl,
                    "pnl_pct": pnl / entry_price * 100,
                    "exit_signal": "MACD轉弱勢(綠)"
                })
                position = 0
                entry_price = 0

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
    """列印回測報告"""
    if not trades:
        print(f"\n{'='*60}")
        print(f"策略: {name}")
        print(f"無交易")
        return

    completed = [t for t in trades if "pnl" in t]
    if not completed:
        print(f"\n{'='*60}")
        print(f"策略: {name}")
        print(f"無已完成交易")
        return

    wins = [t for t in completed if t["pnl"] > 0]
    losses = [t for t in completed if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in completed)
    avg_pnl_pct = np.mean([t["pnl_pct"] for t in completed])
    max_win = max([t["pnl_pct"] for t in completed]) if completed else 0
    max_loss = min([t["pnl_pct"] for t in completed]) if completed else 0
    win_rate = len(wins) / len(completed) * 100

    # 計算最大回撤
    cum_pnl = np.cumsum([t["pnl"] for t in completed])
    peak = np.maximum.accumulate(cum_pnl)
    drawdown = cum_pnl - peak
    max_drawdown = drawdown.min() if len(drawdown) > 0 else 0

    # 平均持有天數
    hold_days = []
    for t in completed:
        if "entry_date" in t and "exit_date" in t:
            days = (t["exit_date"] - t["entry_date"]).days
            hold_days.append(days)
    avg_hold = np.mean(hold_days) if hold_days else 0

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"期間: {completed[0]['entry_date'].strftime('%Y-%m-%d')} ~ {completed[-1].get('exit_date', pd.Timestamp.now()).strftime('%Y-%m-%d')}")
    print(f"總交易次數: {len(completed)}")
    print(f"勝率: {win_rate:.1f}% ({len(wins)}勝 / {len(losses)}負)")
    print(f"總損益(點): {total_pnl:.1f}")
    print(f"平均每筆損益(%): {avg_pnl_pct:.2f}%")
    print(f"最大單筆獲利: {max_win:.2f}%")
    print(f"最大單筆虧損: {max_loss:.2f}%")
    print(f"最大回撤(點): {max_drawdown:.1f}")
    print(f"平均持有天數: {avg_hold:.1f}")

    # 勝負的平均
    if wins:
        avg_win = np.mean([t["pnl_pct"] for t in wins])
        print(f"平均獲利(%): +{avg_win:.2f}%")
    if losses:
        avg_loss = np.mean([t["pnl_pct"] for t in losses])
        print(f"平均虧損(%): {avg_loss:.2f}%")
    if wins and losses:
        profit_factor = abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses)) if sum(t["pnl"] for t in losses) != 0 else float("inf")
        print(f"獲利因子: {profit_factor:.2f}")

    # 年度明細
    print(f"\n--- 年度績效 ---")
    for t in completed:
        year = t["entry_date"].year
    years = sorted(set(t["entry_date"].year for t in completed))
    for y in years:
        year_trades = [t for t in completed if t["entry_date"].year == y]
        year_pnl = sum(t["pnl"] for t in year_trades)
        year_wins = len([t for t in year_trades if t["pnl"] > 0])
        year_wr = year_wins / len(year_trades) * 100 if year_trades else 0
        print(f"  {y}: {len(year_trades)}筆, 損益={year_pnl:+.0f}點, 勝率={year_wr:.0f}%")

    # 最近 5 筆交易明細
    print(f"\n--- 最近 5 筆交易 ---")
    for t in completed[-5:]:
        entry = t["entry_date"].strftime("%Y-%m-%d")
        exit_d = t.get("exit_date", pd.Timestamp.now()).strftime("%Y-%m-%d")
        print(f"  {entry} → {exit_d} | {t['signal']} → {t.get('exit_signal','')} | {t['pnl_pct']:+.2f}%")


def main():
    print("正在取得台灣加權指數 5 年資料...")
    df = fetch_data()
    print(f"取得 {len(df)} 筆日線資料 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    print("計算指標中...")
    df = calc_holding_line(df)
    df = calc_macd_strength(df)
    df = calc_super_cci(df)
    df.dropna(inplace=True)
    print(f"有效資料: {len(df)} 筆")

    # 三種策略回測
    print("\n" + "=" * 60)
    print("更生人策略回測結果（台灣加權指數 5 年）")

    trades1 = backtest_holding_only(df)
    print_report(trades1, "① 純持股線策略（金叉買/死叉賣）")

    trades2 = backtest_macd_strength_only(df)
    print_report(trades2, "② 純MACD強弱策略（紅進/綠出）")

    trades3 = backtest_combined(df)
    print_report(trades3, "③ 組合策略（持股線+MACD+CCI）")

    # Buy & Hold 對照
    first_price = df.iloc[0]["close"]
    last_price = df.iloc[-1]["close"]
    bh_return = (last_price - first_price) / first_price * 100
    print(f"\n{'='*60}")
    print(f"📊 Buy & Hold 對照: {first_price:.0f} → {last_price:.0f} ({bh_return:+.1f}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
