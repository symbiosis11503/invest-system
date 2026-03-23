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
    <div v-if="loading" class="loading-state">載入資料中...</div>

    <template v-else>
      <!-- Top metric row -->
      <div class="metrics-row">
        <!-- Market Mood -->
        <div class="metric-card" v-if="mood && mood.total > 0">
          <div class="metric-label">市場情緒</div>
          <div class="metric-value" :class="moodClass">{{ moodLabel }}</div>
          <div class="metric-sub font-num">
            <span class="text-up">看多 {{ mood.bullish }}</span>
            <span class="sep">/</span>
            <span class="text-down">看空 {{ mood.bearish }}</span>
            <span class="sep">/</span>
            <span class="text-muted">中性 {{ mood.neutral }}</span>
          </div>
          <div class="metric-foot font-num">平均分數 {{ mood.avg_score }}/10 · {{ mood.total }} 則</div>
        </div>

        <!-- TG Stats -->
        <div class="metric-card" v-if="tgStats && tgStats.total > 0">
          <div class="metric-label">群組監聽</div>
          <div class="metric-value text-blue font-num">{{ fmtNum(tgStats.total) }}</div>
          <div class="metric-sub">則訊息</div>
          <div class="metric-foot font-num">今日 {{ tgStats.today }} 則 · {{ tgStats.groups?.length }} 群組</div>
        </div>

        <!-- Latest Backtest -->
        <div class="metric-card" v-if="backtests.length > 0">
          <div class="metric-label">最新回測</div>
          <div class="metric-value font-num"
            :class="(backtests[0].total_return || 0) >= 0 ? 'text-up' : 'text-down'">
            {{ fmt(backtests[0].total_return) }}%
          </div>
          <div class="metric-sub">{{ backtests[0].symbol }} · {{ backtests[0].strategy }}</div>
          <div class="metric-foot font-num">Sharpe {{ fmt(backtests[0].sharpe_ratio) }} · 勝率 {{ fmt(backtests[0].win_rate, 1) }}%</div>
        </div>

        <!-- Total trades -->
        <div class="metric-card" v-if="trades.length > 0">
          <div class="metric-label">近期交易</div>
          <div class="metric-value text-gold font-num">{{ fmtNum(trades.length) }}</div>
          <div class="metric-sub">筆交易紀錄</div>
          <div class="metric-foot">最新：{{ fmtDate(trades[0]?.ts) }}</div>
        </div>
      </div>

      <!-- Institutional flow -->
      <div class="card" v-if="chipData && chipData.rows && chipData.rows.length > 0" style="margin-bottom:16px">
        <div class="card-title">
          法人動向
          <span class="date-badge">{{ chipData.latest_date }}</span>
        </div>
        <div class="chip-flow">
          <div
            v-for="r in chipData.rows"
            :key="r.symbol"
            class="chip-item"
          >
            <span class="chip-sym">{{ r.symbol }}</span>
            <span class="font-num" :class="r.total_net > 0 ? 'text-up' : 'text-down'">
              {{ r.total_net > 0 ? '+' : '' }}{{ fmtNum(r.total_net) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 2-col grid -->
      <div class="grid-2">
        <!-- Recent Backtests -->
        <div class="card">
          <div class="card-title">最近回測</div>
          <div v-if="recentBacktests.length === 0" class="empty-state">尚無回測紀錄</div>
          <table v-else>
            <thead>
              <tr>
                <th>策略</th><th>標的</th><th>報酬率</th><th>Sharpe</th><th>時間</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="b in recentBacktests" :key="b.ts + b.symbol">
                <td>{{ b.strategy }}</td>
                <td>
                  <router-link :to="`/trading?symbol=${b.symbol}`" class="sym-link">
                    {{ b.symbol }}
                  </router-link>
                </td>
                <td>
                  <span class="badge" :class="(b.total_return||0) >= 0 ? 'badge-up' : 'badge-down'">
                    {{ fmt(b.total_return) }}%
                  </span>
                </td>
                <td class="font-num">{{ fmt(b.sharpe_ratio) }}</td>
                <td class="text-muted">{{ fmtDate(b.ts) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="card-footer" v-if="backtests.length > 6">
            <router-link to="/backtests">查看全部 {{ backtests.length }} 筆</router-link>
          </div>
        </div>

        <!-- Recent Trades -->
        <div class="card">
          <div class="card-title">最近交易</div>
          <div v-if="recentTrades.length === 0" class="empty-state">尚無交易紀錄</div>
          <table v-else>
            <thead>
              <tr>
                <th>日期</th><th>標的</th><th>方向</th><th>價格</th><th>損益</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in recentTrades" :key="t.ts + t.symbol + t.action">
                <td class="text-muted">{{ fmtDate(t.ts) }}</td>
                <td>{{ t.symbol }}</td>
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
            <router-link to="/backtests">查看更多</router-link>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 16px; }

.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.metric-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color 0.2s;
}
.metric-card:hover { border-color: var(--gold); }

.metric-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.07em;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
  margin: 4px 0 2px;
}

.metric-sub {
  font-size: 12px;
  color: var(--text2);
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.sep { color: var(--border); }

.metric-foot {
  font-size: 11px;
  color: var(--muted);
  margin-top: 4px;
}

/* Chip flow */
.chip-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.chip-item {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
}

.chip-sym {
  font-weight: 600;
  color: var(--text2);
}

.date-badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--muted);
  margin-left: 8px;
  letter-spacing: 0;
  text-transform: none;
}

/* Grid */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.sym-link {
  color: var(--blue);
  font-weight: 500;
}
.sym-link:hover { color: var(--gold); }

.card-footer {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border2);
  font-size: 12px;
  color: var(--blue);
}

@media (max-width: 768px) {
  .grid-2 { grid-template-columns: 1fr; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 480px) {
  .metrics-row { grid-template-columns: 1fr; }
  .metric-value { font-size: 22px; }
}
</style>
