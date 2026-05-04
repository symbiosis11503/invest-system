#!/usr/bin/env python3
"""
更生人策略回測 v3 — 台指期實際資料 + 結算轉倉
- 使用期交所(TAIFEX)台指期近月合約日線
- 每月第三個週三結算，自動轉倉
- 計入轉倉價差、手續費、滑價
"""

import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from io import StringIO


def fetch_taifex_futures(start_year=2021, end_year=2026):
    """從期交所下載台指期歷史資料（近月合約）"""
    import calendar
    all_rows = []
    req_headers = {"User-Agent": "Mozilla/5.0"}
    url = "https://www.taifex.com.tw/cht/3/futDataDown"
    col_names = ["交易日期", "契約", "到期月份(週別)", "開盤價", "最高價", "最低價",
                 "收盤價", "漲跌價", "漲跌%", "成交量", "結算價", "未沖銷契約數",
                 "最後最佳買價", "最後最佳賣價", "歷史最高價", "歷史最低價",
                 "是否因訊息面暫停交易", "交易時段", "價差對單式委託成交量"]

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year == end_year and month > 3:
                break

            last_day = calendar.monthrange(year, month)[1]
            start_date = f"{year}/{month:02d}/01"
            end_date = f"{year}/{month:02d}/{last_day}"

            params = {
                "down_type": "1",
                "queryStartDate": start_date,
                "queryEndDate": end_date,
                "commodity_id": "TX",
            }

            try:
                r = requests.get(url, params=params, headers=req_headers, timeout=15)
                if r.status_code == 200 and len(r.text) > 100:
                    lines = r.text.strip().split("\n")
                    count = 0
                    for line in lines[1:]:  # skip header
                        parts = line.split(",")
                        if len(parts) >= 19 and parts[0].strip().startswith("20"):
                            row = {col_names[i]: parts[i].strip() for i in range(min(len(col_names), len(parts)))}
                            all_rows.append(row)
                            count += 1
                    print(f"  {year}/{month:02d}: {count} rows")
                time.sleep(0.5)
            except Exception as e:
                print(f"  {year}/{month:02d}: Error - {e}")
                time.sleep(1)

    if not all_rows:
        raise Exception("No data fetched")

    df = pd.DataFrame(all_rows)
    return df


def process_futures_data(df):
    """處理期貨資料：取近月合約一般交易時段"""
    # 清理欄位
    df.columns = df.columns.str.strip()
    df["交易日期"] = pd.to_datetime(df["交易日期"].str.strip(), format="%Y/%m/%d")
    df["到期月份(週別)"] = df["到期月份(週別)"].astype(str).str.strip()
    df["交易時段"] = df["交易時段"].astype(str).str.strip()

    # 只取一般交易時段
    df = df[df["交易時段"] == "一般"].copy()

    # 只取 TX（台指期），排除小台
    df = df[df["契約"].str.strip() == "TX"].copy()

    # 轉換數字欄位
    for col in ["開盤價", "最高價", "最低價", "收盤價", "成交量", "結算價"]:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

    # 排除無效資料
    df = df.dropna(subset=["開盤價", "收盤價", "成交量"])
    df = df[df["成交量"] > 0]

    # 取每日近月合約（成交量最大的月份合約）
    daily = []
    for date, group in df.groupby("交易日期"):
        # 取成交量最大的合約（通常是近月）
        best = group.loc[group["成交量"].idxmax()]
        daily.append({
            "date": date,
            "contract": best["到期月份(週別)"],
            "open": best["開盤價"],
            "high": best["最高價"],
            "low": best["最低價"],
            "close": best["收盤價"],
            "volume": best["成交量"],
            "settlement": best["結算價"],
        })

    result = pd.DataFrame(daily)
    result = result.sort_values("date").reset_index(drop=True)
    result.set_index("date", inplace=True)
    return result


def find_settlement_dates(df):
    """找出每月結算日（第三個週三）"""
    settlement_dates = set()
    contracts = df["contract"].unique()

    for date in df.index:
        # 第三個週三: 先找該月第一天
        year = date.year
        month = date.month
        # 找第三個週三
        first_day = datetime(year, month, 1)
        wed_count = 0
        d = first_day
        while wed_count < 3:
            if d.weekday() == 2:  # 週三
                wed_count += 1
                if wed_count == 3:
                    settlement_dates.add(d.date())
            d += timedelta(days=1)

    return settlement_dates


