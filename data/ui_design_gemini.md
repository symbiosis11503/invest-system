好的，身為專精金融看盤軟體的頂級 UI/UX 設計師，我將為您規劃這 6 個頁面的設計。

我的設計哲學是「資訊密度與清晰度的平衡」。金融使用者需要快速獲取大量資訊，但介面不能混亂。我們將借鑒 TradingView 的專業圖表、Fugle 的在地化親和力，以及 Yahoo Finance 的資訊組織能力，並融入您提供的現代化設計規範。

---

### **通用元件與設計系統**

在進入頁面設計前，我們先確立全站的基礎。

#### **1. CSS 變數 (Design Tokens)**

這將是我們設計系統的核心，確保全站風格統一。

```css
:root {
  /* Colors */
  --background: #09090b;
  --card-bg: #121218;
  --border-color: rgba(255, 255, 255, 0.1);
  --text-primary: #f8fafc;
  --text-secondary: #a1a1aa;
  --text-tertiary: #71717a;

  --accent-indigo: #6366f1;
  --accent-cyan: #06b6d4;
  --price-up: #ef4444;      /* 台股漲 */
  --price-down: #22c55e;    /* 台股跌 */
  --price-neutral: #a1a1aa;

  /* Typography */
  --font-sans: 'Inter', sans-serif;
  --font-mono: 'JetBrains Mono', monospace;

  /* Sizing & Radius */
  --radius-card: 12px;
  --radius-button: 8px;
  --spacing-unit: 4px; /* 基礎間距單位 */
}
```

#### **2. 通用頂部導航列 (Desktop)**

- **HTML 結構**:
    ```html
    <header class="main-header">
      <div class="logo">QuantSys</div>
      <nav class="main-nav">
        <a href="/" class="nav-link active">儀表板</a>
        <a href="/trading" class="nav-link">策略監控</a>
        <a href="/intelligence" class="nav-link">市場情報</a>
        <a href="/backtests" class="nav-link">回測結果</a>
        <a href="/messages" class="nav-link">群組監聽</a>
        <a href="/chipdata" class="nav-link">籌碼分析</a>
      </nav>
      <div class="header-actions">
        <div class="search-bar">...</div>
        <button class="icon-button" id="notifications">
          <!-- SVG Icon for bell -->
        </button>
        <div class="user-profile">...</div>
      </div>
    </header>
    ```
- **互動設計**:
    - `nav-link.active` 會有底部 highlight (使用 `--accent-indigo`)。
    - 搜尋框點擊後會展開，並提供熱門商品建議。

#### **3. 手機版底部 Tab Bar**

- **HTML 結構**:
    ```html
    <nav class="mobile-tab-bar">
      <a href="/" class="tab-item active">儀表板</a>
      <a href="/trading" class="tab-item">監控</a>
      <a href="/intelligence" class="tab-item">情報</a>
      <a href="/backtests" class="tab-item">回測</a>
      <a href="/messages" class="tab-item">群組</a>
    </nav>
    ```
- **策略**:
    - 僅保留最重要的 5 個頁面連結。`籌碼分析` 可從`策略監控`頁面中的商品詳情進入。
    - 當頁面向上滾動時，Tab Bar 可選擇性隱藏，以提供更多內容空間。

---

### **頁面設計詳解**

#### **1. 首頁儀表板 (/)**

**目標：讓使用者在 30 秒內掌握市場全局。**

1.  **HTML 結構描述**:
    ```html
    <main class="dashboard-grid">
      <!-- 2x2 大卡片區塊 -->
      <div class="card market-overview-card large">...</div>
      <div class="card market-sentiment-card">...</div>
      <div class="card institutional-flow-card">...</div>
      
      <!-- 1x2 小卡片區塊 -->
      <div class="card top-strategies-card">...</div>
      <div class="card latest-news-card">...</div>
    </main>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: calc(var(--spacing-unit) * 6);
    }
    .market-overview-card { grid-column: span 3; } /* 市場總覽橫跨三欄 */
    .market-sentiment-card { grid-column: span 1; }
    .institutional-flow-card { grid-column: span 2; }
    .top-strategies-card { grid-column: span 2; }
    .latest-news-card { grid-column: span 1; }
    
    .card {
      background: var(--card-bg);
      border-radius: var(--radius-card);
      border: 1px solid var(--border-color);
      padding: calc(var(--spacing-unit) * 6);
    }
    .price-up { color: var(--price-up); }
    .price-down { color: var(--price-down); }
    ```

