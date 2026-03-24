#!/bin/bash
# 股東紀念品資料更新 (每 12 小時)
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HOME="/Users/wei"

INVEST_DIR="/Users/wei/Projects/invest-system"
VENV="$INVEST_DIR/.venv/bin/python"
LOG="$INVEST_DIR/logs/shareholder_gifts.log"

mkdir -p "$INVEST_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

log "========== SHAREHOLDER GIFTS UPDATE START =========="

$VENV -c "
from shareholder_gifts import fetch_gifts, get_all_gifts
count = fetch_gifts()
total = len(get_all_gifts())
print(f'Fetched: {count}, Total in DB: {total}')
" >> "$LOG" 2>&1

if [ $? -eq 0 ]; then
    log "UPDATE SUCCESS"
else
    log "UPDATE FAILED"
    # Telegram 通知
    TG_BOT_TOKEN="8585765797:AAGYUDdSSTgOmz2TS3d9zsjk4F7T_VdWzao"
    TG_CHAT_ID="6927318445"
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TG_CHAT_ID" \
        -d text="⚠️ 投資系統: 股東紀念品更新失敗" > /dev/null 2>&1
fi

log "========== SHAREHOLDER GIFTS UPDATE DONE =========="
