#!/bin/bash
# clear_news_backlog.sh — 加速清理未分析新聞
# 每次處理 500 則，用 launchd 每 30 分鐘跑一次
# 7 key 輪替 + 4s/則 = ~33 分鐘/500 則

INVEST_DIR="/Users/wei/Projects/invest-system"
LOG="$INVEST_DIR/logs/backlog_clear.log"
VENV="$INVEST_DIR/.venv/bin/python3"

cd "$INVEST_DIR" || exit 1

# 載入 .env（API keys）
export HOME="/Users/wei"
if [ -f "$INVEST_DIR/.env" ]; then
    export $(grep -v '^#' "$INVEST_DIR/.env" | xargs)
fi

mkdir -p "$INVEST_DIR/logs"

# 檢查剩餘 backlog
BACKLOG=$($VENV -c "
from intelligence import get_conn
conn = get_conn()
n = conn.execute('SELECT COUNT(*) FROM news_intelligence WHERE sentiment IS NULL').fetchone()[0]
conn.close()
print(n)
" 2>/dev/null)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backlog: $BACKLOG" >> "$LOG"

if [ "$BACKLOG" -eq 0 ] 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] All clear, nothing to do" >> "$LOG"
    exit 0
fi

# 每次最多 500 則
BATCH=500
if [ "$BACKLOG" -lt "$BATCH" ]; then
    BATCH=$BACKLOG
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Processing batch of $BATCH..." >> "$LOG"

$VENV -c "
from intelligence import analyze_news
a = analyze_news(limit=$BATCH)
print(f'Analyzed: {a}/$BATCH')
" >> "$LOG" 2>&1

REMAINING=$((BACKLOG - BATCH))
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Remaining: ~$REMAINING" >> "$LOG"
