"""
均線交叉策略 (Moving Average Crossover)
短均線上穿長均線 → 買入
短均線下穿長均線 → 賣出
"""
import backtrader as bt
from base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    params = (
        ('name', 'MA交叉'),
        ('fast_period', 5),    # 短均線
        ('slow_period', 20),   # 長均線
        ('size_pct', 0.9),     # 每次下單用 90% 資金
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.order:
            return

        if not self.position:
            # 沒持倉：短均上穿長均 → 買
            if self.crossover > 0:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 有持倉：短均下穿長均 → 賣
            if self.crossover < 0:
                self.order = self.close()
