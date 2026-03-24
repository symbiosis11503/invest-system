#!/bin/bash
# 投資系統每週報告 TG 推播 (每週日 20:00)
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HOME="/Users/wei"

INVEST_DIR="/Users/wei/Projects/invest-system"
LOG="$INVEST_DIR/logs/weekly_report.log"
mkdir -p "$INVEST_DIR/logs"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"; }

TG_BOT_TOKEN="8585765797:AAGYUDdSSTgOmz2TS3d9zsjk4F7T_VdWzao"
TG_CHAT_ID="6927318445"

tg_notify() {
    local msg="$1"
    local mode="${2:-MarkdownV2}"
    curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TG_CHAT_ID" \
        -d text="$msg" \
        -d parse_mode="$mode" > /dev/null 2>&1
}

# MarkdownV2 需要轉義的特殊字元
escape_md() {
    echo "$1" | sed -e 's/[_*[\]()~`>#+=|{}.!-]/\\&/g'
}

log "========== WEEKLY REPORT START =========="

# 取得週報 JSON
RAW=$(curl -s --max-time 30 "http://localhost:18900/api/weekly-summary")

if [ -z "$RAW" ] || echo "$RAW" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if 'markets' in d else 1)" 2>/dev/null; then
    : # JSON valid
else
    log "ERROR: API call failed or invalid JSON"
    tg_notify "⚠️ 投資系統週報: API 呼叫失敗" "HTML"
    exit 1
fi

# 用 python3 解析 JSON 並格式化 MarkdownV2 訊息
export WEEKLY_JSON="$RAW"
MSG=$(python3 << 'PYEOF'
import json, sys, re

def esc(s):
    """Escape MarkdownV2 special characters"""
    return re.sub(r'([_*\[\]()~`>#+=|{}.!\-])', r'\\\1', str(s))

import os
try:
    data = json.loads(os.environ.get('WEEKLY_JSON', '{}'))
except:
    print("解析失敗")
    sys.exit(1)

lines = []
lines.append("*📊 投資系統週報*")
lines.append("")

# 期間
period = data.get('period', '')
if period:
    lines.append(f"📅 {esc(period)}")
    lines.append("")

# 主要市場
markets = data.get('markets', [])
if markets:
    lines.append("*🌍 主要市場*")
    lines.append("```")
    lines.append(f"{'市場':<8} {'收盤':>10} {'週漲跌%':>8}")
    lines.append("─" * 28)
    for m in markets:
        name = m.get('name', m.get('symbol','?'))
        latest = m.get('latest', 0)
        chg = m.get('change_pct', 0)
        arrow = "▲" if chg > 0 else ("▼" if chg < 0 else "─")
        # 格式化數字
        if latest > 10000:
            price_str = f"{latest:,.0f}"
        elif latest > 100:
            price_str = f"{latest:,.1f}"
        else:
            price_str = f"{latest:,.2f}"
        lines.append(f"{name:<8} {price_str:>10} {arrow}{chg:+.2f}%")
    lines.append("```")
    lines.append("")

# 新聞情緒
sentiment = data.get('sentiment', {})
if sentiment:
    lines.append("*📰 新聞情緒*")
    bull = sentiment.get('bullish', {})
    bear = sentiment.get('bearish', {})
    neut = sentiment.get('neutral', {})
    bull_n = bull.get('count', 0)
    bear_n = bear.get('count', 0)
    neut_n = neut.get('count', 0)
    total = bull_n + bear_n + neut_n
    if total > 0:
        lines.append(f"🟢 看多 {esc(str(bull_n))} 則  🔴 看空 {esc(str(bear_n))} 則  ⚪ 中性 {esc(str(neut_n))} 則")
        ratio = bull_n / total * 100
        lines.append(f"多空比: {esc(f'{ratio:.0f}%')} 偏多" if ratio > 55 else
                     f"多空比: {esc(f'{ratio:.0f}%')} 偏空" if ratio < 45 else
                     f"多空比: {esc(f'{ratio:.0f}%')} 均衡")
    lines.append("")

# 法人資金流向
flow = data.get('institutional_flow', {})
if flow:
    lines.append("*💰 法人資金流向*")
    days = flow.get('trading_days', 0)
    lines.append(f"\\({esc(str(days))} 個交易日合計，單位: 億\\)")

    def fmt_b(v):
        """格式化為億元"""
        val = v / 100000000 if abs(v) > 10000 else v  # 如果已經是億就不除
        if abs(v) > 10000:
            return f"{val:+,.1f}"
        return f"{v:+,.0f}"

    lines.append(f"外資: {esc(fmt_b(flow.get('foreign_net', 0)))}")
    lines.append(f"投信: {esc(fmt_b(flow.get('trust_net', 0)))}")
    lines.append(f"自營: {esc(fmt_b(flow.get('dealer_net', 0)))}")
    lines.append(f"*合計: {esc(fmt_b(flow.get('total_net', 0)))}*")
    lines.append("")

# 泡沫/風險指標
bubble = data.get('bubble_summary', {})
if bubble:
    lines.append("*⚠️ 風險指標*")
    vix = bubble.get('vix', {})
    if vix:
        level_map = {'green': '🟢 低', 'yellow': '🟡 中', 'red': '🔴 高'}
        lvl = level_map.get(vix.get('level',''), '❓')
        lines.append(f"VIX: {esc(str(vix.get('value','')))} {lvl}")
    margin = bubble.get('margin_change', {})
    if margin:
        mc = margin.get('margin_balance_change', 0)
        sc = margin.get('short_balance_change', 0)
        lines.append(f"融資變化: {esc(f'{mc:+,}')}  融券變化: {esc(f'{sc:+,}')}")
    lines.append("")

# Top 新聞
top_news = data.get('top_news', [])
if top_news:
    lines.append("*📌 本週重點新聞*")
    for i, n in enumerate(top_news[:5], 1):
        title = n.get('title', '')[:40]
        score = n.get('score', '')
        sent = n.get('sentiment', '')
        emoji = '🟢' if sent == 'bullish' else ('🔴' if sent == 'bearish' else '⚪')
        lines.append(f"{esc(str(i))}\\. {emoji} {esc(title)}")
    lines.append("")

lines.append("_自動產生 by 投資系統_")

print('\n'.join(lines))
PYEOF
)

if [ -z "$MSG" ] || [ "$MSG" = "解析失敗" ]; then
    log "ERROR: Failed to format message"
    tg_notify "⚠️ 投資系統週報: 訊息格式化失敗" "HTML"
    exit 1
fi

# 發送 TG
RESULT=$(curl -s -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="$TG_CHAT_ID" \
    -d text="$MSG" \
    -d parse_mode="MarkdownV2")

if echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)" 2>/dev/null; then
    log "Weekly report sent successfully"
else
    log "ERROR: TG send failed: $RESULT"
    # fallback: 用 HTML 純文字發送
    PLAIN=$(echo "$RAW" | python3 -c "
import json, sys
data = json.load(sys.stdin)
lines = ['📊 投資系統週報', '']
for m in data.get('markets', []):
    name = m.get('name', m.get('symbol',''))
    chg = m.get('change_pct', 0)
    lines.append(f\"{name}: {chg:+.2f}%\")
lines.append('')
flow = data.get('institutional_flow', {})
if flow:
    lines.append(f\"外資: {flow.get('foreign_net',0):+,} / 投信: {flow.get('trust_net',0):+,}\")
print('\n'.join(lines))
")
    tg_notify "$PLAIN" "HTML"
    log "Fallback HTML message sent"
fi

log "========== WEEKLY REPORT DONE =========="