def calc_indicators(df):
    """計算指標（同 v2）"""
    # 持股線
    df["amount"] = df["volume"] * (df["open"] + df["close"]) / 2
    df["vwap88"] = df["amount"].rolling(88).sum() / df["volume"].rolling(88).sum()
    df["sma17"] = df["close"].rolling(17).mean()
    df["holding_line"] = df["sma17"].rolling(2).max()
    df["reflect_line"] = 2 * df["sma17"] - df["holding_line"]
    df["holding_bull"] = df["reflect_line"] >= df["vwap88"]

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

    # CCI
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma_tp = tp.rolling(14).mean()
    mad = tp.rolling(14).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    df["cci"] = (tp - sma_tp) / (0.015 * mad)

    df.dropna(inplace=True)
    return df


# === 交易成本參數 ===
FEE_PER_TRADE = 2       # 手續費（點）每次單邊
SLIPPAGE = 1             # 滑價（點）每次單邊
ROLLOVER_COST = 10       # 轉倉價差平均（點）
POINT_VALUE = 200        # 台指期每點價值（元）


def backtest_with_settlement(df, strategy_name, entry_fn, exit_fn):
    """含結算轉倉的回測引擎"""
    settlement_dates = find_settlement_dates(df)
    position = 0
    entry_price = 0
    max_price = 0
    trades = []
    current_contract = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        today = row.name.date() if hasattr(row.name, "date") else row.name

        # === 結算日處理 ===
        if position == 1 and today in settlement_dates:
            # 結算日強制平倉 + 轉倉
            pnl_points = row["close"] - entry_price - (FEE_PER_TRADE + SLIPPAGE) * 2
            pnl_pct = pnl_points / entry_price * 100

            trades[-1].update({
                "exit_date": row.name,
                "exit_price": row["close"],
                "pnl": pnl_points,
                "pnl_pct": pnl_pct,
                "exit_signal": "結算轉倉",
            })

            # 立刻以新合約重新進場（轉倉）
            rollover_price = row["close"] + ROLLOVER_COST  # 正價差成本
            entry_price = rollover_price
            max_price = row["close"]
            trades.append({
                "type": "LONG(轉倉)",
                "entry_date": row.name,
                "entry_price": entry_price,
                "signal": "轉倉續持",
            })
            continue

        # === 進場 ===
        if position == 0:
            if entry_fn(row, prev, df, i):
                position = 1
                entry_price = row["close"] + SLIPPAGE + FEE_PER_TRADE
                max_price = row["close"]
                current_contract = row.get("contract", "")
                trades.append({
                    "type": "LONG",
                    "entry_date": row.name,
                    "entry_price": entry_price,
                    "signal": entry_fn.__doc__ or "進場",
                })

        # === 出場 ===
        elif position == 1:
            max_price = max(max_price, row["close"])
            pnl_pct = (row["close"] - entry_price) / entry_price * 100
            dd_from_peak = (row["close"] - max_price) / max_price * 100

            exit_sig = exit_fn(row, prev, df, i, pnl_pct, dd_from_peak)
            if exit_sig:
                pnl_points = row["close"] - entry_price - (FEE_PER_TRADE + SLIPPAGE)
                pnl_pct = pnl_points / entry_price * 100
                trades[-1].update({
                    "exit_date": row.name,
                    "exit_price": row["close"],
                    "pnl": pnl_points,
                    "pnl_pct": pnl_pct,
                    "exit_signal": exit_sig,
                })
                position = 0
                entry_price = 0
                max_price = 0

    # 回測結束平倉
    if position != 0 and trades and "exit_date" not in trades[-1]:
        pnl = df.iloc[-1]["close"] - entry_price - (FEE_PER_TRADE + SLIPPAGE)
        trades[-1].update({
            "exit_date": df.index[-1],
            "exit_price": df.iloc[-1]["close"],
            "pnl": pnl,
            "pnl_pct": pnl / entry_price * 100,
            "exit_signal": "回測結束平倉",
        })

    return trades


# === 策略定義 ===

def entry_balanced(row, prev, df, i):
    """持股線多方+MACD轉紅"""
    return (row["holding_bull"] and
            row["macd_str"] == 1 and prev["macd_str"] != 1)

