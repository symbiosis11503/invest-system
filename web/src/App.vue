<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const sidebarOpen = ref(false)

const navItems = [
  { path: '/',             label: '儀表板',   icon: 'grid',  code: 'DASH' },
  { path: '/trading',      label: '看盤',     icon: 'chart', code: 'LIVE' },
  { path: '/backtests',    label: '回測結果', icon: 'test',  code: 'BACK' },
  { path: '/intelligence', label: '市場情報', icon: 'intel', code: 'INTL' },
  { path: '/chipdata',     label: '籌碼分析', icon: 'chip',  code: 'CHIP' },
  { path: '/messages',     label: '群組監聽', icon: 'msg',   code: 'MSGS' },
]

function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <div class="layout">
    <!-- Sidebar -->
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <!-- Brand -->
      <div class="sidebar-header">
        <div class="brand">
          <div class="brand-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
              <polyline points="16 7 22 7 22 13"/>
            </svg>
          </div>
          <div class="brand-text">
            <span class="brand-name">INV-SYS</span>
            <span class="brand-sub">v2.0 · QUANTUM</span>
          </div>
        </div>
        <button class="close-btn" @click="sidebarOpen = false" aria-label="關閉選單">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <!-- System status bar -->
      <div class="sys-status">
        <span class="status-dot"></span>
        <span class="status-text">SYSTEM ONLINE</span>
        <span class="status-sep">|</span>
        <span class="status-text" style="color: var(--muted)">TW MARKET</span>
      </div>

      <!-- Nav -->
      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="sidebarOpen = false"
        >
          <span class="nav-code">{{ item.code }}</span>
          <div class="nav-icon">
            <svg v-if="item.icon === 'grid'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
              <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
            </svg>
            <svg v-if="item.icon === 'chart'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <line x1="12" y1="20" x2="12" y2="10"/>
              <line x1="18" y1="20" x2="18" y2="4"/>
              <line x1="6"  y1="20" x2="6"  y2="16"/>
              <line x1="2"  y1="20" x2="22" y2="20"/>
            </svg>
            <svg v-if="item.icon === 'test'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
            </svg>
            <svg v-if="item.icon === 'intel'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <svg v-if="item.icon === 'chip'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="9" y="9" width="6" height="6"/>
              <path d="M15 2v3M9 2v3M15 19v3M9 19v3M2 15h3M2 9h3M19 15h3M19 9h3"/>
              <rect x="5" y="5" width="14" height="14" rx="1"/>
            </svg>
            <svg v-if="item.icon === 'msg'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <span class="nav-label">{{ item.label }}</span>
          <span class="nav-arrow" v-if="isActive(item.path)">▶</span>
        </router-link>
      </nav>

      <!-- Footer -->
      <div class="sidebar-footer">
        <div class="footer-grid">
          <div class="footer-item">
            <span class="footer-key">BUILD</span>
            <span class="footer-val">2.0.1</span>
          </div>
          <div class="footer-item">
            <span class="footer-key">MODE</span>
            <span class="footer-val" style="color: var(--neon)">LIVE</span>
          </div>
          <div class="footer-item">
            <span class="footer-key">MKT</span>
            <span class="footer-val">TWS</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Overlay -->
    <div
      v-if="sidebarOpen"
      class="overlay"
      @click="sidebarOpen = false"
    />

    <!-- Main content -->
    <div class="main-wrapper">
      <!-- Top bar -->
      <header class="topbar">
        <button class="menu-btn" @click="sidebarOpen = true" aria-label="開啟選單">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
        <div class="topbar-title-group">
          <span class="topbar-path">ROOT / </span>
          <span class="page-title">{{ $route.meta.title }}</span>
        </div>
        <div class="topbar-right">
          <div class="live-badge">
            <span class="live-dot"></span>
            <span class="live-label">LIVE</span>
          </div>
          <div class="topbar-time">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
            <span>TWS</span>
          </div>
        </div>
      </header>

      <!-- Page content -->
      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}

/* ── Sidebar ── */
.sidebar {
  width: 230px;
  background: var(--surface3);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  z-index: 200;
  box-shadow: inset -1px 0 0 var(--border), 4px 0 20px rgba(0,0,0,0.4);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 14px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(0,212,255,0.05) 0%, transparent 60%);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  width: 32px;
  height: 32px;
  background: rgba(0,212,255,0.08);
  border: 1px solid rgba(0,212,255,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cyan);
  clip-path: polygon(6px 0%, 100% 0%, calc(100% - 6px) 100%, 0% 100%);
  flex-shrink: 0;
  box-shadow: inset 0 0 12px rgba(0,212,255,0.1);
}