3.  **重要的互動設計**:
    - **市場總覽卡片**: Hover 指數卡片時，會顯示一個迷你的 Sparkline 圖表，呈現 24 小時趨勢。
    - **市場情緒**: 圓環圖的指針會根據即時情緒分數平滑移動。趨勢箭頭（紅/綠）清晰表示情緒變化。
    - **卡片點擊**: 任何卡片的標題或「查看更多」按鈕都可點擊，跳轉到對應的詳細頁面（例如：點擊新聞摘要跳轉到 `/intelligence`）。

4.  **行動版適配策略**:
    - 使用 CSS Grid 的 `grid-template-columns: 1fr;`，讓所有卡片垂直堆疊成單欄佈局。
    - 優先顯示「市場總覽」和「市場情緒」，其次是新聞摘要。其他資訊可預設摺疊。

---

#### **2. 策略監控 (/trading)**

**目標：提供專業、無干擾的圖表分析與交易執行環境。**

1.  **HTML 結構描述**:
    ```html
    <div class="trading-layout">
      <main class="chart-panel">
        <div class="chart-header">
          <div class="product-selector">...</div>
          <div class="timeframe-selector">...</div>
          <div class="indicator-controls">...</div>
        </div>
        <div id="tradingview-chart-container"></div>
      </main>
      <aside class="info-sidebar">
        <div class="card performance-metrics">...</div>
        <div class="card recent-trades">...</div>
      </aside>
    </div>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .trading-layout { display: flex; gap: calc(var(--spacing-unit) * 6); }
    .chart-panel { flex-grow: 1; }
    .info-sidebar { width: 320px; flex-shrink: 0; }
    #tradingview-chart-container { height: 600px; /* 或動態計算 */ }
    
    .product-selector input {
      background: transparent;
      border: 1px solid var(--border-color);
      /* ... */
    }
    ```

3.  **重要的互動設計**:
    - **商品選擇器**: 輸入時觸發 API 進行模糊搜尋，下拉列表中顯示商品代碼和中文名稱。使用 `JetBrains Mono` 顯示代碼，`Inter` 顯示名稱。
    - **交易訊號標記**: K 線圖上的買賣訊號（例如一個 ▲ 或 ▼）可以點擊，下方「最近交易紀錄」表格中對應的交易會高亮顯示。
    - **可拖曳側邊欄**: `info-sidebar` 和 `chart-panel` 之間的分隔線可以左右拖曳，調整寬度。

4.  **行動版適配策略**:
    - 隱藏右側 `info-sidebar`。
    - 圖表下緣新增一個抽屜式拉環（Handle），向上滑動可以拉出「績效指標」和「最近交易」面板（Bottom Sheet）。
    - 圖表工具列簡化，將不常用的功能收納到「更多」選單中。

---

#### **3. 市場情報 (/intelligence)**

**目標：將雜亂的新聞轉化為可操作的市場洞察。**

1.  **HTML 結構描述**:
    ```html
    <main class="intelligence-page">
      <div class="card sentiment-trend-chart">...</div>
      <div class="filters-bar">
        <!-- Keyword Search, Sentiment Dropdown, Source Selector -->
      </div>
      <div class="news-waterfall">
        <article class="news-card">
          <header>
            <h3>新聞標題...</h3>
            <span class="sentiment-tag positive">看多</span>
          </header>
          <p class="summary">新聞摘要...</p>
          <footer class="ai-analysis">
            <span class="ai-reason-label">AI 分析：</span>
            <span>偵測到「營收創高」、「訂單滿載」等正面詞彙。</span>
          </footer>
        </article>
        <!-- more news-card -->
      </div>
    </main>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .news-waterfall {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
      gap: calc(var(--spacing-unit) * 5);
    }
    .sentiment-tag {
      padding: 4px 8px;
      border-radius: var(--radius-button);
      font-size: 12px;
    }
    .sentiment-tag.positive { background-color: rgba(239, 68, 68, 0.2); color: var(--price-up); }
    .sentiment-tag.negative { background-color: rgba(34, 197, 94, 0.2); color: var(--price-down); }
    ```

