#!/bin/bash
# 投資系統每日資料更新 (14:30 TST 執行)
# 下載當日行情 + 籌碼 + 新聞收集
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HOME="/Users/wei"

INVEST_DIR="/Users/wei/Projects/invest-system"
VENV="$INVEST_DIR/.venv/bin/python"
LOG="$INVEST_DIR/logs/daily_update.log"

mkdir -p "$INVEST_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

log "========== DAILY UPDATE START =========="

# 1. 台股行情 (yfinance 增量)
log "Updating market data..."
$VENV -c "
from data.fetcher import fetch_twse_daily, save_to_db
import datetime
today = datetime.date.today().strftime('%Y%m%d')
data = fetch_twse_daily(today)
if data:
    print(f'TWSE daily: {len(data)} rows')
else:
    print('No TWSE data (market closed?)')
" >> "$LOG" 2>&1

# 2. FinMind 籌碼更新
log "Updating chip data..."
$VENV -c "
from data.finmind import batch_download
symbols = ['2330','2317','2454','2382','2881','2891','1301','2303','2002','3034','3008','3443','6669','2308','3231','5274','6285','2603']
import datetime
today = (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
for s in symbols:
    batch_download(s, today)
print(f'FinMind: {len(symbols)} stocks updated')
" >> "$LOG" 2>&1

# 2.5 TWSE OpenAPI (PER/EPS/月營收/公告)
log "Updating TWSE indicators..."
$VENV data/twse_fetcher.py >> "$LOG" 2>&1

# 3. 新聞收集 + AI 分析
log "Collecting news..."
cd "$INVEST_DIR"
$VENV -c "
from intelligence import collect_news, analyze_news
n = collect_news()
print(f'News collected: {n}')
if n > 0:
    a = analyze_news(limit=n)
    print(f'News analyzed: {a}')
" >> "$LOG" 2>&1

# 4. 自動分析 Top 10 異動股
log "Running auto analysis..."
$VENV scripts/auto_analysis.py >> "$LOG" 2>&1

# 5. 每日報告
log "Generating daily report..."
$VENV daily_report.py >> "$LOG" 2>&1

log "========== DAILY UPDATE DONE =========="
