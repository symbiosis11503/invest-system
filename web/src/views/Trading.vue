<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'

interface OHLCV { date: string; open: number; high: number; low: number; close: number; volume: number }
interface Trade  { symbol: string; action: string; price: number; size: number; pnl: number; ts: string }
interface Backtest { symbol: string; total_return: number; max_drawdown: number; sharpe_ratio: number; win_rate: number; total_trades: number }
interface SymbolInfo { symbol: string; count: number }

const route = useRoute()

// State
const symbols    = ref<SymbolInfo[]>([])
const rawData    = ref<OHLCV[]>([])
const trades     = ref<Trade[]>([])
const backtests  = ref<Backtest[]>([])
const selected   = ref('')
const loadError  = ref('')

// Chart state
let viewStart = 0
let viewEnd   = 0
const MIN_BARS = 15
const MAX_BARS = 300
let isDragging = false
let dragStartX = 0
let dragViewStart = 0
let lastPinchDist = 0
let lastTouchX = 0

// Canvas refs
const chartWrap = ref<HTMLDivElement>()
const canvas    = ref<HTMLCanvasElement>()
const crossInfo = ref<HTMLDivElement>()
let ctx: CanvasRenderingContext2D | null = null

// Stats
const statOpen   = ref('--')
const statHigh   = ref('--')
const statLow    = ref('--')
const statVol    = ref('--')
const priceMain  = ref('--')
const priceChg   = ref('-- (--)')
const priceClass = ref('flat')

const perfReturn = ref({ val: '--', cls: 'flat' })
const perfDD     = ref('--')
const perfSharpe = ref({ val: '--', cls: 'flat' })
const perfWin    = ref({ val: '--', cls: 'flat' })

function fmt(v: number | null | undefined, d = 2) {
  if (v == null) return '--'
  return Number(v).toFixed(d)
}
function fmtInt(v: number | null | undefined) {
  if (v == null) return '--'
  return Number(v).toLocaleString()
}

// Init
async function init() {
  try {
    const data = await fetch('/api/symbols').then(r => r.json())
    symbols.value = data
    if (!data.length) return

    // Check if URL has symbol param
    const urlSym = route.query.symbol as string
    const initial = urlSym && data.find((s: SymbolInfo) => s.symbol === urlSym)
      ? urlSym
      : data[0].symbol

    const [bt, tr] = await Promise.all([
      fetch('/api/backtests').then(r => r.json()).catch(() => []),
      fetch('/api/trades').then(r => r.json()).catch(() => []),
    ])
    backtests.value = bt
    trades.value = tr

    selected.value = initial
    await loadSymbol(initial)
  } catch (e: any) {
    loadError.value = '無法載入資料: ' + e.message
  }
}

async function loadSymbol(sym: string) {
  selected.value = sym
  loadError.value = ''
  try {
    const data: OHLCV[] = await fetch(`/api/market/${encodeURIComponent(sym)}`).then(r => r.json())
    if (!data.length) { loadError.value = `${sym} 無行情資料`; return }
    rawData.value = data.slice().reverse() // API returns DESC
    viewStart = Math.max(0, rawData.value.length - 80)
    viewEnd = rawData.value.length
    updateHeader()
    updatePerf()
    resizeCanvas()
    drawChart()
  } catch (e: any) {
    loadError.value = `載入 ${sym} 失敗: ` + e.message
  }
}

function updateHeader() {
  const d = rawData.value
  if (!d.length) return
  const last = d[d.length - 1]
  const prev = d.length > 1 ? d[d.length - 2] : last
  const chg = last.close - prev.close
  const chgPct = prev.close ? (chg / prev.close * 100) : 0
  const sign = chg > 0 ? '+' : ''

  priceMain.value  = fmt(last.close)
  priceChg.value   = `${sign}${fmt(chg)} (${sign}${fmt(chgPct)}%)`
  priceClass.value = chg > 0 ? 'up' : chg < 0 ? 'down' : 'flat'

  statOpen.value = fmt(last.open)
  statHigh.value = fmt(last.high)
  statLow.value  = fmt(last.low)
  statVol.value  = fmtInt(last.volume)
}

