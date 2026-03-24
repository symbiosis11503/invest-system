"""
突破策略 (Donchian Channel Breakout)
價格突破 N 日最高 → 買入
價格跌破 M 日最低 → 賣出
"""
import backtrader as bt
from base import BaseStrategy


class BreakoutStrategy(BaseStrategy):
    params = (
        ('name', '突破'),
        ('entry_period', 20),  # 進場通道期數
        ('exit_period', 10),   # 出場通道期數
        ('size_pct', 0.9),     # 每次下單用 90% 資金
    )

    def __init__(self):
        super().__init__()
        self.highest = bt.indicators.Highest(
            self.data.high, period=self.p.entry_period
        )
        self.lowest = bt.indicators.Lowest(
            self.data.low, period=self.p.exit_period
        )

    def next(self):
        if self.order:
            return

        if not self.position:
            # 沒持倉：價格突破 N 日最高 → 買
            if self.data.close[0] > self.highest[-1]:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 有持倉：價格跌破 M 日最低 → 賣
            if self.data.close[0] < self.lowest[-1]:
                self.order = self.close()
