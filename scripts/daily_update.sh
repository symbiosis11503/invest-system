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

# Telegram 錯誤通知
TG_BOT_TOKEN="8585765797:AAGYUDdSSTgOmz2TS3d9zsjk4F7T_VdWzao"
TG_CHAT_ID="6927318445"
tg_notify() {
    local msg="$1"
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TG_CHAT_ID" \
        -d text="$msg" \
        -d parse_mode="HTML" > /dev/null 2>&1
}

TOTAL_STEPS=0
OK_STEPS=0

# 判斷是否為週末 (6=六, 0=日)
DAY_OF_WEEK=$(date +%w)
IS_WEEKEND=false
if [ "$DAY_OF_WEEK" -eq 0 ] || [ "$DAY_OF_WEEK" -eq 6 ]; then
    IS_WEEKEND=true
fi

log "========== DAILY UPDATE START (weekend=$IS_WEEKEND) =========="

if [ "$IS_WEEKEND" = false ]; then
    # 1. 台股行情 (yfinance 增量)
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
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
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Market data update failed"
        tg_notify "⚠️ 投資系統: 台股行情更新失敗"
    fi

    # 2. FinMind 籌碼更新
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
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
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Chip data update failed"
        tg_notify "⚠️ 投資系統: FinMind 籌碼更新失敗"
    fi

    # 2.5 TWSE OpenAPI (PER/EPS/月營收/公告)
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Updating TWSE indicators..."
    $VENV data/twse_fetcher.py >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: TWSE indicators update failed"
        tg_notify "⚠️ 投資系統: TWSE 指標更新失敗"
    fi
else
    log "Weekend — skipping market data / chip data / TWSE indicators"
fi

# 3. 新聞收集 + AI 分析 (每天都跑，含週末)
TOTAL_STEPS=$((TOTAL_STEPS + 1))
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
if [ $? -eq 0 ]; then
    OK_STEPS=$((OK_STEPS + 1))
else
    log "ERROR: News collection failed"
    tg_notify "⚠️ 投資系統: 新聞收集/分析失敗"
fi

# 3.5 處理未分析新聞積壓
TOTAL_STEPS=$((TOTAL_STEPS + 1))
log "Checking unanalyzed news backlog..."
cd "$INVEST_DIR"
$VENV -c "
from intelligence import analyze_news, get_conn
conn = get_conn()
backlog = conn.execute('SELECT COUNT(*) FROM news_intelligence WHERE sentiment IS NULL').fetchone()[0]
conn.close()
print(f'Unanalyzed backlog: {backlog}')
if backlog > 0:
    # 每次最多處理 100 則，避免 API rate limit
    batch = min(backlog, 100)
    a = analyze_news(limit=batch)
    print(f'Backlog analyzed: {a}/{backlog}')
    if backlog > batch:
        print(f'Remaining backlog: {backlog - a} (will continue next run)')
" >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    OK_STEPS=$((OK_STEPS + 1))
else
    log "ERROR: News backlog processing failed"
    tg_notify "⚠️ 投資系統: 新聞積壓處理失敗"
fi

if [ "$IS_WEEKEND" = false ]; then
    # 4. 自動分析 Top 10 異動股
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Running auto analysis..."
    $VENV scripts/auto_analysis.py >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Auto analysis failed"
        tg_notify "⚠️ 投資系統: 自動分析失敗"
    fi

    # 5. 每日報告
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Generating daily report..."
    $VENV daily_report.py >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Daily report generation failed"
        tg_notify "⚠️ 投資系統: 每日報告產生失敗"
    fi
else
    log "Weekend — skipping auto analysis & daily report"
fi

# 6. 股東紀念品更新 (每天都跑)
TOTAL_STEPS=$((TOTAL_STEPS + 1))
log "Updating shareholder gifts..."
cd "$INVEST_DIR"
$VENV -c "
from shareholder_gifts import fetch_gifts, get_all_gifts
count = fetch_gifts()
total = len(get_all_gifts())
print(f'Shareholder gifts: fetched {count}, total {total}')
" >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    OK_STEPS=$((OK_STEPS + 1))
else
    log "ERROR: Shareholder gifts update failed"
    tg_notify "⚠️ 投資系統: 股東紀念品更新失敗"
fi

# 7. 財經日曆更新 (每天都跑)
TOTAL_STEPS=$((TOTAL_STEPS + 1))
log "Updating economic calendar..."
cd "$INVEST_DIR"
$VENV -c "
from economic_calendar import fetch_and_store, init_calendar_table
init_calendar_table()
result = fetch_and_store(days=7)
print(f'Economic calendar: {result}')
" >> "$LOG" 2>&1
if [ $? -eq 0 ]; then
    OK_STEPS=$((OK_STEPS + 1))
else
    log "ERROR: Economic calendar update failed"
    tg_notify "⚠️ 投資系統: 財經日曆更新失敗"
fi

log "========== DAILY UPDATE DONE ($OK_STEPS/$TOTAL_STEPS OK) =========="

# 結尾摘要通知
if [ "$OK_STEPS" -eq "$TOTAL_STEPS" ]; then
    tg_notify "✅ 投資系統每日更新完成: $OK_STEPS/$TOTAL_STEPS 步驟成功"
else
    tg_notify "⚠️ 投資系統每日更新完成: $OK_STEPS/$TOTAL_STEPS 步驟成功 (有失敗項目，查看 log)"
fi
