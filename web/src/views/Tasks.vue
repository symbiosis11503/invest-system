<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'

interface Task {
  id: string; name: string; status: 'running' | 'done' | 'error'
  created_at: string; finished_at: string | null; result: string | null; error: string | null
}
interface Strategy { name: string; param_grid: Record<string, number[]>; combinations: number }

// ── State ─────────────────────────────────────────────────────
const tasks      = ref<Task[]>([])
const strategies = ref<Strategy[]>([])
const activeTab  = ref('backtest')
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── Forms ─────────────────────────────────────────────────────
const btForm = ref({
  strategy: 'ma_cross', symbol: 'GC=F', source: 'yfinance',
  period: '1y', start_date: '', end_date: '', cash: ''
})
const optForm = ref({
  strategy: 'ma_cross', symbol: 'GC=F', source: 'yfinance',
  period: '2y', start_date: '', end_date: '', cash: '', top_n: '10'
})
const dlForm = ref({
  source: 'yfinance', symbol: 'GC=F',
  period: '1y', start_date: '', end_date: ''
})
const intelForm = ref({ keywords: '' })
const xForm     = ref({ topics: '' })
const thForm    = ref({ username: '' })
const reportForm = ref({ send_telegram: false })

const tabs = [
  { id: 'backtest',    label: '回測' },
  { id: 'optimizer',  label: '參數優化' },
  { id: 'download',   label: '資料下載' },
  { id: 'intelligence', label: '情報收集' },
  { id: 'x',          label: 'X 輿情' },
  { id: 'threads',    label: 'Threads' },
  { id: 'report',     label: '每日報告' },
]

// ── API ───────────────────────────────────────────────────────
async function loadTasks() {
  try {
    const data = await fetch('/api/tasks').then(r => r.json())
    tasks.value = data
  } catch {}
}

async function loadStrategies() {
  try {
    const data = await fetch('/api/strategies').then(r => r.json())
    strategies.value = data
  } catch {}
}

async function post(url: string, body: object) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  await loadTasks()
  return data
}

async function runBacktest() {
  const b = btForm.value
  await post('/api/run/backtest', {
    strategy: b.strategy, symbol: b.symbol.trim(), source: b.source,
    period: b.period, start_date: b.start_date || null, end_date: b.end_date || null,
    cash: b.cash ? parseFloat(b.cash) : null,
  })
}

async function runOptimizer() {
  const o = optForm.value
  await post('/api/run/optimize', {
    strategy: o.strategy, symbol: o.symbol.trim(), source: o.source,
    period: o.period, start_date: o.start_date || null, end_date: o.end_date || null,
    cash: o.cash ? parseFloat(o.cash) : null, top_n: parseInt(o.top_n) || 10,
  })
}

async function runDownload() {
  const d = dlForm.value
  await post('/api/run/download', {
    source: d.source, symbol: d.symbol.trim(), period: d.period,
    start_date: d.start_date || null, end_date: d.end_date || null,
  })
}

async function runIntelligence() {
  const kw = intelForm.value.keywords.trim()
  await post('/api/run/intelligence', {
    keywords: kw ? kw.split(',').map(s => s.trim()).filter(Boolean) : null,
  })
}

async function runXMonitor() {
  const t = xForm.value.topics.trim()
  await post('/api/run/x-monitor', {
    topics: t ? t.split(',').map(s => s.trim()).filter(Boolean) : null,
  })
}

async function runThreads() {
  await post('/api/run/threads', { username: thForm.value.username.trim() || null })
}

async function runReport() {
  await post('/api/run/report', { send_telegram: reportForm.value.send_telegram })
}

// ── Helpers ───────────────────────────────────────────────────
const runningCount = computed(() => tasks.value.filter(t => t.status === 'running').length)
const sourcesForDl = computed(() => {
  const s = dlForm.value.source
  return s === 'yfinance'
})

