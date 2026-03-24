"""
RSI 策略 (Relative Strength Index)
RSI < 超賣線 → 買入
RSI > 超買線 → 賣出
"""
import backtrader as bt
from base import BaseStrategy


class RSIStrategy(BaseStrategy):
    params = (
        ('name', 'RSI'),
        ('rsi_period', 14),
        ('oversold', 30),     # 超賣線
        ('overbought', 70),   # 超買線
        ('size_pct', 0.9),
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.rsi < self.p.oversold:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            if self.rsi > self.p.overbought:
                self.order = self.close()
