"""
MACD 策略 (Moving Average Convergence Divergence)
MACD 線上穿信號線 → 買入
MACD 線下穿信號線 → 賣出
"""
import backtrader as bt
from base import BaseStrategy


class MACDStrategy(BaseStrategy):
    params = (
        ('name', 'MACD'),
        ('fast', 12),          # 快線期數
        ('slow', 26),          # 慢線期數
        ('signal', 9),         # 信號線期數
        ('size_pct', 0.9),     # 每次下單用 90% 資金
    )

    def __init__(self):
        super().__init__()
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.fast,
            period_me2=self.p.slow,
            period_signal=self.p.signal,
        )
        self.crossover = bt.indicators.CrossOver(
            self.macd.macd, self.macd.signal
        )

    def next(self):
        if self.order:
            return

        if not self.position:
            # 沒持倉：MACD 上穿信號線 → 買
            if self.crossover > 0:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 有持倉：MACD 下穿信號線 → 賣
            if self.crossover < 0:
                self.order = self.close()
