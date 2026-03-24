"""
組合策略（Ensemble / Voting）
多個子策略同時運算，依投票結果決定進出場
- 多數策略看多 → 買
- 多數策略看空 → 賣
- 可設定門檻（例如至少 3/5 看多才買）
"""
import backtrader as bt
from base import BaseStrategy


class EnsembleStrategy(BaseStrategy):
    params = (
        ('name', '組合投票'),
        ('size_pct', 0.9),
        ('threshold', 0.6),      # 投票門檻（0.6 = 至少 60% 看多才買）
        # MA Cross 參數
        ('ma_fast', 13),
        ('ma_slow', 60),
        # RSI 參數
        ('rsi_period', 7),
        ('rsi_oversold', 30),
        ('rsi_overbought', 80),
        # Bollinger 參數
        ('bb_period', 15),
        ('bb_dev', 2.5),
        # MACD 參數
        ('macd_fast', 12),
        ('macd_slow', 30),
        ('macd_signal', 13),
        # Breakout 參數
        ('bo_entry', 10),
        ('bo_exit', 15),
    )

    def __init__(self):
        super().__init__()

        # --- 子策略指標 ---

        # 1. MA Cross
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.ma_fast)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.ma_slow)

        # 2. RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

        # 3. Bollinger Bands
        self.bb = bt.indicators.BollingerBands(
            self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev
        )

        # 4. MACD
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )

        # 5. Breakout (Donchian)
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.bo_entry)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.bo_exit)

    def _get_votes(self):
        """
        收集 5 個子策略的投票
        回傳: (buy_votes, sell_votes, total)
        """
        buy = 0
        sell = 0

        # 1. MA Cross: fast > slow = bullish
        if self.ma_fast[0] > self.ma_slow[0]:
            buy += 1
        elif self.ma_fast[0] < self.ma_slow[0]:
            sell += 1

        # 2. RSI: < oversold = bullish, > overbought = bearish
        if self.rsi[0] < self.p.rsi_oversold:
            buy += 1
        elif self.rsi[0] > self.p.rsi_overbought:
            sell += 1

        # 3. Bollinger: below lower = bullish, above upper = bearish
        if self.data.close[0] < self.bb.lines.bot[0]:
            buy += 1
        elif self.data.close[0] > self.bb.lines.top[0]:
            sell += 1

        # 4. MACD: macd > signal = bullish
        if self.macd.macd[0] > self.macd.signal[0]:
            buy += 1
        elif self.macd.macd[0] < self.macd.signal[0]:
            sell += 1

        # 5. Breakout: new high = bullish, new low = bearish
        if len(self.data) > 1:
            if self.data.close[0] > self.highest[-1]:
                buy += 1
            elif self.data.close[0] < self.lowest[-1]:
                sell += 1

        total = buy + sell
        return buy, sell, total

    def next(self):
        if self.order:
            return

        buy_votes, sell_votes, total = self._get_votes()

        if total == 0:
            return

        buy_ratio = buy_votes / 5  # 固定除以 5 個策略
        sell_ratio = sell_votes / 5

        if not self.position:
            # 沒持倉：買入條件
            if buy_ratio >= self.p.threshold:
                size = int(self.broker.getcash() * self.p.size_pct / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
                    self.log(f'投票買入 (多{buy_votes}/空{sell_votes})')
        else:
            # 有持倉：賣出條件
            if sell_ratio >= self.p.threshold:
                self.order = self.close()
                self.log(f'投票賣出 (多{buy_votes}/空{sell_votes})')