def exit_balanced(row, prev, df, i, pnl_pct, dd_from_peak):
    if not row["holding_bull"] and prev["holding_bull"]:
        return "持股線翻空"
    # 連續弱勢3天
    weak = 0
    for j in range(3):
        if i - j >= 0 and df.iloc[i - j]["macd_str"] == -1:
            weak += 1
    if weak >= 3:
        return "連續弱勢3天"
    if dd_from_peak <= -7:
        return f"移動停損({dd_from_peak:.1f}%)"
    return None

def entry_conservative(row, prev, df, i):
    """持股線多方+MACD轉紅(保守)"""
    return (row["holding_bull"] and
            row["macd_str"] == 1 and prev["macd_str"] != 1)

def exit_conservative(row, prev, df, i, pnl_pct, dd_from_peak):
    if not row["holding_bull"] and prev["holding_bull"]:
        return "持股線翻空"
    if dd_from_peak <= -10:
        return f"移動停損({dd_from_peak:.1f}%)"
    return None

def entry_aggressive(row, prev, df, i):
    """多重進場(積極)"""
    if row["holding_bull"] and row["macd_str"] == 1 and prev["macd_str"] != 1:
        return True
    if (row["holding_bull"] and
        row["cci"] >= -200 and prev["cci"] < -200 and
        row["macd_str"] >= 0):
        return True
    if (row["holding_bull"] and not prev["holding_bull"] and
        row["macd_str"] >= 0):
        return True
    return False

def exit_aggressive(row, prev, df, i, pnl_pct, dd_from_peak):
    if not row["holding_bull"] and prev["holding_bull"]:
        return "持股線翻空"
    # 連續弱勢5天+已獲利
    weak = 0
    for j in range(5):
        if i - j >= 0 and df.iloc[i - j]["macd_str"] == -1:
            weak += 1
    if weak >= 5 and pnl_pct > 2:
        return "連續弱勢5天(保護利潤)"
    if dd_from_peak <= -8:
        return f"移動停損({dd_from_peak:.1f}%)"
    if row["cci"] > 200 and row["macd_str"] == -1:
        return "CCI過熱+MACD弱"
    return None


def print_report(trades, name):
    completed = [t for t in trades if "pnl" in t]
    # 排除轉倉中間交易，合併計算
    real_trades = [t for t in completed if t.get("exit_signal") != "結算轉倉"]
    rollover_count = len([t for t in completed if t.get("exit_signal") == "結算轉倉"])

    if not real_trades:
        print(f"\n{'='*60}\n策略: {name}\n無已完成交易")
        return

    wins = [t for t in real_trades if t["pnl"] > 0]
    losses = [t for t in real_trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in completed)  # 含轉倉損益
    total_pnl_money = total_pnl * POINT_VALUE
    avg_pnl_pct = np.mean([t["pnl_pct"] for t in real_trades])
    max_win = max(t["pnl_pct"] for t in real_trades)
    max_loss = min(t["pnl_pct"] for t in real_trades)
    win_rate = len(wins) / len(real_trades) * 100

    cum_pnl = np.cumsum([t["pnl"] for t in completed])
    peak = np.maximum.accumulate(cum_pnl)
    max_dd = (cum_pnl - peak).min()

    hold_days = []
    for t in real_trades:
        if "entry_date" in t and "exit_date" in t:
            hold_days.append((t["exit_date"] - t["entry_date"]).days)
    avg_hold = np.mean(hold_days) if hold_days else 0

    total_fee = len(completed) * (FEE_PER_TRADE + SLIPPAGE) * 2
    rollover_fee = rollover_count * ROLLOVER_COST

    print(f"\n{'='*60}")
    print(f"策略: {name}")
    print(f"{'='*60}")
    print(f"期間: {completed[0]['entry_date'].strftime('%Y-%m-%d')} ~ {completed[-1].get('exit_date', pd.Timestamp.now()).strftime('%Y-%m-%d')}")
    print(f"實際交易: {len(real_trades)}筆 | 轉倉: {rollover_count}次")
    print(f"勝率: {win_rate:.1f}% ({len(wins)}W/{len(losses)}L)")
    print(f"總損益: {total_pnl:+.0f}點 ({total_pnl_money:+,.0f}元)")
    print(f"平均每筆: {avg_pnl_pct:+.2f}%")
    print(f"最大獲利: {max_win:+.2f}% | 最大虧損: {max_loss:+.2f}%")
    print(f"最大回撤: {max_dd:.0f}點 ({max_dd * POINT_VALUE:,.0f}元)")
    print(f"平均持有: {avg_hold:.0f}天")
    print(f"總交易成本: {total_fee + rollover_fee:.0f}點 (手續費{total_fee:.0f} + 轉倉{rollover_fee:.0f})")

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
        yr = [t for t in yt if t.get("exit_signal") != "結算轉倉"]
        yw = len([t for t in yr if t["pnl"] > 0])
        yrc = len(yr) if yr else 1
        print(f"  {y}: {len(yr)}筆(+{len(yt)-len(yr)}轉倉), {yp:+.0f}點({yp*POINT_VALUE:+,.0f}元), 勝率{yw/yrc*100:.0f}%")

    # 出場原因
    print(f"\n--- 出場原因 ---")
    reasons = {}
    for t in completed:
        r = t.get("exit_signal", "?")
        if "停損" in r:
            k = "移動停損"
        elif "翻空" in r:
            k = "持股線翻空"
        elif "弱勢" in r:
            k = "連續弱勢"
        elif "轉倉" in r:
            k = "結算轉倉"
        elif "CCI" in r:
            k = "CCI過熱"
        elif "回測" in r:
            k = "回測結束"
        else:
            k = r
        reasons[k] = reasons.get(k, 0) + 1
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}次")

    # 最近交易
    print(f"\n--- 最近 5 筆（不含轉倉）---")
    for t in real_trades[-5:]:
        e = t["entry_date"].strftime("%Y/%m/%d")
        x = t.get("exit_date", pd.Timestamp.now()).strftime("%m/%d")
        print(f"  {e}→{x} | {t.get('signal','')[:20]} → {t.get('exit_signal','')[:20]} | {t['pnl']:+.0f}點 ({t['pnl_pct']:+.2f}%)")


