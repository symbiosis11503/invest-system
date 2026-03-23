<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const sidebarOpen = ref(false)

const navItems = [
  { path: '/',             label: '儀表板',   icon: 'grid' },
  { path: '/trading',      label: '看盤',     icon: 'chart' },
  { path: '/backtests',    label: '回測結果', icon: 'test' },
  { path: '/intelligence', label: '市場情報', icon: 'intel' },
  { path: '/chipdata',     label: '籌碼分析', icon: 'chip' },
  { path: '/messages',     label: '群組監聽', icon: 'msg' },
]

function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <div class="layout">
    <!-- Sidebar -->
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-header">
        <div class="brand">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
            <polyline points="16 7 22 7 22 13"/>
          </svg>
          <span>投資系統</span>
        </div>
        <button class="close-btn" @click="sidebarOpen = false" aria-label="關閉選單">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="sidebarOpen = false"
        >
          <!-- Grid icon -->
          <svg v-if="item.icon === 'grid'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>
          </svg>
          <!-- Chart icon -->
          <svg v-if="item.icon === 'chart'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="20" x2="12" y2="10"/>
            <line x1="18" y1="20" x2="18" y2="4"/>
            <line x1="6"  y1="20" x2="6"  y2="16"/>
            <line x1="2"  y1="20" x2="22" y2="20"/>
          </svg>
          <!-- Test icon -->
          <svg v-if="item.icon === 'test'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
          <!-- Intel icon -->
          <svg v-if="item.icon === 'intel'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <!-- Chip icon -->
          <svg v-if="item.icon === 'chip'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="6" height="6"/>
            <path d="M15 2v3M9 2v3M15 19v3M9 19v3M2 15h3M2 9h3M19 15h3M19 9h3"/>
            <rect x="5" y="5" width="14" height="14" rx="2"/>
          </svg>
          <!-- Message icon -->
          <svg v-if="item.icon === 'msg'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <span class="version-text">v2.0 · Finance</span>
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
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
        <span class="page-title">{{ $route.meta.title }}</span>
        <div class="topbar-right">
          <span class="live-dot" title="系統運行中"></span>
          <span class="live-label">Live</span>
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
  width: 220px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  z-index: 200;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 16px 14px;
  border-bottom: 1px solid var(--border);
}

.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--gold);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.close-btn {
  display: none;
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: color 0.2s;
}
.close-btn:hover { color: var(--text); }

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 8px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
  cursor: pointer;
}

.nav-item:hover {
  color: var(--text2);
  background: rgba(255,255,255,0.05);
}

.nav-item.active {
  color: var(--gold);
  background: var(--gold-soft);
}

.nav-item.active svg {
  color: var(--gold);
}

.nav-item svg {
  flex-shrink: 0;
  opacity: 0.8;
}

.sidebar-footer {
  padding: 14px 16px;
  border-top: 1px solid var(--border);
}

.version-text {
  font-size: 11px;
  color: var(--muted);
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
  height: 52px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}

.menu-btn {
  display: none;
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  transition: color 0.2s;
  min-width: 44px;
  min-height: 44px;
  align-items: center;
  justify-content: center;
}
.menu-btn:hover { color: var(--text); }

.page-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text2);
  flex: 1;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.live-dot {
  width: 7px;
  height: 7px;
  background: var(--down);
  border-radius: 50%;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.live-label {
  font-size: 11px;
  color: var(--down);
  font-weight: 600;
  letter-spacing: 0.05em;
}

.content {
  flex: 1;
  padding: 20px;
  min-width: 0;
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
    background: rgba(0,0,0,0.5);
    z-index: 250;
  }
  .content {
    padding: 14px;
  }
}
</style>
