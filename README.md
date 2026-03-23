# Invest System 台股 AI 投資分析系統

> 台灣第一個開源台股 AI 投資分析系統 — 849 萬筆資料、2,030 商品、AI 情緒分析、六頁深色儀表板

## 特色

- **全量台股覆蓋** — 上市 + 上櫃 + 興櫃 + ETF 共 1,963 支，加 67 國際商品
- **849 萬筆歷史資料** — 台股/台期/美股/黃金/原油/加密/外匯
- **AI 新聞情緒分析** — 7,500+ 則新聞，Groq + Gemini 雙引擎
- **TWSE OpenAPI 整合** — PER/PBR/殖利率/季度 EPS/月營收，每日自動更新
- **籌碼分析** — 法人買賣超、融資融券、營收連成長、籌碼洗淨訊號
- **六頁深色主題 UI** — 儀表板/策略監控/市場情報/回測/群組監聽/籌碼分析
- **零成本** — 所有資料來源免費

## 截圖

> 儀表板：市場總覽、法人 Top Buy/Sell、策略排行、情緒分析

## 快速開始

```bash
# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 下載全量台股資料（約 30 分鐘）
python batch_download_all.py

# 抓取 TWSE 開放資料（PER/EPS/月營收）
python data/twse_fetcher.py

# 收集新聞 + AI 分析
python intelligence.py
python intelligence.py --mood   # 查看市場情緒

# 啟動 Web 儀表板
python webapp.py                # http://localhost:18900
```

## 資料規模

| 類別 | 數量 | 說明 |
|------|------|------|
| 台股 + ETF | 1,963 支 | 上市/上櫃/興櫃全覆蓋 |
| 國際商品 | 67 個 | 期貨/指數/外匯/加密 |
| 歷史行情 | 849 萬筆 | 1998 年起 |
| AI 分析新聞 | 7,500+ 則 | Groq + Gemini |
| PER/PBR | 1,067 檔 | TWSE OpenAPI 每日更新 |
| 季度 EPS | 936 檔 | 最新 2025Q4 |
| 月營收 | 1,069 檔 | YoY/MoM |
| 法人籌碼 | 9,597 筆 | 外資/投信/自營 |

## 六頁儀表板

| 頁面 | 路徑 | 功能 |
|------|------|------|
| 儀表板 | `/` | 市場總覽、法人 Top Buy/Sell、情緒環、策略排行 |
| 策略監控 | `/trading` | K 線圖、即時報價、技術指標 |
| 市場情報 | `/intelligence` | AI 情緒分析、看多/看空/中性過濾 |
| 回測結果 | `/backtests` | 策略績效比較、排序篩選 |
| 群組監聽 | `/messages` | Telegram 群組訊息監控 |
| 籌碼分析 | `/chipdata` | 法人/融資券/月營收/EPS/本益比 |

## 策略引擎

內建 6 個策略，可自訂新增：

| 策略 | 說明 | 最佳績效 |
|------|------|---------|
| ma_cross | 均線交叉 (MA5/MA20) | 黃金 +76.7% |
| rsi | RSI 超買超賣 | |
| bollinger | 布林通道 | |
| macd | MACD 交叉 | |
| breakout | Donchian 突破 | 黃金 +62.1% |
| ensemble | 組合投票 | +80.7% |

```bash
# 回測範例
python backtest.py ma_cross --symbol GC=F --source yfinance --period 2y
python backtest.py ensemble --symbol 2330.TW --source yfinance
```

## 智慧指標

| 指標 | 說明 | 來源 |
|------|------|------|
| 年化 EPS | 近 4 季 EPS 合計 | TWSE OpenAPI |
| 法人連買天數 | 三大法人連續淨買超 | FinMind |
| 營收連成長月數 | 月營收 YoY 連續正成長 | TWSE OpenAPI |
| 籌碼洗淨訊號 | 融資遞減 + 股價上漲 | FinMind + 行情 |
| VIX 恐慌篩選 | VIX>30 時找低 PER 高殖利率 | yfinance + TWSE |

## API 端點

| 端點 | 說明 |
|------|------|
| `GET /api/market/<symbol>` | 個股行情 |
| `GET /api/backtests` | 回測結果 |
| `GET /api/intelligence` | AI 分析新聞 |
| `GET /api/mood` | 市場情緒 |
| `GET /api/chipdata/<symbol>` | 個股籌碼面 |
| `GET /api/top-flow` | 法人買賣超 Top 10 |
| `GET /api/eps-leaders` | EPS 排行 Top 20 |
| `GET /api/screener/vix-panic` | VIX 恐慌篩選 |
| `GET /health` | 系統健康檢查 |

## 資料來源（全部免費）

| 來源 | 資料 | 方式 |
|------|------|------|
| TWSE OpenAPI | PER/PBR/殖利率/EPS/月營收/公告 | REST JSON |
| 證交所 TWSE | 上市個股行情 | yfinance |
| 櫃買中心 TPEx | 上櫃/興櫃行情 | yfinance |
| 期交所 TAIFEX | 台灣期貨 | 官網 CSV |
| yfinance | 國際市場 | Python API |
| FinMind | 法人/融資券/營收 | REST API |
| Google News | 財經新聞 RSS | RSS XML |
| Groq + Gemini | AI 情緒分析 | API |

## 技術架構

```
invest-system/
├── webapp.py              # Flask Web App (port 18900)
├── backtest.py            # Backtrader 回測引擎
├── intelligence.py        # 新聞收集 + AI 分析
├── daily_report.py        # 每日市場報告
├── data/
│   ├── fetcher.py         # 台股/期貨/國際下載器
│   ├── finmind.py         # FinMind 籌碼下載器
│   └── twse_fetcher.py    # TWSE OpenAPI (PER/EPS/營收)
├── templates/             # 六頁 HTML 儀表板
├── static/
│   └── invest-base.css    # 設計系統
├── strategies/            # 6 個回測策略
├── scripts/
│   └── daily_update.sh    # 每日自動更新排程
└── db/trades.db           # SQLite 資料庫
```

## 自動化

- **每日 14:35** — launchd 自動更新行情 + 籌碼 + TWSE 指標 + 新聞
- **webapp** — launchd 服務，開機自啟 + 掛掉重啟

## 環境需求

- Python 3.10+
- macOS / Linux
- 依賴：flask, backtrader, yfinance, pandas, numpy, requests

## License

MIT

---

Built with [Symbiosis](https://github.com/symbiosis11503) — AI 與人的智慧共同體
