"""
布林通道策略 (Bollinger Bands)
價格跌破下軌 → 買入
價格突破上軌 → 賣出
"""
import backtrader as bt
from base import BaseStrategy


class BollingerStrategy(BaseStrategy):
    params = (
        ('name', '布林通道'),
        ('period', 20),        # 均線期數
        ('devfactor', 2),      # 標準差倍數
        ('size_pct', 0.9),     # 每次下單用 90% 資金
    )

    def __init__(self):
        super().__init__()
        self.boll = bt.indicators.BollingerBands(
            self.data.close, period=self.p.period, devfactor=self.p.devfactor
        )

    def next(self):
        if self.order:
            return

        if not self.position:
            # 沒持倉：價格跌破下軌 → 買
            if self.data.close[0] < self.boll.lines.bot[0]:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 有持倉：價格突破上軌 → 賣
            if self.data.close[0] > self.boll.lines.top[0]:
                self.order = self.close()
