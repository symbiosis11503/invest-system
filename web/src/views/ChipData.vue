<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface InstRow {
  symbol: string; date: string
  foreign_buy: number; foreign_sell: number; foreign_net: number
  trust_buy: number; trust_sell: number; trust_net: number
  dealer_net: number; total_net: number
  margin_balance: number; short_balance: number
}

const rows    = ref<InstRow[]>([])
const loading = ref(true)
const latestDate = ref('')
const sortKey = ref<keyof InstRow>('total_net')
const sortAsc = ref(false)
const search  = ref('')

async function load() {
  loading.value = true
  try {
    const data = await fetch('/api/chipdata/summary').then(r => r.json())
    rows.value = data.rows || []
    latestDate.value = data.latest_date || ''
  } catch {
    // Fallback: use list endpoint
    try {
      const data = await fetch('/api/chipdata').then(r => r.json())
      if (Array.isArray(data) && data.length > 0) {
        // Load data for first symbol
        const sym = data[0].symbol
        const sym_data = await fetch(`/api/chipdata/${sym}`).then(r => r.json())
        rows.value = sym_data.institutional || []
        latestDate.value = rows.value[0]?.date || ''
      }
    } catch {}
  } finally {
    loading.value = false
  }
}

onMounted(load)

const filtered = computed(() => {
  const q = search.value.toLowerCase()
  const r = q ? rows.value.filter(r => r.symbol?.toLowerCase().includes(q)) : rows.value
  return [...r].sort((a, b) => {
    const av = a[sortKey.value] ?? 0
    const bv = b[sortKey.value] ?? 0
    const cmp = (av as number) < (bv as number) ? -1 : (av as number) > (bv as number) ? 1 : 0
    return sortAsc.value ? cmp : -cmp
  })
})

function setSort(k: keyof InstRow) {
  if (sortKey.value === k) sortAsc.value = !sortAsc.value
  else { sortKey.value = k; sortAsc.value = false }
}
function sortIcon(k: keyof InstRow) {
  if (sortKey.value !== k) return '↕'
  return sortAsc.value ? '↑' : '↓'
}
function fmtNet(v: number | null | undefined) {
  if (v == null) return '--'
  const sign = v > 0 ? '+' : ''
  return sign + Number(v).toLocaleString()
}
function netClass(v: number) {
  return v > 0 ? 'text-up' : v < 0 ? 'text-down' : 'text-muted'
}
</script>

<template>
  <div class="chip-page">
    <div class="chip-header">
      <div>
        <h2 class="page-heading">法人籌碼分析</h2>
        <p class="page-sub text-muted" v-if="latestDate">資料日期：{{ latestDate }}</p>
      </div>
      <div class="search-wrap">
        <input
          v-model="search"
          class="search-input"
          placeholder="搜尋標的..."
          aria-label="搜尋標的"
        />
      </div>
    </div>

    <div class="loading-state" v-if="loading">載入中...</div>
    <div class="empty-state" v-else-if="rows.length === 0">尚無籌碼資料</div>

    <div class="card" v-else>
      <table>
        <thead>
          <tr>
            <th @click="setSort('symbol')" class="sortable">標的 {{ sortIcon('symbol') }}</th>
            <th @click="setSort('foreign_net')" class="sortable">外資淨買 {{ sortIcon('foreign_net') }}</th>
            <th @click="setSort('trust_net')" class="sortable">投信淨買 {{ sortIcon('trust_net') }}</th>
            <th @click="setSort('dealer_net')" class="sortable">自營淨買 {{ sortIcon('dealer_net') }}</th>
            <th @click="setSort('total_net')" class="sortable">三大法人合計 {{ sortIcon('total_net') }}</th>
            <th @click="setSort('margin_balance')" class="sortable" v-if="rows[0]?.margin_balance != null">融資餘額 {{ sortIcon('margin_balance') }}</th>
            <th @click="setSort('short_balance')" class="sortable" v-if="rows[0]?.short_balance != null">融券餘額 {{ sortIcon('short_balance') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.symbol + r.date">
            <td>
              <router-link :to="`/trading?symbol=${r.symbol}`" class="sym-link">
                {{ r.symbol }}
              </router-link>
            </td>
            <td class="font-num" :class="netClass(r.foreign_net)">{{ fmtNet(r.foreign_net) }}</td>
            <td class="font-num" :class="netClass(r.trust_net)">{{ fmtNet(r.trust_net) }}</td>
            <td class="font-num" :class="netClass(r.dealer_net)">{{ fmtNet(r.dealer_net) }}</td>
            <td>
              <span class="badge font-num" :class="r.total_net > 0 ? 'badge-up' : r.total_net < 0 ? 'badge-down' : 'badge-neutral'">
                {{ fmtNet(r.total_net) }}
              </span>
            </td>
            <td class="font-num text-muted" v-if="rows[0]?.margin_balance != null">
              {{ r.margin_balance ? Number(r.margin_balance).toLocaleString() : '--' }}
            </td>
            <td class="font-num text-muted" v-if="rows[0]?.short_balance != null">
              {{ r.short_balance ? Number(r.short_balance).toLocaleString() : '--' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.chip-page { display: flex; flex-direction: column; gap: 14px; }

.chip-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-heading { font-size: 16px; font-weight: 600; color: var(--text); }
.page-sub     { font-size: 12px; margin-top: 2px; }

.search-wrap { flex-shrink: 0; }

.search-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  color: var(--text);
  font-family: inherit;
  min-height: 40px;
  width: 200px;
  transition: border-color 0.2s;
}
.search-input:focus { outline: none; border-color: var(--gold); }
.search-input::placeholder { color: var(--muted); }

th.sortable { cursor: pointer; user-select: none; }
th.sortable:hover { color: var(--gold); }

.sym-link { color: var(--blue); font-weight: 500; }
.sym-link:hover { color: var(--gold); }

@media (max-width: 768px) {
  .card { padding: 14px; }
  table { min-width: 600px; }
  .search-input { width: 160px; }
}
</style>
