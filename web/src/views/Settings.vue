<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface SettingsData {
  GROQ_API_KEY: string
  GEMINI_API_KEY: string
  GEMINI_API_KEY_APEX: string
  GEMINI_API_KEY_ECHO: string
  GEMINI_API_KEY_BACKUP: string
  XAI_API_KEY: string
  TG_API_ID: string
  TG_API_HASH: string
  TELEGRAM_BOT_TOKEN: string
  TELEGRAM_ALLOWED_USERS: string
  DEFAULT_CASH: string
  DEFAULT_COMMISSION: string
  DEFAULT_TAX: string
  [key: string]: string
}

const settings  = ref<SettingsData>({} as SettingsData)
const form      = ref<SettingsData>({} as SettingsData)
const loading   = ref(true)
const saving    = ref(false)
const saved     = ref(false)
const showKeys  = ref<Record<string, boolean>>({})

const API_GROUPS = [
  {
    label: 'AI 分析引擎',
    keys: [
      { key: 'GROQ_API_KEY',         label: 'Groq API Key',            hint: 'llama-3.3 情感分析', sensitive: true },
      { key: 'GEMINI_API_KEY',        label: 'Gemini Key (主)',          hint: 'Gemini 2.5 Flash 分析', sensitive: true },
      { key: 'GEMINI_API_KEY_APEX',   label: 'Gemini Key 2 (APEX)',      hint: '備用輪替 key', sensitive: true },
      { key: 'GEMINI_API_KEY_ECHO',   label: 'Gemini Key 3 (ECHO)',      hint: '備用輪替 key', sensitive: true },
      { key: 'GEMINI_API_KEY_BACKUP', label: 'Gemini Key 4 (BACKUP)',    hint: '備用輪替 key', sensitive: true },
    ]
  },
  {
    label: 'X / Twitter',
    keys: [
      { key: 'XAI_API_KEY', label: 'xAI (Grok) API Key', hint: 'X/Twitter 輿情搜尋', sensitive: true },
    ]
  },
  {
    label: 'Telegram',
    keys: [
      { key: 'TG_API_ID',            label: 'TG API ID',            hint: 'my.telegram.org 取得', sensitive: false },
      { key: 'TG_API_HASH',          label: 'TG API Hash',          hint: 'my.telegram.org 取得', sensitive: true },
      { key: 'TELEGRAM_BOT_TOKEN',   label: 'Bot Token',            hint: '推播報告用', sensitive: true },
      { key: 'TELEGRAM_ALLOWED_USERS', label: 'Chat ID',            hint: '接收推播的 chat_id', sensitive: false },
    ]
  },
  {
    label: '交易預設值',
    keys: [
      { key: 'DEFAULT_CASH',       label: '初始資金 (TWD)', hint: '預設 1,000,000', sensitive: false },
      { key: 'DEFAULT_COMMISSION', label: '手續費率',       hint: '預設 0.001425 (台股)', sensitive: false },
      { key: 'DEFAULT_TAX',        label: '交易稅率',       hint: '預設 0.003', sensitive: false },
    ]
  },
]

