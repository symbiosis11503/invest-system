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

# Telegram 錯誤通知 (從 .env 讀取)
if [ -f "$INVEST_DIR/.env" ]; then
    export $(grep -v '^#' "$INVEST_DIR/.env" | xargs)
fi
TG_BOT_TOKEN="${TG_BOT_TOKEN:-}"
TG_CHAT_ID="${TG_CHAT_ID:-}"
tg_notify() {
    local msg="$1"
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TG_CHAT_ID" \
        -d text="$msg" \
        -d parse_mode="HTML" > /dev/null 2>&1
}

TOTAL_STEPS=0
OK_STEPS=0

# 先更新休市日曆（每次都跑，確保最新）
$VENV -c "from data.twse_fetcher import fetch_holiday_schedule; fetch_holiday_schedule()" >> "$LOG" 2>&1

# 用 TWSE 休市日曆判斷是否為交易日（涵蓋週末 + 國定假日）
# 注意：必須丟棄 stdout，只看 exit code（0=交易日，1=非交易日）
$VENV data/twse_fetcher.py --check-trading-day > /dev/null 2>&1 && IS_TRADING=true || IS_TRADING=false

log "========== DAILY UPDATE START (trading_day=$IS_TRADING) =========="

if [ "$IS_TRADING" = "true" ]; then
    # 1. 台股行情 (yfinance 增量)
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Updating market data..."
    $VENV -c "
from data.fetcher import fetch_twse_daily, save_to_db
import datetime
today = datetime.date.today().strftime('%Y%m%d')
data = fetch_twse_daily(today)
if data:
    saved = save_to_db(data, source='twse')
    print(f'TWSE daily: {len(data)} rows fetched, {saved} saved')
else:
    print('No TWSE data (market closed?)')
" >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Market data update failed"
        tg_notify "⚠️ 投資系統: 台股行情更新失敗"
    fi

    # 1.5 國際指數 + 商品行情 (yfinance)
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Updating index & commodity data (yfinance)..."
    $VENV -c "
from data.fetcher import fetch_yfinance, save_to_db
symbols = ['^TWII', '^GSPC', '^DJI', '^IXIC', '^N225', '^HSI', 'GC=F', 'CL=F', 'BTC-USD', 'ETH-USD']
total = 0
for sym in symbols:
    try:
        data = fetch_yfinance(sym, period='5d')
        if data:
            saved = save_to_db(data, source='yfinance')
            total += saved
    except Exception as e:
        print(f'  {sym}: {e}')
print(f'Index/commodity: {total} rows saved ({len(symbols)} symbols)')
" >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Index data update failed"
        tg_notify "⚠️ 投資系統: 國際指數更新失敗"
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
    log "Non-trading day — skipping market data / chip data / TWSE indicators"
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

if [ "$IS_TRADING" = "true" ]; then
    # 3.7 融資融券（TWSE OpenAPI）
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Fetching margin trading data..."
    $VENV -c "
from data.twse_fetcher import fetch_margin_trading
count = fetch_margin_trading()
print(f'Margin trading: {count} stocks')
" >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Margin trading fetch failed"
        tg_notify "⚠️ 投資系統: 融資融券抓取失敗"
    fi

    # 3.8 分點主力抓取（重點股票近1日）
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Fetching broker trading data..."
    $VENV broker_trading.py 2330 2317 2454 2382 2881 2891 1301 2303 2002 3034 3008 3443 6669 2308 3231 5274 >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Broker trading data fetch failed"
        tg_notify "⚠️ 投資系統: 分點主力抓取失敗"
    fi

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
    log "Non-trading day — skipping auto analysis & daily report"
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

# 8. 分點主力更新 (交易日)
if [ "$IS_TRADING" = "true" ]; then
    TOTAL_STEPS=$((TOTAL_STEPS + 1))
    log "Updating broker trading data..."
    cd "$INVEST_DIR"
    $VENV -c "
from broker_trading import init_broker_table, fetch_broker_trading
import time
init_broker_table()
stocks = ['2330','2317','2454','2308','2412','2881','2882','2891','2886','3711',
          '2603','2609','2615','3037','2303','6505','1301','2002','3008','2345']
ok = 0
for s in stocks:
    r = fetch_broker_trading(s, period=1)
    if r: ok += 1
    time.sleep(0.3)
print(f'Broker trading: {ok}/{len(stocks)} stocks fetched')
" >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        OK_STEPS=$((OK_STEPS + 1))
    else
        log "ERROR: Broker trading update failed"
        tg_notify "⚠️ 投資系統: 分點主力更新失敗"
    fi
fi

# 數據完整性驗證（交易日）
if [ "$IS_TRADING" = "true" ]; then
    log "Running data integrity check..."
    $VENV -c "
import sqlite3, datetime
conn = sqlite3.connect('db/trades.db')
today = datetime.date.today().strftime('%Y-%m-%d')
checks = []
# 台股行情
n = conn.execute('SELECT COUNT(*) FROM market_data WHERE date=?', (today,)).fetchone()[0]
checks.append(f'行情:{n}筆')
if n < 100: print(f'⚠️ 台股行情偏少: {n} (預期 1000+)')
# 新聞
n = conn.execute(\"SELECT COUNT(*) FROM news_intelligence WHERE published_at >= ?\", (today,)).fetchone()[0]
checks.append(f'新聞:{n}筆')
# 法人
n = conn.execute('SELECT COUNT(*) FROM tw_institutional WHERE date=?', (today,)).fetchone()[0]
checks.append(f'法人:{n}筆')
conn.close()
print(f'[驗證] {\" | \".join(checks)}')
" >> "$LOG" 2>&1
fi

log "========== DAILY UPDATE DONE ($OK_STEPS/$TOTAL_STEPS OK) =========="

# 結尾摘要通知
if [ "$OK_STEPS" -eq "$TOTAL_STEPS" ]; then
    tg_notify "✅ 投資系統每日更新完成: $OK_STEPS/$TOTAL_STEPS 步驟成功"
    $VENV "$INVEST_DIR/push_notify.py" "投資系統更新完成" "$OK_STEPS/$TOTAL_STEPS 步驟成功" "/" "daily-update" 2>/dev/null
else
    tg_notify "⚠️ 投資系統每日更新完成: $OK_STEPS/$TOTAL_STEPS 步驟成功 (有失敗項目，查看 log)"
    $VENV "$INVEST_DIR/push_notify.py" "投資更新有失敗" "$OK_STEPS/$TOTAL_STEPS 成功，請檢查" "/" "daily-update" 2>/dev/null
fi
