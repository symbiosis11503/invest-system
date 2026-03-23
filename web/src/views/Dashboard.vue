<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface Backtest {
  strategy: string; symbol: string; start_date: string; end_date: string
  total_return: number; max_drawdown: number; sharpe_ratio: number
  win_rate: number; total_trades: number; ts: string
}
interface Trade {
  strategy: string; symbol: string; action: string
  price: number; size: number; pnl: number; ts: string
}
interface Mood {
  total: number; bullish: number; bearish: number; neutral: number
  avg_score: number; mood: string
}
interface TgStats { total: number; today: number; groups: any[] }
interface InstRow { symbol: string; foreign_net: number; trust_net: number; total_net: number }
interface ChipRow { latest_date: string; rows: InstRow[] }

const backtests = ref<Backtest[]>([])
const trades    = ref<Trade[]>([])
const mood      = ref<Mood | null>(null)
const tgStats   = ref<TgStats | null>(null)
const chipData  = ref<ChipRow | null>(null)
const loading   = ref(true)

async function load() {
  loading.value = true
  try {
    const [bt, tr, md, tg, cd] = await Promise.allSettled([
      fetch('/api/backtests').then(r => r.json()),
      fetch('/api/trades').then(r => r.json()),
      fetch('/api/mood').then(r => r.json()),
      fetch('/api/tg-stats').then(r => r.json()),
      fetch('/api/chipdata/summary').then(r => r.json()),
    ])
    if (bt.status === 'fulfilled') backtests.value = bt.value
    if (tr.status === 'fulfilled') trades.value    = tr.value
    if (md.status === 'fulfilled') mood.value      = md.value
    if (tg.status === 'fulfilled') tgStats.value   = tg.value
    if (cd.status === 'fulfilled') chipData.value  = cd.value
  } finally {
    loading.value = false
  }
}

onMounted(load)

const moodLabel = computed(() => {
  const m = mood.value?.mood
  return m === 'bullish' ? '看多' : m === 'bearish' ? '看空' : '中性'
})
const moodClass = computed(() => {
  const m = mood.value?.mood
  return m === 'bullish' ? 'text-up' : m === 'bearish' ? 'text-down' : 'text-muted'
})
const moodAccent = computed(() => {
  const m = mood.value?.mood
  return m === 'bullish' ? 'var(--up)' : m === 'bearish' ? 'var(--down)' : 'var(--muted)'
})

function fmt(v: number | null | undefined, d = 2) {
  if (v == null) return '--'
  return Number(v).toFixed(d)
}
function fmtNum(v: number | null | undefined) {
  if (v == null) return '--'
  return Number(v).toLocaleString()
}
function fmtDate(s: string) {
  return (s || '').slice(0, 10)
}

const recentBacktests = computed(() => backtests.value.slice(0, 6))
const recentTrades    = computed(() => trades.value.slice(0, 10))
</script>