.brand-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.brand-name {
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  font-weight: 700;
  color: var(--cyan);
  letter-spacing: 0.1em;
  text-shadow: 0 0 12px rgba(0,212,255,0.6);
}

.brand-sub {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--muted);
  letter-spacing: 0.06em;
}

.close-btn {
  display: none;
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  cursor: pointer;
  padding: 5px;
  border-radius: 2px;
  transition: all 0.2s;
}
.close-btn:hover { color: var(--cyan); border-color: var(--cyan); }

/* System status */
.sys-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: rgba(0,255,136,0.04);
  border-bottom: 1px solid var(--border2);
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.08em;
}

.status-dot {
  width: 5px;
  height: 5px;
  background: var(--neon);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--neon);
  animation: blink 2.5s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes blink {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--neon); }
  50%       { opacity: 0.3; box-shadow: none; }
}

.status-text { color: var(--neon); }
.status-sep  { color: var(--border); }

/* Nav */
.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 10px 8px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 2px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
  transition: all 0.15s;
  cursor: pointer;
  position: relative;
  border: 1px solid transparent;
  text-decoration: none;
}

.nav-item:hover {
  color: var(--text2);
  background: rgba(0,212,255,0.04);
  border-color: var(--border);
}

.nav-item.active {
  color: var(--cyan);
  background: rgba(0,212,255,0.07);
  border-color: rgba(0,212,255,0.2);
  box-shadow: inset 3px 0 0 var(--cyan), 0 0 12px rgba(0,212,255,0.05);
}

.nav-item.active .nav-code { color: var(--cyan); opacity: 1; }
.nav-item.active .nav-icon { color: var(--cyan); }

.nav-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 8px;
  letter-spacing: 0.08em;
  opacity: 0.4;
  width: 28px;
  flex-shrink: 0;
}

.nav-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  opacity: 0.7;
}

.nav-label {
  flex: 1;
  font-size: 12px;
}

.nav-arrow {
  font-size: 7px;
  color: var(--cyan);
  opacity: 0.6;
}

/* Footer */
.sidebar-footer {
  padding: 10px 14px;
  border-top: 1px solid var(--border);
  background: rgba(0,0,0,0.2);
}

.footer-grid {
  display: flex;
  gap: 14px;
}

.footer-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.footer-key {
  font-family: 'Orbitron', monospace;
  font-size: 7px;
  color: var(--muted);
  letter-spacing: 0.1em;
}

.footer-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text2);
  letter-spacing: 0.04em;
}

/* ── Main ── */
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  height: 50px;
  background: var(--surface3);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 1px 0 var(--border), 0 2px 20px rgba(0,0,0,0.4);
}

/* Top bar accent line */
.topbar::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--cyan), transparent);
  opacity: 0.4;
}

.menu-btn {
  display: none;
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  cursor: pointer;
  padding: 8px;
  border-radius: 2px;
  transition: all 0.2s;
  min-width: 36px;
  min-height: 36px;
  align-items: center;
  justify-content: center;
}
.menu-btn:hover { color: var(--cyan); border-color: var(--cyan); }

.topbar-title-group {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
}

.topbar-path {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.04em;
}

.page-title {
  font-family: 'Orbitron', monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--text2);
  letter-spacing: 0.08em;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.live-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  background: rgba(0,255,136,0.06);
  border: 1px solid rgba(0,255,136,0.25);
  padding: 3px 10px;
  border-radius: 1px;
  clip-path: polygon(4px 0%, 100% 0%, calc(100% - 4px) 100%, 0% 100%);
}

.live-dot {
  width: 6px;
  height: 6px;
  background: var(--neon);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--neon);
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px var(--neon); }
  50%       { opacity: 0.5; box-shadow: none; }
}

.live-label {
  font-family: 'Orbitron', monospace;
  font-size: 9px;
  color: var(--neon);
  font-weight: 700;
  letter-spacing: 0.1em;
}

.topbar-time {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--muted);
}

.content {
  flex: 1;
  padding: 20px;
  min-width: 0;
  background: var(--bg);
  /* Subtle grid overlay */
  background-image:
    linear-gradient(rgba(0,212,255,0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,212,255,0.02) 1px, transparent 1px);
  background-size: 40px 40px;
}

.overlay {
  display: none;
}

/* ── Responsive ── */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    z-index: 300;
  }
  .sidebar.open {
    transform: translateX(0);
  }
  .close-btn {
    display: flex;
  }
  .menu-btn {
    display: flex;
  }
  .overlay {
    display: block;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.7);
    z-index: 250;
    backdrop-filter: blur(2px);
  }
  .content {
    padding: 14px;
  }
  .topbar-time { display: none; }
}
</style>