3.  **重要的互動設計**:
    - **篩選器**: 篩選器變動時，新聞瀑布流會以淡入淡出效果非同步更新內容，無需刷新頁面。
    - **無限滾動**: 滾動到頁面底部時，自動載入更多新聞。
    - **AI 分析展開**: 預設只顯示一行 AI 分析理由，點擊後可展開顯示更詳細的分析，如關鍵詞權重、情緒分數等。

4.  **行動版適配策略**:
    - 瀑布流 (`news-waterfall`) 的 `grid-template-columns` 改為 `1fr`，呈現單欄佈局。
    - 篩選器區域折疊成一個「篩選」按鈕，點擊後以全螢幕 Modal 或 Bottom Sheet 形式呈現篩選選項。

---

#### **4. 回測結果 (/backtests)**

**目標：直觀比較策略表現，快速找到金礦。**

1.  **HTML 結構描述**:
    ```html
    <main class="backtests-page">
      <div class="card">
        <h2>策略比較矩陣</h2>
        <div class="strategy-matrix">...</div>
      </div>
      <div class="card">
        <h2>最佳策略 Top 10</h2>
        <ul class="top-list">...</ul>
      </div>
      <div class="card">
        <h2>詳細回測數據</h2>
        <table class="results-table">...</table>
        <!-- Equity Curve Chart container (initially hidden) -->
        <div id="equity-curve-modal" class="modal">...</div>
      </div>
    </main>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .strategy-matrix {
      display: grid;
      /* JS 會動態設定 grid-template-columns/rows */
      gap: 2px;
    }
    .matrix-cell {
      padding: 8px;
      text-align: center;
      font-family: var(--font-mono);
      /* JS 會根據報酬率設定背景色 */
    }
    .results-table th.sortable:hover { cursor: pointer; color: var(--accent-cyan); }
    ```

3.  **重要的互動設計**:
    - **矩陣熱力圖**: 矩陣中的格子根據報酬率高低，以不同深淺的紅/綠色作為背景，形成熱力圖效果，一目了然。
    - **互動式表格**: 點擊表格標頭（如「年化報酬」、「MDD」）可以對數據進行排序。
    - **點擊顯示圖表**: 點擊矩陣中的任一格子或表格中的任一列，會以 Modal 彈窗形式顯示該次回測的詳細權益曲線圖。

4.  **行動版適配策略**:
    - **策略比較矩陣不適用於手機**。改為兩個下拉式選單（一個選策略，一個選商品），讓使用者手動選擇進行一對一比較。
    - 詳細數據表格 (`results-table`) 允許水平滾動，以查看所有欄位。

---

#### **5. 群組監聽 (/messages)**

**目標：打造一個高效、即時的投資者交流社群。**

1.  **HTML 結構描述**:
    ```html
    <div class="chat-layout">
      <aside class="channel-list">
        <!-- List of groups/channels -->
      </aside>
      <main class="message-view">
        <header class="channel-header">...</header>
        <div class="message-stream">
          <!-- Messages here -->
        </div>
        <form class="message-input-form">
          <input type="text" placeholder="輸入訊息..." />
        </form>
      </main>
      <aside class="context-panel">
        <div class="card tag-cloud">...</div>
        <!-- Pinned messages, etc. -->
      </aside>
    </div>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .chat-layout { display: grid; grid-template-columns: 240px 1fr 280px; height: 100vh; }
    .message-stream { overflow-y: auto; padding: 20px; }
    .message { display: flex; gap: 12px; margin-bottom: 16px; }
    .message .author { font-weight: 600; color: var(--accent-cyan); }
    .tag-cloud a {
      display: inline-block;
      margin: 4px;
      padding: 4px 10px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      font-size: 13px;
    }
    ```

