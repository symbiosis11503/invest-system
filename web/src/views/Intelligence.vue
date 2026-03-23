<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'

interface NewsItem {
  id: number; title: string; summary: string; url: string; source: string
  sentiment: string; score: number; keywords: string; reason: string
  published_at: string; analyzed_at: string
}
interface Mood {
  total: number; bullish: number; bearish: number; neutral: number
  avg_score: number; mood: string
}

const news    = ref<NewsItem[]>([])
const mood    = ref<Mood | null>(null)
const loading = ref(true)
const filter  = ref('all') // 'all' | 'bullish' | 'bearish' | 'neutral'

async function load() {
  loading.value = true
  try {
    const [n, m] = await Promise.allSettled([
      fetch('/api/intelligence').then(r => r.json()),
      fetch('/api/mood').then(r => r.json()),
    ])
    if (n.status === 'fulfilled') news.value = n.value
    if (m.status === 'fulfilled') mood.value = m.value
  } finally {
    loading.value = false
  }
}

onMounted(load)

const filtered = computed(() =>
  filter.value === 'all' ? news.value : news.value.filter(n => n.sentiment === filter.value)
)

const moodLabel = computed(() => {
  const m = mood.value?.mood
  return m === 'bullish' ? '看多' : m === 'bearish' ? '看空' : '中性'
})

function sentimentLabel(s: string) {
  return s === 'bullish' ? '看多' : s === 'bearish' ? '看空' : '中性'
}

function sentimentClass(s: string) {
  return s === 'bullish' ? 'badge-up' : s === 'bearish' ? 'badge-down' : 'badge-neutral'
}

function scoreColor(score: number) {
  if (score >= 7) return 'var(--up)'
  if (score <= 3) return 'var(--down)'
  return 'var(--muted)'
}

function parseKeywords(kw: string): string[] {
  try {
    const arr = JSON.parse(kw)
    return Array.isArray(arr) ? arr.slice(0, 5) : []
  } catch {
    return (kw || '').split(',').map(s => s.trim()).filter(Boolean).slice(0, 5)
  }
}
</script>

<template>
  <div class="intel-page">
    <!-- Mood overview -->
    <div class="mood-card" v-if="mood && mood.total > 0">
      <div class="mood-main">
        <div class="mood-label">今日市場情緒</div>
        <div class="mood-value"
          :class="mood.mood === 'bullish' ? 'text-up' : mood.mood === 'bearish' ? 'text-down' : 'text-muted'">
          {{ moodLabel }}
        </div>
        <div class="mood-score font-num">平均分數 {{ mood.avg_score }}/10</div>
      </div>
      <div class="mood-bars">
        <div class="mb-item">
          <span class="mb-label text-up">看多</span>
          <div class="mb-bar">
            <div class="mb-fill up" :style="{ width: (mood.bullish / mood.total * 100) + '%' }"></div>
          </div>
          <span class="mb-val font-num">{{ mood.bullish }}</span>
        </div>
        <div class="mb-item">
          <span class="mb-label text-down">看空</span>
          <div class="mb-bar">
            <div class="mb-fill down" :style="{ width: (mood.bearish / mood.total * 100) + '%' }"></div>
          </div>
          <span class="mb-val font-num">{{ mood.bearish }}</span>
        </div>
        <div class="mb-item">
          <span class="mb-label text-muted">中性</span>
          <div class="mb-bar">
            <div class="mb-fill neutral" :style="{ width: (mood.neutral / mood.total * 100) + '%' }"></div>
          </div>
          <span class="mb-val font-num">{{ mood.neutral }}</span>
        </div>
      </div>
    </div>

    <!-- Filter tabs -->
    <div class="filter-tabs">
      <button
        v-for="f in [['all','全部'], ['bullish','看多'], ['bearish','看空'], ['neutral','中性']]"
        :key="f[0]"
        class="tab-btn"
        :class="{ active: filter === f[0] }"
        @click="filter = f[0]"
      >{{ f[1] }}</button>
      <span class="filter-count text-muted">{{ filtered.length }} 則</span>
    </div>

    <!-- Loading -->
    <div class="loading-state" v-if="loading">載入中...</div>
    <div class="empty-state" v-else-if="filtered.length === 0">尚無情報資料</div>

    <!-- News grid -->
    <div class="news-grid" v-else>
      <a
        v-for="item in filtered"
        :key="item.id"
        :href="item.url"
        target="_blank"
        rel="noopener"
        class="news-card"
      >
        <div class="nc-header">
          <span class="badge" :class="sentimentClass(item.sentiment)">
            {{ sentimentLabel(item.sentiment) }}
          </span>
          <span class="nc-source text-muted">{{ item.source }}</span>
          <span class="nc-score font-num" :style="{ color: scoreColor(item.score) }">
            {{ item.score }}/10
          </span>
        </div>
        <div class="nc-title">{{ item.title }}</div>
        <div class="nc-summary">{{ item.summary }}</div>
        <div class="nc-reason" v-if="item.reason">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          {{ item.reason }}
        </div>
        <div class="nc-keywords" v-if="item.keywords">
          <span
            v-for="kw in parseKeywords(item.keywords)"
            :key="kw"
            class="badge badge-gold"
          >{{ kw }}</span>
        </div>
        <div class="nc-time text-muted">{{ (item.analyzed_at || item.published_at || '').slice(0, 16) }}</div>
      </a>
    </div>
  </div>