function updatePerf() {
  const sym = selected.value
  const bt = backtests.value.find(b => b.symbol === sym)
  if (!bt) {
    perfReturn.value = { val: '--', cls: 'flat' }
    perfDD.value = '--'
    perfSharpe.value = { val: '--', cls: 'flat' }
    perfWin.value = { val: '--', cls: 'flat' }
    return
  }
  const ret = bt.total_return || 0
  perfReturn.value = { val: fmt(ret) + '%', cls: ret >= 0 ? 'up' : 'down' }
  perfDD.value = fmt(bt.max_drawdown) + '%'
  const sr = bt.sharpe_ratio || 0
  perfSharpe.value = { val: fmt(sr), cls: sr >= 1 ? 'up' : 'flat' }
  const wr = bt.win_rate || 0
  perfWin.value = { val: fmt(wr, 1) + '%', cls: wr >= 50 ? 'up' : 'down' }
}

// Canvas
function resizeCanvas() {
  if (!canvas.value || !chartWrap.value) return
  const dpr  = window.devicePixelRatio || 1
  const rect  = chartWrap.value.getBoundingClientRect()
  const w     = rect.width
  const h     = Math.min(480, Math.max(320, window.innerHeight * 0.45))
  canvas.value.style.width  = w + 'px'
  canvas.value.style.height = h + 'px'
  canvas.value.width  = w * dpr
  canvas.value.height = h * dpr
  ctx = canvas.value.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
}

function calcMA(data: OHLCV[], period: number) {
  const ma: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) { ma.push(null); continue }
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) sum += data[j].close
    ma.push(sum / period)
  }
  return ma
}

interface ChartLayout {
  pad: { t: number; b: number; l: number; r: number }
  priceH: number; volH: number; chartW: number
  pMin: number; pMax: number; volTop: number; vMax: number
  barW: number; slice: OHLCV[]; n: number; W: number; H: number
  py: (v: number) => number
}
let layout: ChartLayout | null = null

