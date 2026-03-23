# 投資系統 UI 重新設計 — Gemini Pro 提示

## 目標
重新設計投資系統的 6 個頁面 UI，參考 TradingView/Fugle 等專業看盤軟體，去蕪存菁。

## 現有系統
- Flask Web App，6 個頁面
- 深色主題，自建 Canvas K 線圖
- 849 萬筆行情 / 2,030 商品 / 7,700+ 新聞
- API 驅動（10 個 REST 端點）

## 6 個頁面
1. / — 投資儀表板（市場情緒+法人動向+回測摘要）
2. /trading — 策略監控（K 線圖+交易訊號+績效）
3. /intelligence — 市場情報（新聞列表+情緒分析）
4. /backtests — 回測結果（策略比較表格）
5. /messages — 群組監聽（TG 訊息流）
6. /chipdata — 籌碼分析（法人/融資/PER/營收）

## 設計要求
- 深色主題（#09090b 背景）
- 台股慣例：紅漲綠跌
- 統一導航列（頂部或側邊）
- 手機 RWD
- 資訊密度高但不雜亂
- 參考 TradingView 的簡潔專業感
- 用 Symbiosis Design System (SKILL.md) 的色彩和字型

## 需要的輸出
每個頁面的：
1. 佈局結構（wireframe 描述）
2. 主要元件配置
3. 色彩應用
4. 互動設計
5. 行動版適配