<template>
  <div class="dashboard">
    <div v-if="loading" class="loading-state">INITIALIZING DATA STREAM...</div>

    <template v-else>
      <!-- Top metric row -->
      <div class="metrics-row">

        <!-- Market Mood -->
        <div class="metric-card" v-if="mood && mood.total > 0" :style="`--card-accent: ${moodAccent}`">
          <div class="mc-header">
            <span class="mc-code">SIG_01</span>
            <span class="mc-label">市場情緒</span>
          </div>
          <div class="mc-value font-num" :class="moodClass">{{ moodLabel }}</div>
          <div class="mc-bars" v-if="mood.total > 0">
            <div class="mc-bar">
              <span class="mc-bar-label text-up">看多</span>
              <div class="mc-bar-track">
                <div class="mc-bar-fill up" :style="`width: ${Math.round(mood.bullish/mood.total*100)}%`"></div>
              </div>
              <span class="mc-bar-val font-num text-up">{{ mood.bullish }}</span>
            </div>
            <div class="mc-bar">
              <span class="mc-bar-label text-down">看空</span>
              <div class="mc-bar-track">
                <div class="mc-bar-fill dn" :style="`width: ${Math.round(mood.bearish/mood.total*100)}%`"></div>
              </div>
              <span class="mc-bar-val font-num text-down">{{ mood.bearish }}</span>
            </div>
          </div>
          <div class="mc-foot font-num">AVG {{ mood.avg_score }}/10 · {{ mood.total }} SIGNALS</div>
        </div>

        <!-- TG Stats -->
        <div class="metric-card" v-if="tgStats && tgStats.total > 0" style="--card-accent: var(--cyan)">
          <div class="mc-header">
            <span class="mc-code">SIG_02</span>
            <span class="mc-label">群組監聽</span>
          </div>
          <div class="mc-value text-cyan font-num">{{ fmtNum(tgStats.total) }}</div>
          <div class="mc-sub">MESSAGES CAPTURED</div>
          <div class="mc-foot font-num">TODAY +{{ tgStats.today }} · {{ tgStats.groups?.length }} NODES</div>
        </div>

        <!-- Latest Backtest -->
        <div class="metric-card" v-if="backtests.length > 0"
          :style="`--card-accent: ${(backtests[0].total_return||0) >= 0 ? 'var(--up)' : 'var(--down)'}`">
          <div class="mc-header">
            <span class="mc-code">SIG_03</span>
            <span class="mc-label">最新回測</span>
          </div>
          <div class="mc-value font-num"
            :class="(backtests[0].total_return || 0) >= 0 ? 'text-up' : 'text-down'">
            {{ fmt(backtests[0].total_return) }}%
          </div>
          <div class="mc-sub font-num">{{ backtests[0].symbol }} · {{ backtests[0].strategy }}</div>
          <div class="mc-foot font-num">SHARPE {{ fmt(backtests[0].sharpe_ratio) }} · WIN {{ fmt(backtests[0].win_rate, 1) }}%</div>
        </div>

        <!-- Total trades -->
        <div class="metric-card" v-if="trades.length > 0" style="--card-accent: var(--gold)">
          <div class="mc-header">
            <span class="mc-code">SIG_04</span>
            <span class="mc-label">近期交易</span>
          </div>
          <div class="mc-value text-gold font-num">{{ fmtNum(trades.length) }}</div>
          <div class="mc-sub">TRADE RECORDS</div>
          <div class="mc-foot font-num">LATEST {{ fmtDate(trades[0]?.ts) }}</div>
        </div>

      </div>

      <!-- Institutional flow -->
      <div class="card hud-panel" v-if="chipData && chipData.rows && chipData.rows.length > 0">
        <div class="card-title">
          法人動向
          <span class="date-tag font-num">{{ chipData.latest_date }}</span>
        </div>
        <div class="chip-flow">
          <div
            v-for="r in chipData.rows"
            :key="r.symbol"
            class="chip-item"
            :class="r.total_net > 0 ? 'chip-up' : 'chip-dn'"
          >
            <span class="chip-sym font-hud">{{ r.symbol }}</span>
            <span class="chip-net font-num" :class="r.total_net > 0 ? 'text-up' : 'text-down'">
              {{ r.total_net > 0 ? '+' : '' }}{{ fmtNum(r.total_net) }}
            </span>
            <div class="chip-bar-mini">
              <div
                class="chip-bar-fill-mini"
                :class="r.total_net > 0 ? 'up' : 'dn'"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 2-col grid -->
      <div class="grid-2">
        <!-- Recent Backtests -->
        <div class="card hud-panel">
          <div class="card-title">最近回測</div>
          <div v-if="recentBacktests.length === 0" class="empty-state">NO BACKTEST RECORDS</div>
          <table v-else>
            <thead>
              <tr>
                <th>策略</th><th>標的</th><th>報酬率</th><th>Sharpe</th><th>時間</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in recentBacktests" :key="b.ts + b.symbol">
                <td class="td-strategy">{{ b.strategy }}</td>
                <td>
                  <router-link :to="`/trading?symbol=${b.symbol}`" class="sym-link font-num">
                    {{ b.symbol }}
                  </router-link>
                </td>
                <td>
                  <span class="badge" :class="(b.total_return||0) >= 0 ? 'badge-up' : 'badge-down'">
                    {{ fmt(b.total_return) }}%
                  </span>
                </td>
                <td class="font-num">{{ fmt(b.sharpe_ratio) }}</td>
                <td class="font-num text-muted">{{ fmtDate(b.ts) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="card-footer" v-if="backtests.length > 6">
            <router-link to="/backtests">
              <span class="footer-arrow">▶</span> 查看全部 {{ backtests.length }} 筆
            </router-link>
          </div>
        </div>

        <!-- Recent Trades -->
        <div class="card hud-panel">
          <div class="card-title">最近交易</div>
          <div v-if="recentTrades.length === 0" class="empty-state">NO TRADE RECORDS</div>
          <table v-else>
            <thead>
              <tr>
                <th>日期</th><th>標的</th><th>方向</th><th>價格</th><th>損益</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in recentTrades" :key="t.ts + t.symbol + t.action">
                <td class="font-num text-muted">{{ fmtDate(t.ts) }}</td>
                <td class="font-num">{{ t.symbol }}</td>
                <td>
                  <span class="badge" :class="t.action === 'buy' ? 'badge-up' : 'badge-down'">
                    {{ t.action === 'buy' ? '買入' : '賣出' }}
                  </span>
                </td>
                <td class="font-num">{{ fmt(t.price) }}</td>
                <td class="font-num" :class="(t.pnl||0) >= 0 ? 'text-up' : 'text-down'">
                  {{ (t.pnl||0) >= 0 ? '+' : '' }}{{ fmt(t.pnl) }}
                </td>
              </tr>
            </tbody>
          </table>
          <div class="card-footer" v-if="trades.length > 10">
            <router-link to="/backtests">
              <span class="footer-arrow">▶</span> 查看更多
            </router-link>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 16px; }

/* ── Metric Row ── */
.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
}