function drawChart() {
  if (!ctx || !canvas.value || !rawData.value.length) return
  const dpr = window.devicePixelRatio || 1
  const W   = canvas.value.width / dpr
  const H   = canvas.value.height / dpr
  ctx.clearRect(0, 0, W, H)

  const pad = { t: 16, b: 24, l: 56, r: 8 }
  const volH   = H * 0.18
  const priceH = H - pad.t - pad.b - volH - 8
  const chartW = W - pad.l - pad.r

  const slice = rawData.value.slice(viewStart, viewEnd)
  const n     = slice.length
  if (!n) return

  const barW    = chartW / n
  const candleW = Math.max(1, barW * 0.65)
  const gap     = (barW - candleW) / 2

  // Price range
  let pMin = Infinity, pMax = -Infinity
  slice.forEach(d => { if (d.low < pMin) pMin = d.low; if (d.high > pMax) pMax = d.high })
  const pRange = pMax - pMin || 1
  pMin -= pRange * 0.04; pMax += pRange * 0.04
  const py = (v: number) => pad.t + priceH - (v - pMin) / (pMax - pMin) * priceH

  // Volume range
  let vMax = 0
  slice.forEach(d => { if ((d.volume || 0) > vMax) vMax = d.volume || 0 })
  if (!vMax) vMax = 1
  const volTop = H - pad.b - volH
  const vy = (v: number) => H - pad.b - (v / vMax) * volH

  // Save layout for crosshair
  layout = { pad, priceH, volH, chartW, pMin, pMax, volTop, vMax, barW, slice, n, W, H, py }

  // Grid lines
  ctx.strokeStyle = '#1a2240'
  ctx.lineWidth   = 0.5
  ctx.fillStyle   = '#4a5568'
  ctx.font        = '10px Inter, -apple-system, sans-serif'
  ctx.textAlign   = 'right'
  for (let i = 0; i <= 5; i++) {
    const v  = pMin + (pMax - pMin) * i / 5
    const yy = py(v)
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W - pad.r, yy); ctx.stroke()
    ctx.fillText(v.toFixed(v >= 1000 ? 0 : 2), pad.l - 4, yy + 3)
  }

  // Separator
  ctx.beginPath(); ctx.moveTo(pad.l, volTop - 4); ctx.lineTo(W - pad.r, volTop - 4); ctx.stroke()

  // Volume bars
  slice.forEach((d, i) => {
    const x  = pad.l + i * barW + gap
    const up = d.close >= d.open
    ctx!.fillStyle = up ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'
    const vt = vy(d.volume || 0)
    ctx!.fillRect(x, vt, candleW, H - pad.b - vt)
  })

  // Candles
  slice.forEach((d, i) => {
    const x  = pad.l + i * barW + gap
    const cx = x + candleW / 2
    const up = d.close >= d.open
    const color = up ? '#EF4444' : '#22C55E'
    ctx!.strokeStyle = color
    ctx!.lineWidth = 1
    ctx!.beginPath(); ctx!.moveTo(cx, py(d.high)); ctx!.lineTo(cx, py(d.low)); ctx!.stroke()
    const bodyTop = py(Math.max(d.open, d.close))
    const bodyBot = py(Math.min(d.open, d.close))
    const bodyH   = Math.max(1, bodyBot - bodyTop)
    ctx!.fillStyle = color
    ctx!.fillRect(x, bodyTop, candleW, bodyH)
  })

  // MA lines
  const d = rawData.value
  const ma5  = calcMA(d, 5).slice(viewStart, viewEnd)
  const ma20 = calcMA(d, 20).slice(viewStart, viewEnd)
  const ma60 = calcMA(d, 60).slice(viewStart, viewEnd)

  function drawMA(ma: (number | null)[], color: string) {
    ctx!.strokeStyle = color
    ctx!.lineWidth   = 1.2
    ctx!.beginPath()
    let started = false
    ma.forEach((v, i) => {
      if (v === null) return
      const x = pad.l + i * barW + barW / 2
      const y = py(v)
      if (!started) { ctx!.moveTo(x, y); started = true } else ctx!.lineTo(x, y)
    })
    ctx!.stroke()
  }
  drawMA(ma5,  '#EAB308')
  drawMA(ma20, '#38BDF8')
  drawMA(ma60, '#8B5CF6')

  // Trade signals
  const symTrades = trades.value.filter(t => t.symbol === selected.value)
  if (symTrades.length) {
    const tdMap: Record<string, Trade[]> = {}
    symTrades.forEach(t => {
      const d = (t.ts || '').slice(0, 10)
      if (!tdMap[d]) tdMap[d] = []
      tdMap[d].push(t)
    })
    slice.forEach((d, i) => {
      if (!tdMap[d.date]) return
      tdMap[d.date].forEach(t => {
        const x    = pad.l + i * barW + barW / 2
        const buy  = t.action === 'buy'
        const y    = buy ? py(d.low) + 14 : py(d.high) - 14
        ctx!.fillStyle = buy ? '#EF4444' : '#22C55E'
        ctx!.font       = 'bold 14px sans-serif'
        ctx!.textAlign  = 'center'
        ctx!.fillText(buy ? '▲' : '▼', x, y)
      })
    })
  }

  // X-axis labels
  ctx.fillStyle  = '#4a5568'
  ctx.font       = '10px Inter, -apple-system, sans-serif'
  ctx.textAlign  = 'center'
  const step     = Math.max(1, Math.floor(n / 7))
  for (let i = 0; i < n; i += step) {
    const x = pad.l + i * barW + barW / 2
    ctx.fillText(slice[i].date.slice(5), x, H - 6)
  }
}

