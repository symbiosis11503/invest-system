<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface Backtest {
  strategy: string; symbol: string
  start_date: string; end_date: string
  initial_cash: number; final_value: number
  total_return: number; max_drawdown: number
  sharpe_ratio: number; win_rate: number
  total_trades: number; ts: string
}

const rows    = ref<Backtest[]>([])
const loading = ref(true)
const sortKey = ref<keyof Backtest>('ts')
const sortAsc = ref(false)

async function load() {
  loading.value = true
  try {
    rows.value = await fetch('/api/backtests').then(r => r.json())
  } finally {
    loading.value = false
  }
}

onMounted(load)

const sorted = computed(() => {
  const k   = sortKey.value
  const asc = sortAsc.value
  return [...rows.value].sort((a, b) => {
    const av = a[k] ?? ''
    const bv = b[k] ?? ''
    const cmp = av < bv ? -1 : av > bv ? 1 : 0
    return asc ? cmp : -cmp
  })
})

function setSort(k: keyof Backtest) {
  if (sortKey.value === k) sortAsc.value = !sortAsc.value
  else { sortKey.value = k; sortAsc.value = false }
}

function sortIcon(k: keyof Backtest) {
  if (sortKey.value !== k) return '↕'
  return sortAsc.value ? '↑' : '↓'
}

function fmt(v: number | null | undefined, d = 2) {
  if (v == null) return '--'
  return Number(v).toFixed(d)
}
function fmtMoney(v: number | null | undefined) {
  if (v == null) return '--'
  return Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 0 })
}
</script>

<template>
  <div class="backtests-page">
    <!-- Summary bar -->
    <div class="summary-bar" v-if="!loading && rows.length > 0">
      <div class="sum-item">
        <span class="sum-label">共</span>
        <span class="sum-val">{{ rows.length }}</span>
        <span class="sum-unit">筆</span>
      </div>
      <div class="sum-item">
        <span class="sum-label">平均報酬率</span>
        <span class="sum-val font-num" :class="(rows.reduce((a,b)=>a+(b.total_return||0),0)/rows.length) >= 0 ? 'text-up' : 'text-down'">
          {{ fmt(rows.reduce((a,b)=>a+(b.total_return||0),0) / rows.length) }}%
        </span>
      </div>
      <div class="sum-item">
        <span class="sum-label">平均 Sharpe</span>
        <span class="sum-val font-num text-gold">
          {{ fmt(rows.reduce((a,b)=>a+(b.sharpe_ratio||0),0) / rows.length) }}
        </span>
      </div>
      <div class="sum-item">
        <span class="sum-label">平均勝率</span>
        <span class="sum-val font-num text-blue">
          {{ fmt(rows.reduce((a,b)=>a+(b.win_rate||0),0) / rows.length, 1) }}%
        </span>
      </div>
    </div>

    <div class="card">
      <div class="loading-state" v-if="loading">載入中...</div>
      <div class="empty-state" v-else-if="rows.length === 0">尚無回測紀錄</div>
      <table v-else>
        <thead>
          <tr>
            <th @click="setSort('strategy')" class="sortable">策略 {{ sortIcon('strategy') }}</th>
            <th @click="setSort('symbol')" class="sortable">標的 {{ sortIcon('symbol') }}</th>
            <th @click="setSort('start_date')" class="sortable">開始 {{ sortIcon('start_date') }}</th>
            <th @click="setSort('end_date')" class="sortable">結束 {{ sortIcon('end_date') }}</th>
            <th @click="setSort('initial_cash')" class="sortable">初始資金 {{ sortIcon('initial_cash') }}</th>
            <th @click="setSort('final_value')" class="sortable">最終價值 {{ sortIcon('final_value') }}</th>
            <th @click="setSort('total_return')" class="sortable">報酬率 {{ sortIcon('total_return') }}</th>
            <th @click="setSort('max_drawdown')" class="sortable">最大回撤 {{ sortIcon('max_drawdown') }}</th>
            <th @click="setSort('sharpe_ratio')" class="sortable">Sharpe {{ sortIcon('sharpe_ratio') }}</th>
            <th @click="setSort('win_rate')" class="sortable">勝率 {{ sortIcon('win_rate') }}</th>
            <th @click="setSort('total_trades')" class="sortable">交易次數 {{ sortIcon('total_trades') }}</th>
            <th @click="setSort('ts')" class="sortable">時間 {{ sortIcon('ts') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in sorted" :key="b.ts + b.symbol + b.strategy">
            <td class="text-blue">{{ b.strategy }}</td>
            <td>
              <router-link :to="`/trading?symbol=${b.symbol}`" class="sym-link">
                {{ b.symbol }}
              </router-link>
            </td>
            <td class="text-muted">{{ b.start_date || 'N/A' }}</td>
            <td class="text-muted">{{ b.end_date || 'N/A' }}</td>
            <td class="font-num">{{ fmtMoney(b.initial_cash) }}</td>
            <td class="font-num">{{ fmtMoney(b.final_value) }}</td>
            <td>
              <span class="badge" :class="(b.total_return||0) >= 0 ? 'badge-up' : 'badge-down'">
                {{ fmt(b.total_return) }}%
              </span>
            </td>
            <td>
              <span class="badge badge-down">{{ fmt(b.max_drawdown) }}%</span>
            </td>
            <td class="font-num" :class="(b.sharpe_ratio||0) >= 1 ? 'text-up' : 'text-muted'">
              {{ fmt(b.sharpe_ratio) }}
            </td>
            <td>
              <span class="badge" :class="(b.win_rate||0) >= 50 ? 'badge-up' : 'badge-down'">
                {{ fmt(b.win_rate, 1) }}%
              </span>
            </td>
            <td class="font-num text-muted">{{ b.total_trades || 0 }}</td>
            <td class="text-muted">{{ (b.ts || '').slice(0, 16) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.backtests-page { display: flex; flex-direction: column; gap: 14px; }

.summary-bar {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 14px 20px;
  align-items: center;
  position: relative;
}

.summary-bar::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--cyan), transparent);
  opacity: 0.4;
}

.sum-item { display: flex; align-items: baseline; gap: 6px; }
.sum-label { font-family: 'Orbitron', monospace; font-size: 9px; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.sum-val   { font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }
.sum-unit  { font-size: 11px; color: var(--muted); }

th.sortable {
  cursor: pointer;
  user-select: none;
}
th.sortable:hover { color: var(--cyan); }

.sym-link { color: var(--cyan); font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; letter-spacing: 0.04em; }
.sym-link:hover { color: var(--neon); }

@media (max-width: 768px) {
  .summary-bar { gap: 16px; }
  .sum-val { font-size: 16px; }
  .card { padding: 14px; }
  table { min-width: 800px; }
}
</style>