</template>

<style scoped>
.intel-page { display: flex; flex-direction: column; gap: 16px; }

/* Mood card */
.mood-card {
  display: flex;
  gap: 32px;
  align-items: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 24px;
  flex-wrap: wrap;
}

.mood-main { min-width: 140px; }
.mood-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 6px; }
.mood-value { font-size: 32px; font-weight: 700; letter-spacing: -0.02em; }
.mood-score { font-size: 12px; color: var(--muted); margin-top: 4px; }

.mood-bars { flex: 1; display: flex; flex-direction: column; gap: 8px; min-width: 200px; }

.mb-item { display: flex; align-items: center; gap: 8px; }
.mb-label { font-size: 12px; font-weight: 600; min-width: 32px; }
.mb-bar {
  flex: 1;
  height: 6px;
  background: var(--border2);
  border-radius: 3px;
  overflow: hidden;
}
.mb-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.5s ease;
}
.mb-fill.up      { background: var(--up); }
.mb-fill.down    { background: var(--down); }
.mb-fill.neutral { background: var(--muted); }
.mb-val { font-size: 12px; min-width: 24px; text-align: right; color: var(--text2); }

/* Filters */
.filter-tabs { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }

.tab-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
  min-height: 36px;
}
.tab-btn:hover  { color: var(--text); border-color: var(--muted); }
.tab-btn.active { color: var(--gold); border-color: var(--gold); background: var(--gold-soft); }

.filter-count { font-size: 12px; margin-left: 6px; }

/* News grid */
.news-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.news-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.2s, transform 0.15s;
  color: var(--text);
  text-decoration: none;
}
.news-card:hover {
  border-color: var(--gold);
  transform: translateY(-1px);
}

.nc-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.nc-source { font-size: 11px; flex: 1; }
.nc-score  { font-size: 12px; font-weight: 600; }

.nc-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.nc-summary {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.nc-reason {
  display: flex;
  gap: 6px;
  align-items: flex-start;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.5;
  background: var(--surface2);
  border-radius: 6px;
  padding: 6px 8px;
}

.nc-keywords { display: flex; gap: 4px; flex-wrap: wrap; }

.nc-time { font-size: 11px; color: var(--muted); margin-top: 2px; }

@media (max-width: 640px) {
  .mood-card { flex-direction: column; align-items: flex-start; gap: 16px; }
  .news-grid { grid-template-columns: 1fr; }
}
</style>