async function load() {
  loading.value = true
  try {
    const data = await fetch('/api/settings').then(r => r.json())
    settings.value = data
    // Clone to form (don't pre-fill masked values)
    for (const key of Object.keys(data)) {
      form.value[key] = data[key]?.startsWith('****') ? '' : (data[key] || '')
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true; saved.value = false
  try {
    const payload: Record<string, string> = {}
    for (const key of Object.keys(form.value)) {
      if (form.value[key] !== '') payload[key] = form.value[key]
    }
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    saved.value = true
    await load()
    setTimeout(() => { saved.value = false }, 3000)
  } finally {
    saving.value = false
  }
}

function toggleShow(key: string) {
  showKeys.value[key] = !showKeys.value[key]
}

function isSet(key: string) {
  return !!(settings.value[key])
}

onMounted(load)
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <div>
        <div class="page-title-code">CFG</div>
        <div class="page-title-text">系統設定</div>
      </div>
      <div class="header-actions">
        <span class="save-ok font-num" v-if="saved">✓ 已儲存</span>
        <button class="btn-save" @click="save" :disabled="saving">
          <span v-if="saving">儲存中...</span>
          <span v-else>儲存設定</span>
        </button>
      </div>
    </div>

    <div v-if="loading" class="loading-state">載入中...</div>

    <template v-else>
      <div v-for="group in API_GROUPS" :key="group.label" class="settings-group card">
        <div class="group-title">{{ group.label }}</div>
        <div class="fields-grid">
          <div v-for="item in group.keys" :key="item.key" class="field-row">
            <div class="field-meta">
              <label class="field-label">{{ item.label }}</label>
              <span class="field-hint">{{ item.hint }}</span>
            </div>
            <div class="field-input-wrap">
              <div class="input-group">
                <div class="status-dot-wrap">
                  <span class="dot" :class="isSet(item.key) ? 'dot-on' : 'dot-off'"></span>
                </div>
                <input
                  v-if="item.sensitive"
                  :type="showKeys[item.key] ? 'text' : 'password'"
                  v-model="form[item.key]"
                  class="field-input"
                  :placeholder="isSet(item.key) ? settings[item.key] : '輸入 ' + item.label"
                  autocomplete="off"
                  spellcheck="false"
                />
                <input
                  v-else
                  type="text"
                  v-model="form[item.key]"
                  class="field-input"
                  :placeholder="isSet(item.key) ? settings[item.key] : '輸入 ' + item.label"
                  autocomplete="off"
                  spellcheck="false"
                />
                <button
                  v-if="item.sensitive"
                  class="btn-toggle-show"
                  @click="toggleShow(item.key)"
                  :title="showKeys[item.key] ? '隱藏' : '顯示'"
                >
                  <svg v-if="!showKeys[item.key]" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                  <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Info note -->
      <div class="info-note card">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span>設定儲存於本地資料庫。敏感欄位（API Keys）以加密方式顯示，留空表示不更新。</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 16px; }

.page-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-title-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  color: var(--muted);
  letter-spacing: 0.08em;
  background: var(--border);
  padding: 1px 6px;
  display: inline-block;
  margin-bottom: 4px;
}

.page-title-text {
  font-family: 'Orbitron', monospace;
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.06em;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.save-ok {
  font-size: 12px;
  color: var(--neon);
  letter-spacing: 0.04em;
}

.btn-save {
  background: rgba(0,212,255,0.08);
  border: 1px solid rgba(0,212,255,0.4);
  color: var(--cyan);
  font-family: 'Orbitron', monospace;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  padding: 8px 20px;
  cursor: pointer;
  transition: all 0.2s;
  clip-path: polygon(6px 0%, 100% 0%, calc(100% - 6px) 100%, 0% 100%);
}
.btn-save:hover:not(:disabled) { background: rgba(0,212,255,0.15); box-shadow: 0 0 12px rgba(0,212,255,0.2); }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

/* Group */
.settings-group { display: flex; flex-direction: column; gap: 16px; }

.group-title {
  font-family: 'Orbitron', monospace;
  font-size: 10px;
  font-weight: 600;
  color: var(--cyan);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
  padding-bottom: 10px;
}

.fields-grid { display: flex; flex-direction: column; gap: 12px; }

.field-row {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  align-items: center;
  gap: 16px;
}

.field-meta { display: flex; flex-direction: column; gap: 3px; }

.field-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text2);
  cursor: default;
}

.field-hint {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--muted);
  letter-spacing: 0.02em;
}

.field-input-wrap { display: flex; align-items: center; }

.input-group {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.status-dot-wrap { flex-shrink: 0; }

.dot {
  display: block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.dot-on  { background: var(--neon); box-shadow: 0 0 6px var(--neon); }
.dot-off { background: var(--border); }

.field-input {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 2px;
  padding: 8px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--text);
  transition: border-color 0.2s;
  min-width: 0;
}
.field-input:focus {
  outline: none;
  border-color: var(--cyan);
  background: var(--surface3);
}
.field-input::placeholder { color: var(--muted); font-family: inherit; font-size: 11px; }

.btn-toggle-show {
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  cursor: pointer;
  padding: 6px;
  display: flex;
  align-items: center;
  border-radius: 2px;
  flex-shrink: 0;
  transition: all 0.15s;
}
.btn-toggle-show:hover { color: var(--cyan); border-color: var(--cyan); }

/* Info note */
.info-note {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

@media (max-width: 640px) {
  .field-row { grid-template-columns: 1fr; gap: 6px; }
}
</style>
