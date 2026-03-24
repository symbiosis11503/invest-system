"""
策略測試腳本
使用合成 OHLCV 資料測試所有策略，不需要連接資料庫
"""
import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np

# 確保 strategies/ 目錄在 path 中（讓 from base import 能找到）
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import backtrader as bt
from base import BaseStrategy
from bollinger import BollingerStrategy
from ma_cross import MACrossStrategy
from rsi import RSIStrategy
from macd import MACDStrategy
from breakout import BreakoutStrategy
from ensemble import EnsembleStrategy


# ============================================
# 合成資料產生器
# ============================================

def make_data(n=500, seed=42, trend='mixed'):
    """
    產生帶趨勢的合成 OHLCV 資料
    trend: 'up' | 'down' | 'mixed'
    """
    np.random.seed(seed)
    dates = pd.date_range('2022-01-01', periods=n, freq='B')

    if trend == 'up':
        drift = 0.0008
    elif trend == 'down':
        drift = -0.0008
    else:
        # 前半段上漲，後半段震盪
        drifts = np.concatenate([
            np.full(n // 3, 0.001),
            np.full(n // 3, -0.0005),
            np.full(n - 2 * (n // 3), 0.0003),
        ])
        drift = drifts

    returns = np.random.normal(drift, 0.015, n)
    price = 100 * np.exp(np.cumsum(returns))

    noise = np.random.uniform(0.001, 0.02, n)
    high = price * (1 + noise)
    low = price * (1 - noise)
    open_ = price * (1 + np.random.uniform(-0.01, 0.01, n))
    volume = np.random.randint(1_000_000, 5_000_000, n)

    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': price,
        'volume': volume,
    }, index=dates)
    df.index.name = 'datetime'
    return df


# ============================================
# 回測執行器
# ============================================

def run_backtest(strategy_cls, df, cash=1_000_000, commission=0.001425,
                 strategy_kwargs=None):
    """執行單一策略回測，回傳結果 dict"""
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)

    data_feed = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data_feed)

    kwargs = strategy_kwargs or {}
    cerebro.addstrategy(strategy_cls, **kwargs)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        riskfreerate=0.02, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    final_value = cerebro.broker.getvalue()
    roi = (final_value - cash) / cash * 100

    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    dd = strat.analyzers.drawdown.get_analysis()
    max_dd = dd.get('max', {}).get('drawdown', 0)

    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('closed', 0)
    won = trade_analysis.get('won', {}).get('total', 0)
    win_rate = won / total_trades * 100 if total_trades > 0 else 0

    return {
        'final_value': final_value,
        'roi_pct': roi,
        'sharpe': sharpe,
        'max_drawdown_pct': max_dd,
        'total_trades': total_trades,
        'win_rate_pct': win_rate,
    }


# ============================================
# 測試所有策略
# ============================================

STRATEGIES = [
    ('MA 交叉',    MACrossStrategy,   {}),
    ('RSI',        RSIStrategy,       {}),
    ('布林通道',   BollingerStrategy, {}),
    ('MACD',       MACDStrategy,      {}),
    ('突破',       BreakoutStrategy,  {}),
    ('組合投票',   EnsembleStrategy,  {}),
]

SCENARIOS = [
    ('mixed（混合趨勢）', 'mixed', 42),
    ('up（上漲趨勢）',    'up',    99),
    ('down（下跌趨勢）',  'down',  7),
]


def run_all():
    print('=' * 72)
    print('  策略測試報告（合成資料，500 根 K 線，初始資金 100 萬）')
    print('=' * 72)

    all_ok = True

    for scenario_name, trend, seed in SCENARIOS:
        df = make_data(n=500, seed=seed, trend=trend)
        print(f'\n【場景：{scenario_name}】  資料: {df.index[0].date()} ~ {df.index[-1].date()}')
        print(f"  {'策略':<10} {'最終資產':>12} {'報酬率':>8} {'Sharpe':>8} "
              f"{'最大回撤':>10} {'交易次數':>8} {'勝率':>8}")
        print('  ' + '-' * 68)

        for name, cls, kwargs in STRATEGIES:
            try:
                r = run_backtest(cls, df, strategy_kwargs=kwargs)
                sharpe_str = f"{r['sharpe']:.2f}" if r['sharpe'] is not None else '  N/A'
                print(f"  {name:<10} "
                      f"{r['final_value']:>12,.0f} "
                      f"{r['roi_pct']:>+7.1f}% "
                      f"{sharpe_str:>8} "
                      f"{r['max_drawdown_pct']:>9.1f}% "
                      f"{r['total_trades']:>8} "
                      f"{r['win_rate_pct']:>7.1f}%")
            except Exception as e:
                print(f"  {name:<10}  ❌ 測試失敗: {e}")
                all_ok = False

    print('\n' + '=' * 72)
    if all_ok:
        print('  ✅ 所有策略測試通過（無例外）')
    else:
        print('  ❌ 部分策略測試失敗，請檢查上方錯誤訊息')
    print('=' * 72)
    return all_ok


if __name__ == '__main__':
    success = run_all()
    sys.exit(0 if success else 1)