// Crosshair
function showCrosshair(clientX: number, clientY: number) {
  if (!layout || !ctx || !crossInfo.value || !canvas.value) return
  const L    = layout
  const rect = canvas.value.getBoundingClientRect()
  const mx   = clientX - rect.left
  const my   = clientY - rect.top

  if (mx < L.pad.l || mx > L.W - L.pad.r || my < L.pad.t || my > L.H - L.pad.b) {
    crossInfo.value.style.display = 'none'; drawChart(); return
  }
  const idx = Math.floor((mx - L.pad.l) / L.barW)
  if (idx < 0 || idx >= L.n) { crossInfo.value.style.display = 'none'; drawChart(); return }

  drawChart()
  const d     = L.slice[idx]
  const cx    = L.pad.l + idx * L.barW + L.barW / 2
  const price = L.pMin + (1 - (my - L.pad.t) / L.priceH) * (L.pMax - L.pMin)

  // Crosshair lines
  ctx.strokeStyle = 'rgba(255,255,255,0.15)'
  ctx.lineWidth   = 0.5
  ctx.setLineDash([4, 4])
  ctx.beginPath(); ctx.moveTo(cx, L.pad.t); ctx.lineTo(cx, L.H - L.pad.b); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(L.pad.l, my); ctx.lineTo(L.W - L.pad.r, my); ctx.stroke()
  ctx.setLineDash([])

  // Price label
  ctx.fillStyle = 'rgba(245,158,11,0.9)'
  ctx.fillRect(0, my - 10, L.pad.l - 2, 20)
  ctx.fillStyle = '#0F172A'
  ctx.font      = 'bold 10px Inter, -apple-system, sans-serif'
  ctx.textAlign = 'right'
  ctx.fillText(price.toFixed(2), L.pad.l - 6, my + 4)

  // Info box
  const chg   = d.close - d.open
  const color = chg >= 0 ? '#EF4444' : '#22C55E'
  crossInfo.value.style.display = 'block'
  crossInfo.value.innerHTML = `<span style="color:${color}">${d.date}</span>&nbsp; O:${fmt(d.open)} H:${fmt(d.high)} L:${fmt(d.low)} C:${fmt(d.close)} V:${fmtInt(d.volume)}`
}

// Mouse events
function onMouseMove(e: MouseEvent) { showCrosshair(e.clientX, e.clientY) }
function onMouseLeave() { if (crossInfo.value) crossInfo.value.style.display = 'none'; drawChart() }

function onMouseDown(e: MouseEvent) {
  isDragging    = true
  dragStartX    = e.clientX
  dragViewStart = viewStart
  if (canvas.value) canvas.value.style.cursor = 'grabbing'
}

function onWindowMouseMove(e: MouseEvent) {
  if (!isDragging || !layout) return
  const barShift = Math.round((e.clientX - dragStartX) / layout.barW)
  const range    = viewEnd - viewStart
  let ns         = dragViewStart - barShift
  ns             = Math.max(0, Math.min(rawData.value.length - range, ns))
  viewStart      = ns; viewEnd = ns + range
  drawChart()
}

function onWindowMouseUp() {
  isDragging = false
  if (canvas.value) canvas.value.style.cursor = 'crosshair'
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  if (!layout) return
  const range   = viewEnd - viewStart
  const rect    = canvas.value!.getBoundingClientRect()
  const ratio   = (e.clientX - rect.left - layout.pad.l) / layout.chartW
  let delta     = e.deltaY > 0 ? Math.ceil(range * 0.1) : -Math.ceil(range * 0.1)
  let newRange  = Math.max(MIN_BARS, Math.min(Math.min(MAX_BARS, rawData.value.length), range + delta))
  if (newRange === range) return
  const left    = Math.round((newRange - range) * ratio)
  let ns = viewStart - left
  let ne = ns + newRange
  if (ns < 0) { ns = 0; ne = newRange }
  if (ne > rawData.value.length) { ne = rawData.value.length; ns = ne - newRange }
  viewStart = Math.max(0, ns); viewEnd = ne
  drawChart()
}

// Touch events
function onTouchStart(e: TouchEvent) {
  if (e.touches.length === 1) {
    isDragging    = true
    lastTouchX    = e.touches[0].clientX
    dragViewStart = viewStart
  } else if (e.touches.length === 2) {
    isDragging = false
    const dx = e.touches[0].clientX - e.touches[1].clientX
    const dy = e.touches[0].clientY - e.touches[1].clientY
    lastPinchDist = Math.sqrt(dx * dx + dy * dy)
  }
}

function onTouchMove(e: TouchEvent) {
  e.preventDefault()
  if (e.touches.length === 1 && isDragging && layout) {
    const dx       = e.touches[0].clientX - lastTouchX
    const barShift = Math.round(dx / layout.barW)
    if (!barShift) return
    lastTouchX = e.touches[0].clientX
    const range = viewEnd - viewStart
    let ns = viewStart - barShift
    ns = Math.max(0, Math.min(rawData.value.length - range, ns))
    viewStart = ns; viewEnd = ns + range
    drawChart()
    showCrosshair(e.touches[0].clientX, e.touches[0].clientY)
  } else if (e.touches.length === 2) {
    const dx   = e.touches[0].clientX - e.touches[1].clientX
    const dy   = e.touches[0].clientY - e.touches[1].clientY
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (lastPinchDist) {
      const scale   = dist / lastPinchDist
      const range   = viewEnd - viewStart
      let newRange  = Math.round(range / scale)
      newRange      = Math.max(MIN_BARS, Math.min(Math.min(MAX_BARS, rawData.value.length), newRange))
      if (newRange !== range) {
        const mid = Math.floor((viewStart + viewEnd) / 2)
        let ns = mid - Math.floor(newRange / 2)
        let ne = ns + newRange
        if (ns < 0) { ns = 0; ne = newRange }
        if (ne > rawData.value.length) { ne = rawData.value.length; ns = ne - newRange }
        viewStart = Math.max(0, ns); viewEnd = ne
        drawChart()
      }
    }
    lastPinchDist = dist
  }
}