.metric-card {
  --card-accent: var(--cyan);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.25s;
  position: relative;
  overflow: hidden;
  cursor: default;
}

/* Accent top line */
.metric-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: var(--card-accent);
  opacity: 0.6;
  transition: opacity 0.25s;
}

/* HUD corner brackets */
.metric-card::after {
  content: '';
  position: absolute;
  bottom: -1px; right: -1px;
  width: 10px;
  height: 10px;
  border-bottom: 2px solid var(--card-accent);
  border-right: 2px solid var(--card-accent);
  opacity: 0.5;
  transition: opacity 0.25s;
}

.metric-card:hover {
  border-color: rgba(0,212,255,0.2);
  background: var(--surface2);
  box-shadow: 0 0 20px rgba(0,0,0,0.4), inset 0 0 30px rgba(0,212,255,0.02);
}
.metric-card:hover::before { opacity: 1; }
.metric-card:hover::after  { opacity: 1; }

.mc-header {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mc-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  color: var(--muted);
  letter-spacing: 0.06em;
  background: var(--border);
  padding: 1px 5px;
  border-radius: 1px;
}

.mc-label {
  font-family: 'Orbitron', monospace;
  font-size: 9px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.mc-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  margin: 4px 0 2px;
  letter-spacing: -0.02em;
}

.mc-sub {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text2);
  letter-spacing: 0.04em;
}

.mc-foot {
  font-size: 9px;
  color: var(--muted);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  margin-top: 2px;
}

/* Mini bar charts */
.mc-bars {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 4px 0;
}

.mc-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mc-bar-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  width: 22px;
  flex-shrink: 0;
}

.mc-bar-track {
  flex: 1;
  height: 3px;
  background: var(--border);
  border-radius: 1px;
  overflow: hidden;
}

.mc-bar-fill {
  height: 100%;
  border-radius: 1px;
  transition: width 0.5s ease;
}
.mc-bar-fill.up { background: var(--up); box-shadow: 0 0 4px var(--up); }
.mc-bar-fill.dn { background: var(--down); box-shadow: 0 0 4px var(--down); }

.mc-bar-val {
  font-size: 9px;
  width: 20px;
  text-align: right;
  flex-shrink: 0;
}

/* ── Chip Flow ── */
.hud-panel { }

.date-tag {
  font-size: 9px;
  font-weight: 400;
  color: var(--muted);
  background: var(--border);
  padding: 1px 6px;
  border-radius: 1px;
  letter-spacing: 0;
  text-transform: none;
}

.chip-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface2);
  border: 1px solid var(--border);
  padding: 6px 12px;
  font-size: 12px;
  position: relative;
  clip-path: polygon(6px 0%, 100% 0%, calc(100% - 6px) 100%, 0% 100%);
  transition: all 0.2s;
}

.chip-item.chip-up {
  border-color: rgba(255,59,91,0.2);
  background: rgba(255,59,91,0.04);
}
.chip-item.chip-dn {
  border-color: rgba(0,230,118,0.2);
  background: rgba(0,230,118,0.04);
}

.chip-sym {
  font-size: 11px;
  font-weight: 600;
  color: var(--text2);
  letter-spacing: 0.06em;
}

.chip-net {
  font-size: 11px;
}

.chip-bar-mini {
  width: 30px;
  height: 2px;
  background: var(--border);
  border-radius: 1px;
}

.chip-bar-fill-mini {
  height: 100%;
  width: 100%;
  border-radius: 1px;
}
.chip-bar-fill-mini.up { background: var(--up); }
.chip-bar-fill-mini.dn { background: var(--down); }

/* ── Grid ── */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.td-strategy {
  color: var(--text2);
  font-family: 'Inter', sans-serif;
  font-size: 12px;
}

.sym-link {
  color: var(--cyan);
  font-weight: 500;
  font-size: 12px;
  letter-spacing: 0.04em;
}
.sym-link:hover { color: var(--neon); }

.card-footer {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border2);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.04em;
}

.card-footer a { color: var(--cyan); }
.card-footer a:hover { color: var(--neon); }

.footer-arrow {
  font-size: 8px;
  opacity: 0.6;
  margin-right: 2px;
}

@media (max-width: 768px) {
  .grid-2 { grid-template-columns: 1fr; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 480px) {
  .metrics-row { grid-template-columns: 1fr; }
  .mc-value { font-size: 26px; }
}
</style>