def main():
    import os
    cache_file = "/Users/wei/Projects/invest-system/data/taifex_tx_daily.csv"

    if os.path.exists(cache_file):
        print(f"讀取快取: {cache_file}")
        df_raw = pd.read_csv(cache_file, dtype=str)
    else:
        print("從期交所下載台指期 5 年資料...")
        df_raw = fetch_taifex_futures(2021, 2026)
        # 確保所有欄位名稱去空白
        df_raw.columns = df_raw.columns.str.strip()
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        df_raw.to_csv(cache_file, index=False)
        print(f"已快取至 {cache_file}")

    print("處理期貨資料（取近月合約）...")
    df = process_futures_data(df_raw)
    print(f"日線資料: {len(df)} 筆 ({df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')})")

    print("計算指標...")
    df = calc_indicators(df)
    print(f"有效資料: {len(df)} 筆")

    print(f"\n{'='*60}")
    print(f"更生人策略 v3（台指期實際資料 + 結算轉倉 + 交易成本）")
    print(f"手續費: {FEE_PER_TRADE}點/單邊 | 滑價: {SLIPPAGE}點/單邊 | 轉倉成本: {ROLLOVER_COST}點")
    print(f"每點價值: {POINT_VALUE}元")

    t1 = backtest_with_settlement(df, "平衡版", entry_balanced, exit_balanced)
    print_report(t1, "④ 平衡版（持股線+MACD轉紅+弱勢3天出+停損7%）")

    t2 = backtest_with_settlement(df, "保守版", entry_conservative, exit_conservative)
    print_report(t2, "⑤ 保守版（持股線+MACD轉紅+持股線出場+停損10%）")

    t3 = backtest_with_settlement(df, "積極版", entry_aggressive, exit_aggressive)
    print_report(t3, "⑥ 積極版（多重進場+CCI+弱勢5天+停損8%）")

    # Buy & Hold
    first = df.iloc[0]["close"]
    last = df.iloc[-1]["close"]
    bh = (last - first) / first * 100
    bh_pts = last - first
    print(f"\n{'='*60}")
    print(f"📊 Buy & Hold: {first:.0f} → {last:.0f} ({bh:+.1f}%, {bh_pts:+,.0f}點, {bh_pts*POINT_VALUE:+,.0f}元)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