function statusClass(s: string) {
  return s === 'done' ? 'status-done' : s === 'error' ? 'status-error' : 'status-running'
}
function statusLabel(s: string) {
  return s === 'done' ? 'DONE' : s === 'error' ? 'ERROR' : 'RUNNING'
}
function fmtTime(s: string | null) {
  if (!s) return '--'
  return s.slice(0, 16).replace('T', ' ')
}
function elapsed(t: Task) {
  if (!t.finished_at) return '...'
  const s = new Date(t.created_at)
  const e = new Date(t.finished_at)
  const diff = Math.round((e.getTime() - s.getTime()) / 1000)
  return diff < 60 ? `${diff}s` : `${Math.floor(diff/60)}m${diff%60}s`
}

onMounted(async () => {
  await Promise.all([loadTasks(), loadStrategies()])
  pollTimer = setInterval(loadTasks, 3000)
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="tasks-page">

    <!-- Header -->
    <div class="page-header">
      <div>
        <div class="page-title-code">CTRL</div>
        <div class="page-title-text">任務控制台</div>
      </div>
      <div class="header-badge" v-if="runningCount > 0">
        <span class="running-dot"></span>
        <span class="font-num">{{ runningCount }} 個任務執行中</span>
      </div>
    </div>

    <!-- Tab nav -->
    <div class="tab-nav">
      <button
        v-for="tab in tabs" :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >{{ tab.label }}</button>
    </div>

    <!-- ── Backtest ── -->
    <div class="panel card" v-if="activeTab === 'backtest'">
      <div class="panel-title">執行回測</div>
      <div class="form-grid">
        <div class="form-field">
          <label>策略</label>
          <select v-model="btForm.strategy" class="input-ctrl">
            <option v-for="s in strategies" :key="s.name" :value="s.name">
              {{ s.name }}
            </option>
          </select>
        </div>
        <div class="form-field">
          <label>標的代號</label>
          <input v-model="btForm.symbol" class="input-ctrl" placeholder="GC=F / 2330 / BTC-USD" />
        </div>
        <div class="form-field">
          <label>資料來源</label>
          <select v-model="btForm.source" class="input-ctrl">
            <option value="yfinance">yfinance（國際）</option>
            <option value="db">本地資料庫</option>
          </select>
        </div>
        <div class="form-field" v-if="btForm.source === 'yfinance'">
          <label>期間</label>
          <select v-model="btForm.period" class="input-ctrl">
            <option value="6mo">6 個月</option>
            <option value="1y">1 年</option>
            <option value="2y">2 年</option>
            <option value="5y">5 年</option>
            <option value="max">最大</option>
          </select>
        </div>
        <template v-if="btForm.source === 'db'">
          <div class="form-field">
            <label>起始日</label>
            <input v-model="btForm.start_date" type="date" class="input-ctrl" />
          </div>
          <div class="form-field">
            <label>結束日</label>
            <input v-model="btForm.end_date" type="date" class="input-ctrl" />
          </div>
        </template>
        <div class="form-field">
          <label>初始資金（留空用預設值）</label>
          <input v-model="btForm.cash" class="input-ctrl" placeholder="1000000" type="number" />
        </div>
      </div>
      <button class="btn-run" @click="runBacktest">▶ 執行回測</button>
    </div>

    <!-- ── Optimizer ── -->
    <div class="panel card" v-if="activeTab === 'optimizer'">
      <div class="panel-title">參數優化 (Grid Search)</div>
      <div class="form-grid">
        <div class="form-field">
          <label>策略</label>
          <select v-model="optForm.strategy" class="input-ctrl">
            <option v-for="s in strategies" :key="s.name" :value="s.name">
              {{ s.name }} ({{ s.combinations }} 組)
            </option>
          </select>
        </div>
        <div class="form-field">
          <label>標的代號</label>
          <input v-model="optForm.symbol" class="input-ctrl" placeholder="GC=F" />
        </div>
        <div class="form-field">
          <label>資料來源</label>
          <select v-model="optForm.source" class="input-ctrl">
            <option value="yfinance">yfinance</option>
            <option value="db">本地資料庫</option>
          </select>
        </div>
        <div class="form-field">
          <label>期間</label>
          <select v-model="optForm.period" class="input-ctrl">
            <option value="1y">1 年</option>
            <option value="2y">2 年</option>
            <option value="5y">5 年</option>
          </select>
        </div>
        <div class="form-field">
          <label>顯示前 N 名</label>
          <input v-model="optForm.top_n" class="input-ctrl" type="number" min="1" max="50" />
        </div>
        <div class="form-field">
          <label>初始資金（留空用預設值）</label>
          <input v-model="optForm.cash" class="input-ctrl" placeholder="1000000" type="number" />
        </div>
      </div>
      <div class="warning-note">⚠ 優化器會自動批次回測所有參數組合，需時較長</div>
      <button class="btn-run" @click="runOptimizer">▶ 開始優化</button>
    </div>

    <!-- ── Download ── -->
    <div class="panel card" v-if="activeTab === 'download'">
      <div class="panel-title">資料下載</div>
      <div class="form-grid">
        <div class="form-field">
          <label>資料來源</label>
          <select v-model="dlForm.source" class="input-ctrl">
            <option value="yfinance">yfinance（國際市場）</option>
            <option value="twse">TWSE（上市台股）</option>
            <option value="tpex">TPEx（上櫃台股）</option>
            <option value="taifex">TAIFEX（台灣期貨）</option>
          </select>
        </div>
        <div class="form-field">
          <label>代號 / 商品</label>
          <input v-model="dlForm.symbol" class="input-ctrl"
                 :placeholder="dlForm.source === 'yfinance' ? 'GC=F / BTC-USD / ^TWII' : dlForm.source === 'taifex' ? 'TX / MTX / TE' : '2330 / 2317'" />
        </div>
        <div class="form-field" v-if="sourcesForDl">
          <label>期間</label>
          <select v-model="dlForm.period" class="input-ctrl">
            <option value="1y">1 年</option>
            <option value="2y">2 年</option>
            <option value="5y">5 年</option>
            <option value="max">最大</option>
          </select>
        </div>
        <template v-else>
          <div class="form-field">
            <label>起始日</label>
            <input v-model="dlForm.start_date" type="date" class="input-ctrl" />
          </div>
          <div class="form-field">
            <label>結束日（留空=今日）</label>
            <input v-model="dlForm.end_date" type="date" class="input-ctrl" />
          </div>
        </template>
      </div>
      <button class="btn-run" @click="runDownload">▶ 開始下載</button>
    </div>

    <!-- ── Intelligence ── -->
    <div class="panel card" v-if="activeTab === 'intelligence'">
      <div class="panel-title">新聞情報收集 + AI 分析</div>
      <p class="panel-desc">從多個 RSS 來源抓取財經新聞，並用 Groq / Gemini 做情感分析（看多/看空/中性）</p>
      <div class="form-grid">
        <div class="form-field full">
          <label>額外搜尋關鍵字（選填，逗號分隔）</label>
          <input v-model="intelForm.keywords" class="input-ctrl"
                 placeholder="台積電, 聯準會, 黃金, 比特幣（留空用預設）" />
        </div>
      </div>
      <button class="btn-run" @click="runIntelligence">▶ 收集 + 分析</button>
    </div>

    <!-- ── X Monitor ── -->
    <div class="panel card" v-if="activeTab === 'x'">
      <div class="panel-title">X / Twitter 輿情監控</div>
      <p class="panel-desc">使用 Grok API 搜尋 X 上的熱門話題，並用 Gemini 生成輿情日報<br>
        <span class="text-muted">需設定 XAI_API_KEY（Grok）和 GEMINI_API_KEY</span></p>
      <div class="form-grid">
        <div class="form-field full">
          <label>搜尋主題（選填，逗號分隔）</label>
          <input v-model="xForm.topics" class="input-ctrl"
                 placeholder="台積電 TSMC, 黃金 gold, 比特幣 Bitcoin（留空用預設）" />
        </div>
      </div>
      <button class="btn-run" @click="runXMonitor">▶ 開始監控</button>
    </div>

    <!-- ── Threads ── -->
    <div class="panel card" v-if="activeTab === 'threads'">
      <div class="panel-title">Threads 社群貼文監控</div>
      <p class="panel-desc">抓取 Threads 帳號的最新貼文並做 AI 情感分析</p>
      <div class="form-grid">
        <div class="form-field">
          <label>新增監控帳號（選填）</label>
          <input v-model="thForm.username" class="input-ctrl" placeholder="@leo19790524" />
        </div>
      </div>
      <button class="btn-run" @click="runThreads">▶ 執行監控</button>
    </div>

    <!-- ── Report ── -->
    <div class="panel card" v-if="activeTab === 'report'">
      <div class="panel-title">每日市場報告</div>
      <p class="panel-desc">彙整市場行情、情緒分析、重要新聞，產生每日報告</p>
      <div class="form-grid">
        <div class="form-field">
          <label class="check-label">
            <input type="checkbox" v-model="reportForm.send_telegram" />
            <span>推播到 Telegram</span>
          </label>
        </div>
      </div>
      <button class="btn-run" @click="runReport">▶ 產生報告</button>
    </div>

    <!-- ── Task History ── -->
    <div class="card">
      <div class="task-header">
        <div class="card-title">任務紀錄</div>
        <button class="btn-refresh" @click="loadTasks">重新整理</button>
      </div>
      <div class="empty-state" v-if="tasks.length === 0">尚無任務記錄</div>
      <table v-else>
        <thead>
          <tr>
            <th>狀態</th>
            <th>任務名稱</th>
            <th>建立時間</th>
            <th>耗時</th>
            <th>結果 / 錯誤</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.id">
            <td>
              <span class="status-badge" :class="statusClass(t.status)">
                <span class="status-spin" v-if="t.status === 'running'"></span>
                {{ statusLabel(t.status) }}
              </span>
            </td>
            <td class="task-name font-num">{{ t.name }}</td>
            <td class="text-muted font-num">{{ fmtTime(t.created_at) }}</td>
            <td class="text-muted font-num">{{ elapsed(t) }}</td>
            <td class="result-cell">
              <span v-if="t.error" class="text-down" :title="t.error">{{ t.error.slice(0, 80) }}</span>
              <span v-else-if="t.result" class="text-muted">{{ t.result.slice(0, 100) }}</span>
              <span v-else class="text-muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

  </div>
</template>

<style scoped>
.tasks-page { display: flex; flex-direction: column; gap: 16px; }

/* Header */
.page-header {
  display: flex; align-items: flex-end;
  justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.page-title-code {
  font-family: 'JetBrains Mono', monospace; font-size: 9px; color: var(--muted);
  letter-spacing: 0.08em; background: var(--border); padding: 1px 6px;
  display: inline-block; margin-bottom: 4px;
}
.page-title-text {
  font-family: 'Orbitron', monospace; font-size: 15px; font-weight: 700;
  color: var(--text); letter-spacing: 0.06em;
}
.header-badge {
  display: flex; align-items: center; gap: 8px;
  background: rgba(0,255,136,0.06); border: 1px solid rgba(0,255,136,0.3);
  padding: 5px 12px; font-size: 12px; color: var(--neon);
}
.running-dot {
  width: 6px; height: 6px; background: var(--neon); border-radius: 50%;
  box-shadow: 0 0 6px var(--neon); animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }

/* Tabs */
.tab-nav {
  display: flex; gap: 4px; flex-wrap: wrap;
  border-bottom: 1px solid var(--border); padding-bottom: 0;
}
.tab-btn {
  background: none; border: 1px solid transparent;
  border-bottom: none; color: var(--muted); font-family: inherit;
  font-size: 12px; padding: 7px 16px; cursor: pointer; transition: all 0.15s;
  position: relative; bottom: -1px;
}
.tab-btn:hover { color: var(--text); }
.tab-btn.active {
  color: var(--cyan); border-color: var(--border); border-bottom-color: var(--bg);
  background: var(--bg);
}

/* Panel */
.panel { display: flex; flex-direction: column; gap: 16px; }
.panel-title {
  font-family: 'Orbitron', monospace; font-size: 11px; font-weight: 600;
  color: var(--text2); letter-spacing: 0.08em;
  border-bottom: 1px solid var(--border); padding-bottom: 10px;
}
.panel-desc { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 0; }

/* Forms */
.form-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px;
}
.form-field { display: flex; flex-direction: column; gap: 5px; }
.form-field.full { grid-column: 1 / -1; }
.form-field label {
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
  color: var(--muted); letter-spacing: 0.04em;
}
.input-ctrl {
  background: var(--surface2); border: 1px solid var(--border);
  border-radius: 2px; padding: 7px 10px; font-size: 12px; font-family: inherit;
  color: var(--text); transition: border-color 0.2s;
}
.input-ctrl:focus { outline: none; border-color: var(--cyan); }
.input-ctrl option { background: var(--surface3); }

.check-label {
  display: flex; align-items: center; gap: 8px; cursor: pointer;
  font-family: inherit; font-size: 12px; color: var(--text2);
}
.check-label input[type="checkbox"] { width: 14px; height: 14px; cursor: pointer; }

.warning-note {
  font-size: 11px; color: var(--gold); background: rgba(255,184,0,0.06);
  border: 1px solid rgba(255,184,0,0.2); padding: 8px 12px; border-radius: 2px;
}

/* Run button */
.btn-run {
  background: rgba(0,255,136,0.08); border: 1px solid rgba(0,255,136,0.35);
  color: var(--neon); font-family: 'Orbitron', monospace; font-size: 11px;
  font-weight: 600; letter-spacing: 0.1em; padding: 10px 24px;
  cursor: pointer; transition: all 0.2s; align-self: flex-start;
  clip-path: polygon(6px 0%, 100% 0%, calc(100% - 6px) 100%, 0% 100%);
}
.btn-run:hover { background: rgba(0,255,136,0.15); box-shadow: 0 0 12px rgba(0,255,136,0.2); }

/* Task history */
.task-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.btn-refresh {
  background: none; border: 1px solid var(--border); color: var(--muted);
  font-size: 11px; padding: 4px 10px; cursor: pointer; border-radius: 2px;
  transition: all 0.15s; font-family: inherit;
}
.btn-refresh:hover { color: var(--cyan); border-color: var(--cyan); }

.status-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: 'JetBrains Mono', monospace; font-size: 10px;
  font-weight: 600; letter-spacing: 0.06em;
  padding: 2px 8px; border-radius: 1px;
}
.status-done    { color: var(--neon); background: rgba(0,255,136,0.08); border: 1px solid rgba(0,255,136,0.25); }
.status-error   { color: var(--down); background: rgba(255,59,91,0.08); border: 1px solid rgba(255,59,91,0.25); }
.status-running { color: var(--cyan); background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.25); }

.status-spin {
  width: 6px; height: 6px; border: 1px solid var(--cyan); border-top-color: transparent;
  border-radius: 50%; animation: spin 0.8s linear infinite; display: inline-block;
}
@keyframes spin { to { transform: rotate(360deg) } }

.task-name { color: var(--text2); font-size: 12px; }
.result-cell { max-width: 300px; font-size: 11px; word-break: break-word; }

@media (max-width: 640px) {
  .form-grid { grid-template-columns: 1fr; }
  table { min-width: 600px; }
}
</style>
