# 歷史模式比對功能規格

## 需求
參考越南股市 AI 助理的做法：「類似結構在過去出現時，反彈機率不低」

## 功能
給定一個股票代號，分析目前技術面結構（RSI/MA/Volume），
在歷史資料中搜尋類似的模式，計算之後的走勢機率。

## 輸入
- symbol: 股票代號
- lookback: 回看天數（預設 20）
- match_threshold: 相似度閾值（預設 0.8）

## 輸出
```json
{
  "symbol": "2330.TW",
  "current_pattern": {
    "rsi_14": 28.5,
    "ma5_vs_ma20": "below",
    "volume_trend": "decreasing",
    "description": "RSI 超賣 + 短均線下穿 + 量縮"
  },
  "similar_patterns": [
    {
      "date": "2024-08-05",
      "similarity": 0.92,
      "after_5d_return": 3.2,
      "after_10d_return": 5.8,
      "after_20d_return": 8.1
    }
  ],
  "probability": {
    "bounce_5d": 72,
    "bounce_10d": 68,
    "bounce_20d": 65
  },
  "summary": "過去 3 年出現 12 次類似結構，72% 在 5 日內反彈"
}
```

## 技術
- 用 market_data 表的歷史 OHLCV
- RSI/MA/Volume 標準化後計算歐式距離
- 前 N 個最相似的模式取平均報酬

## 優先級
中 — 等核心功能穩定後再做
