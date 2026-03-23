<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface TgMessage {
  id: number; group_name: string; sender: string
  text: string; ts: string; msg_type: string
}
interface TgStats {
  total: number; today: number
  groups: { group_name: string; msg_count: number; latest_ts: string }[]
}

const messages = ref<TgMessage[]>([])
const stats    = ref<TgStats | null>(null)
const loading  = ref(true)
const selGroup = ref('all')
const search   = ref('')

async function load() {
  loading.value = true
  try {
    const [msgs, st] = await Promise.allSettled([
      fetch('/api/tg-messages').then(r => r.json()),
      fetch('/api/tg-stats').then(r => r.json()),
    ])
    if (msgs.status === 'fulfilled') messages.value = msgs.value
    if (st.status  === 'fulfilled') stats.value = st.value
  } finally {
    loading.value = false
  }
}

onMounted(load)

const groups = computed(() => {
  const gs = new Set(messages.value.map(m => m.group_name))
  return [...gs]
})

const filtered = computed(() => {
  let r = messages.value
  if (selGroup.value !== 'all') r = r.filter(m => m.group_name === selGroup.value)
  const q = search.value.toLowerCase()
  if (q) r = r.filter(m =>
    (m.text || '').toLowerCase().includes(q) ||
    (m.sender || '').toLowerCase().includes(q)
  )
  return r
})

function msgColor(text: string) {
  const t = (text || '').toLowerCase()
  if (t.includes('買') || t.includes('漲') || t.includes('bullish')) return 'left-up'
  if (t.includes('賣') || t.includes('跌') || t.includes('bearish')) return 'left-down'
  return ''
}
</script>

<template>
  <div class="msg-page">
    <!-- Stats bar -->
    <div class="stats-bar" v-if="stats">
      <div class="stat-block">
        <span class="sb-label">總訊息</span>
        <span class="sb-val font-num text-blue">{{ (stats.total || 0).toLocaleString() }}</span>
      </div>
      <div class="stat-block">
        <span class="sb-label">今日</span>
        <span class="sb-val font-num text-gold">{{ stats.today || 0 }}</span>
      </div>
      <div class="stat-block">
        <span class="sb-label">群組數</span>
        <span class="sb-val font-num">{{ stats.groups?.length || 0 }}</span>
      </div>
      <!-- Top groups -->
      <div class="group-pills" v-if="stats.groups?.length">
        <div v-for="g in stats.groups.slice(0, 5)" :key="g.group_name" class="group-pill">
          <span class="gp-name">{{ g.group_name }}</span>
          <span class="gp-count font-num text-muted">{{ g.msg_count }}</span>
        </div>
      </div>
    </div>

    <!-- Filters -->
    <div class="filters-row">
      <div class="tabs">
        <button
          class="tab-btn"
          :class="{ active: selGroup === 'all' }"
          @click="selGroup = 'all'"
        >全部</button>
        <button
          v-for="g in groups"
          :key="g"
          class="tab-btn"
          :class="{ active: selGroup === g }"
          @click="selGroup = g"
        >{{ g }}</button>
      </div>
      <input
        v-model="search"
        class="search-input"
        placeholder="搜尋內容..."
        aria-label="搜尋訊息"
      />
    </div>

    <div class="loading-state" v-if="loading">載入中...</div>
    <div class="empty-state" v-else-if="filtered.length === 0">尚無訊息紀錄</div>

    <!-- Message list -->
    <div class="msg-list" v-else>
      <div
        v-for="m in filtered"
        :key="m.id || m.ts"
        class="msg-item"
        :class="msgColor(m.text)"
      >
        <div class="mi-header">
          <span class="mi-group badge badge-blue">{{ m.group_name }}</span>
          <span class="mi-sender text-muted">{{ m.sender }}</span>
          <span class="mi-time text-muted font-num">{{ (m.ts || '').slice(0, 16) }}</span>
        </div>
        <div class="mi-text">{{ m.text }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-page { display: flex; flex-direction: column; gap: 14px; }

/* Stats bar */
.stats-bar {
  display: flex;
  align-items: center;
  gap: 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 20px;
  flex-wrap: wrap;
}

.stat-block { display: flex; flex-direction: column; gap: 2px; }
.sb-label   { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.sb-val     { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; }

.group-pills { display: flex; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.group-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 10px;
}
.gp-name  { font-size: 12px; color: var(--text2); }
.gp-count { font-size: 12px; }

/* Filters */
.filters-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tabs { display: flex; gap: 4px; flex-wrap: wrap; flex: 1; }

.tab-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
  min-height: 34px;
  white-space: nowrap;
}
.tab-btn:hover  { color: var(--text); }
.tab-btn.active { color: var(--gold); border-color: var(--gold); background: var(--gold-soft); }

.search-input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 13px;
  color: var(--text);
  font-family: inherit;
  min-height: 36px;
  width: 200px;
  transition: border-color 0.2s;
}
.search-input:focus { outline: none; border-color: var(--gold); }
.search-input::placeholder { color: var(--muted); }

/* Message list */
.msg-list { display: flex; flex-direction: column; gap: 8px; }

.msg-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  border-left: 3px solid var(--border);
  transition: border-color 0.15s;
}
.msg-item:hover     { border-color: var(--border); border-left-color: var(--gold); }
.msg-item.left-up   { border-left-color: var(--up); }
.msg-item.left-down { border-left-color: var(--down); }

.mi-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}

.mi-sender { font-size: 12px; font-weight: 500; }
.mi-time   { font-size: 11px; margin-left: auto; }

.mi-text {
  font-size: 13px;
  color: var(--text2);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 640px) {
  .stats-bar  { gap: 16px; }
  .sb-val     { font-size: 16px; }
  .group-pills { margin-left: 0; width: 100%; }
  .search-input { width: 100%; }
}
</style>
