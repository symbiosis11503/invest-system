import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import './style.css'
import App from './App.vue'

import Dashboard from './views/Dashboard.vue'
import Trading from './views/Trading.vue'
import Backtests from './views/Backtests.vue'
import Intelligence from './views/Intelligence.vue'
import ChipData from './views/ChipData.vue'
import Messages from './views/Messages.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/',             component: Dashboard,    meta: { title: '儀表板' } },
    { path: '/trading',      component: Trading,      meta: { title: '看盤' } },
    { path: '/backtests',    component: Backtests,    meta: { title: '回測結果' } },
    { path: '/intelligence', component: Intelligence, meta: { title: '市場情報' } },
    { path: '/chipdata',     component: ChipData,     meta: { title: '籌碼分析' } },
    { path: '/messages',     component: Messages,     meta: { title: '群組監聽' } },
  ]
})

router.afterEach((to) => {
  document.title = `${to.meta.title as string} — 投資系統`
})

createApp(App).use(router).mount('#app')