function onTouchEnd() {
  isDragging = false; lastPinchDist = 0
  if (crossInfo.value) crossInfo.value.style.display = 'none'
}

// Resize handler
let resizeTimer: ReturnType<typeof setTimeout>
function onResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => { resizeCanvas(); drawChart() }, 150)
}

onMounted(async () => {
  await nextTick()
  window.addEventListener('mousemove', onWindowMouseMove)
  window.addEventListener('mouseup', onWindowMouseUp)
  window.addEventListener('resize', onResize)
  await init()
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onWindowMouseMove)
  window.removeEventListener('mouseup', onWindowMouseUp)
  window.removeEventListener('resize', onResize)
  clearTimeout(resizeTimer)
})

// Symbol change watcher
watch(selected, (sym) => { if (sym) loadSymbol(sym) })

const symTrades = () => trades.value.filter(t => t.symbol === selected.value).slice(0, 20)
</script>

<template>
  <div class="trading-page">
    <!-- Symbol bar -->
    <div class="symbol-bar">
      <div class="symbol-wrap">
        <select
          v-model="selected"
          class="symbol-select"
          aria-label="選擇標的"
        >
          <option v-for="s in symbols" :key="s.symbol" :value="s.symbol">
            {{ s.symbol }} ({{ s.count }}筆)
          </option>
        </select>
      </div>

      <!-- Price header -->
      <div class="price-block">
        <span class="price-main" :class="'price-' + priceClass">{{ priceMain }}</span>
        <span class="price-change" :class="'price-' + priceClass">{{ priceChg }}</span>
      </div>

      <!-- OHLV stats -->
      <div class="stat-pills">
        <div class="stat-pill">
          <span class="sp-label">開盤</span>
          <span class="sp-val font-num">{{ statOpen }}</span>
        </div>
        <div class="stat-pill">
          <span class="sp-label">最高</span>
          <span class="sp-val font-num text-up">{{ statHigh }}</span>
        </div>
        <div class="stat-pill">
          <span class="sp-label">最低</span>
          <span class="sp-val font-num text-down">{{ statLow }}</span>
        </div>
        <div class="stat-pill">
          <span class="sp-label">成交量</span>
          <span class="sp-val font-num">{{ statVol }}</span>
        </div>
      </div>
    </div>

    <!-- Error -->
    <div v-if="loadError" class="error-msg">{{ loadError }}</div>

    <!-- Chart container -->
    <div class="chart-card">
      <div class="chart-wrap" ref="chartWrap">
        <div class="chart-legend">
          <span><i style="background:#EAB308"></i>MA5</span>
          <span><i style="background:#38BDF8"></i>MA20</span>
          <span><i style="background:#8B5CF6"></i>MA60</span>
        </div>
        <div class="cross-info" ref="crossInfo"></div>
        <canvas
          ref="canvas"
          @mousemove="onMouseMove"
          @mouseleave="onMouseLeave"
          @mousedown="onMouseDown"
          @wheel.prevent="onWheel"
          @touchstart.passive="onTouchStart"
          @touchmove.prevent="onTouchMove"
          @touchend="onTouchEnd"
          style="cursor:crosshair; display:block; width:100%"
        />
      </div>
    </div>

    <!-- Perf + Trades row -->
    <div class="bottom-grid">
      <!-- Performance -->
      <div class="card">
        <div class="card-title">回測績效</div>
        <div class="perf-grid">
          <div class="perf-card">
            <div class="perf-label">報酬率</div>
            <div class="perf-value font-num" :class="'text-' + perfReturn.cls">{{ perfReturn.val }}</div>
          </div>
          <div class="perf-card">
            <div class="perf-label">最大回撤</div>
            <div class="perf-value font-num text-down">{{ perfDD }}</div>
          </div>
          <div class="perf-card">
            <div class="perf-label">Sharpe</div>
            <div class="perf-value font-num" :class="'text-' + perfSharpe.cls">{{ perfSharpe.val }}</div>
          </div>
          <div class="perf-card">
            <div class="perf-label">勝率</div>
            <div class="perf-value font-num" :class="'text-' + perfWin.cls">{{ perfWin.val }}</div>
          </div>
        </div>
      </div>

      <!-- Recent trades -->
      <div class="card">
        <div class="card-title">最近交易</div>
        <div v-if="!symTrades().length" class="empty-state">尚無交易紀錄</div>
        <table v-else>
          <thead>
            <tr><th>日期</th><th>動作</th><th>價格</th><th>數量</th><th>損益</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in symTrades()" :key="t.ts + t.action">
              <td class="text-muted">{{ t.ts?.slice(0, 10) }}</td>
              <td>
                <span class="badge" :class="t.action === 'buy' ? 'badge-up' : 'badge-down'">
                  {{ t.action === 'buy' ? '買入' : '賣出' }}
                </span>
              </td>
              <td class="font-num">{{ fmt(t.price) }}</td>
              <td class="font-num">{{ t.size }}</td>
              <td class="font-num" :class="(t.pnl || 0) >= 0 ? 'text-up' : 'text-down'">
                {{ (t.pnl || 0) >= 0 ? '+' : '' }}{{ fmt(t.pnl) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trading-page { display: flex; flex-direction: column; gap: 14px; }

/* Symbol bar */
.symbol-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
}

.symbol-select {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  min-width: 160px;
  min-height: 40px;
  font-family: inherit;
}
.symbol-select:focus { outline: none; border-color: var(--gold); }
.symbol-select option { background: var(--surface); }

.price-block { display: flex; align-items: baseline; gap: 12px; }
.price-main  { font-size: 28px; font-weight: 700; letter-spacing: -0.5px; font-variant-numeric: tabular-nums; }
.price-change{ font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
.price-up    { color: var(--up); }
.price-down  { color: var(--down); }
.price-flat  { color: var(--muted); }

.stat-pills  { display: flex; gap: 10px; flex-wrap: wrap; margin-left: auto; }
.stat-pill   { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
.sp-label    { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.sp-val      { font-size: 13px; font-weight: 600; }

/* Error */
.error-msg {
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.3);
  border-radius: 8px;
  padding: 12px 16px;
  color: #FCA5A5;
  font-size: 13px;
}

/* Chart */
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
}

.chart-wrap { position: relative; }

.chart-legend {
  position: absolute;
  top: 8px;
  right: 12px;
  display: flex;
  gap: 10px;
  font-size: 11px;
  z-index: 2;
  pointer-events: none;
  color: var(--text2);
}

.chart-legend span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.chart-legend i {
  display: inline-block;
  width: 18px;
  height: 2px;
  border-radius: 1px;
  flex-shrink: 0;
}

.cross-info {
  position: absolute;
  top: 8px;
  left: 12px;
  font-size: 12px;
  z-index: 2;
  pointer-events: none;
  background: rgba(15,23,42,0.9);
  border: 1px solid var(--border);
  padding: 4px 10px;
  border-radius: 6px;
  display: none;
  font-variant-numeric: tabular-nums;
  color: var(--text2);
}

/* Bottom */
.bottom-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 14px;
}

.perf-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.perf-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  text-align: center;
}

.perf-label { font-size: 11px; color: var(--muted); margin-bottom: 6px; }
.perf-value { font-size: 22px; font-weight: 700; }

/* Responsive */
@media (max-width: 900px) {
  .bottom-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .symbol-bar { padding: 12px 14px; gap: 10px; }
  .price-main { font-size: 22px; }
  .stat-pills { margin-left: 0; }
  .perf-value { font-size: 18px; }
}
@media (max-width: 480px) {
  .price-main { font-size: 20px; }
  .stat-pill:nth-child(3), .stat-pill:nth-child(4) { display: none; }
}
</style>