3.  **重要的互動設計**:
    - **即時訊息**: 使用 WebSocket，新訊息會自動推送到 `message-stream` 底部，並有平滑的滾動效果。
    - **提及 (@mention)**: 輸入 `@` 會觸發使用者列表，方便提及他人。被提及的訊息對該使用者會有特殊高亮。
    - **熱門關鍵字**: Tag cloud 中的關鍵字（如 $TSMC, #AI）可以點擊，會自動將該關鍵字填入搜尋框並執行搜尋。

4.  **行動版適配策略**:
    - 採用單欄佈局，只顯示 `message-view`。
    - `channel-list` 和 `context-panel` 分別收納到左上角的漢堡選單和右上角的功能選單中，點擊後以側滑抽屜形式出現。

---

#### **6. 籌碼分析 (/chipdata)**

**目標：將複雜的籌碼數據以最易懂的圖表呈現。**

1.  **HTML 結構描述**:
    ```html
    <main class="chip-data-page">
      <header class="page-header">
        <h1>籌碼分析</h1>
        <div class="product-selector-large">...</div>
      </header>
      <div class="chip-data-grid">
        <div class="card chart-card">
          <h2>三大法人買賣超</h2>
          <div id="institutional-chart"></div>
        </div>
        <div class="card chart-card">
          <h2>融資融券餘額</h2>
          <div id="margin-chart"></div>
        </div>
        <div class="card kpi-card">
          <h2>關鍵指標</h2>
          <div class="kpi-grid">
            <!-- PER, PBR, Yield items -->
          </div>
        </div>
        <div class="card chart-card">
          <h2>月營收成長趨勢</h2>
          <div id="revenue-chart"></div>
        </div>
      </div>
    </main>
    ```

2.  **CSS 關鍵樣式**:
    ```css
    .chip-data-grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: calc(var(--spacing-unit) * 6);
    }
    .chart-card { grid-column: span 1; }
    .kpi-card { grid-column: span 1; grid-row: span 2; } /* KPI卡片佔兩格高 */
    .institutional-chart-card { grid-column: span 2; } /* 法人圖橫跨兩欄 */

    /* 調整佈局讓法人圖在最上方 */
    .chip-data-grid { grid-template-columns: repeat(2, 1fr); }
    .institutional-chart { grid-column: 1 / 3; }
    ```
    *（註：以上 CSS Grid 佈局可依視覺優先級調整，此處提供一種範例）*

3.  **重要的互動設計**:
    - **圖表連動**: 圖表具備 Tooltip，當滑鼠懸停在某個時間點時，所有圖表可以選擇性地同步顯示該時間點的數據。
    - **法人圖表切換**: 在「三大法人買賣超」圖表中，可以點擊圖例（外資/投信/自營）來顯示或隱藏對應的數據系列。
    - **指標儀表板**: PER/PBR 等指標，除了數字外，旁邊可搭配一個簡單的量表（Gauge），顯示其在歷史區間的相對位置（高/中/低）。

4.  **行動版適配策略**:
    - Grid 佈局改為單欄垂直堆疊。
    - 商品選擇器固定在頁面頂部。
    - 圖表預設顯示較短的時間區間，並提供時間範圍切換按鈕（如：近3月/近1年/近3年）。

---

### **總結**

此設計方案的核心是建立一個一致、可擴展的設計系統。深色主題和強調色的使用創造了專業感，而清晰的版面配置和周到的互動設計則確保了在處理複雜金融數據時的使用者體驗。從儀表板的宏觀概覽到策略監控的微觀操作，再到情報和籌碼的深度分析，每個頁面都有其明確的目標和為之服務的設計策略，並充分考慮了桌面和行動裝置的差異性，確保在任何情境下都能高效運作。