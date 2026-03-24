"""投資系統 Web App — 家人手機瀏覽用"""
import sqlite3
import json
import math
import os
import functools
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, Response, send_file, render_template, send_from_directory, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")

# 載入 ai-hub 共用環境變數（含 Gemini API keys）
from config import load_env
load_env()
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=os.path.join(BASE_DIR, 'static'))
_START_TIME = time.time()


@app.route("/api/health")
@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "invest-system", "uptime": round(time.time() - _START_TIME, 1)})


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_sim_tables():
    """建立模擬交易相關表（如果不存在）"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sim_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name_zh TEXT,
            action TEXT NOT NULL,
            order_type TEXT DEFAULT 'limit',
            price REAL,
            quantity INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            filled_price REAL,
            filled_at TEXT,
            strategy TEXT,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS sim_portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            name_zh TEXT,
            avg_price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            current_price REAL,
            unrealized_pnl REAL,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS sim_account (
            id INTEGER PRIMARY KEY,
            cash REAL DEFAULT 1000000,
            total_value REAL DEFAULT 1000000,
            realized_pnl REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    # 確保帳戶有初始記錄
    existing = conn.execute("SELECT id FROM sim_account WHERE id=1").fetchone()
    if not existing:
        conn.execute("INSERT INTO sim_account (id, cash, total_value, realized_pnl) VALUES (1, 1000000, 1000000, 0)")
    conn.commit()
    conn.close()


init_sim_tables()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


# ── 簡易快取 ──────────────────────────────────────────
_cache = {}

def cached(ttl_seconds=300):
    """簡易記憶體快取，TTL 預設 5 分鐘"""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__name__}:{args}:{kwargs}"
            now = time.time()
            if key in _cache:
                val, ts = _cache[key]
                if now - ts < ttl_seconds:
                    return val
            result = fn(*args, **kwargs)
            _cache[key] = (result, now)
            return result
        return wrapper
    return decorator


# ── API ──────────────────────────────────────────────

@app.route("/api/backtests")
def api_backtests():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM backtest_results ORDER BY ts DESC").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/market/<symbol>")
def api_market(symbol):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 120",
        (symbol,)
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/trades")
def api_trades():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/symbols")
@cached(ttl_seconds=600)
def api_symbols():
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.symbol, COUNT(*) as count, MIN(m.date) as min_date, MAX(m.date) as max_date,
               COALESCE(sn.name_zh, m.symbol) as name_zh, sn.exchange, sn.category
        FROM market_data m
        LEFT JOIN symbol_names sn ON sn.symbol = m.symbol
        GROUP BY m.symbol ORDER BY m.symbol
    """).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/symbol-names")
@cached(ttl_seconds=3600)
def api_symbol_names():
    conn = get_conn()
    rows = conn.execute("SELECT symbol, name_zh, name_en, exchange, category FROM symbol_names ORDER BY symbol").fetchall()
    conn.close()
    return jsonify({r['symbol']: r['name_zh'] for r in rows})


@app.route("/api/intelligence")
def api_intelligence():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, title, summary, url, source, sentiment, score, keywords, reason,
               published_at, analyzed_at
        FROM news_intelligence
        WHERE sentiment IS NOT NULL AND sentiment != 'error'
        ORDER BY analyzed_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/mood")
def api_mood():
    conn = get_conn()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        """SELECT sentiment, score FROM news_intelligence
           WHERE analyzed_at > ? AND sentiment IN ('bullish', 'bearish', 'neutral')""",
        (cutoff,)
    ).fetchall()
    conn.close()

    if not rows:
        return jsonify({'total': 0, 'bullish': 0, 'bearish': 0, 'neutral': 0,
                        'avg_score': 0, 'mood': 'unknown'})

    counts = {'bullish': 0, 'bearish': 0, 'neutral': 0}
    score_sum = 0
    for r in rows:
        counts[r['sentiment']] = counts.get(r['sentiment'], 0) + 1
        score_sum += (r['score'] or 5)
    total = len(rows)
    avg_score = round(score_sum / total, 1)
    dominant = max(counts, key=counts.get)
    return jsonify({'total': total, 'bullish': counts['bullish'],
                    'bearish': counts['bearish'], 'neutral': counts['neutral'],
                    'avg_score': avg_score, 'mood': dominant})


@app.route("/api/tg-messages")
def api_tg_messages():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM tg_messages ORDER BY ts DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/tg-stats")
def api_tg_stats():
    conn = get_conn()
    groups = conn.execute("""
        SELECT group_name, COUNT(*) as msg_count,
               MAX(ts) as latest_ts
        FROM tg_messages GROUP BY group_name ORDER BY msg_count DESC
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = conn.execute(
        "SELECT COUNT(*) FROM tg_messages WHERE ts >= ?", (today,)
    ).fetchone()[0]
    conn.close()
    return jsonify({
        "total": total,
        "today": today_count,
        "groups": rows_to_dicts(groups),
    })


@app.route("/trading")
def trading():
    return send_file(os.path.join(BASE_DIR, "trading.html"))


# ── HTML ─────────────────────────────────────────────

STYLE = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     padding:12px;max-width:960px;margin:0 auto;font-size:14px}
h1{font-size:1.3rem;margin-bottom:12px;color:#38bdf8}
h2{font-size:1.1rem;margin:16px 0 8px;color:#7dd3fc}
a{color:#38bdf8;text-decoration:none}
a:hover{text-decoration:underline}
.card{background:#1e293b;border-radius:10px;padding:14px;margin-bottom:12px;
      border:1px solid #334155;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:6px 8px;border-bottom:1px solid #475569;color:#94a3b8;white-space:nowrap}
td{padding:6px 8px;border-bottom:1px solid #1e293b;white-space:nowrap}
.pos{color:#4ade80}.neg{color:#f87171}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;
       background:#334155;color:#cbd5e1;margin:2px}
nav{display:flex;gap:12px;margin-bottom:14px;flex-wrap:wrap}
nav a{background:#1e293b;padding:6px 14px;border-radius:6px;border:1px solid #334155}
nav a:hover,nav a.active{background:#334155}
.empty{color:#64748b;padding:20px;text-align:center}
canvas{width:100%;max-height:360px}
@media(max-width:600px){body{padding:8px}table{font-size:12px}th,td{padding:4px 5px}}
"""

NAV = """<nav>
<a href="/">首頁</a>
<a href="/trading">看盤</a>
<a href="/backtests">回測結果</a>
<a href="/intelligence">市場情報</a>
<a href="/chipdata">籌碼分析</a>
<a href="/messages">群組監聯</a>
<select onchange="if(this.value)location.href='/market/'+this.value" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:4px 8px;font-size:13px;cursor:pointer;min-height:36px">
<option value="">📊 行情查詢</option>
{symbol_options}
</select>
</nav>"""


def make_nav(active=""):
    conn = get_conn()
    symbols = conn.execute("""
        SELECT symbol, source, COUNT(*) as cnt FROM market_data
        GROUP BY symbol ORDER BY source, symbol
    """).fetchall()
    conn.close()

    categories = {}
    source_names = {'twse': '🇹🇼 台股', 'taifex': '📈 期貨', 'yfinance': '🌍 國際', 'tpex_otc': '🏢 上櫃', 'tpex_emerging': '🌱 興櫃'}
    for r in symbols:
        cat = source_names.get(r['source'], '其他')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r['symbol'])

    options = ""
    for cat, syms in categories.items():
        options += f'<optgroup label="{cat}">'
        for s in syms:
            options += f'<option value="{s}">{s}</option>'
        options += '</optgroup>'

    return NAV.format(symbol_options=options)


def page(title, body):
    return f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — 投資系統</title>
<style>{STYLE}</style></head>
<body>{make_nav()}<h1>{title}</h1>{body}</body></html>"""


# ── 首頁 ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template('index.html')


def index_old():
    conn = get_conn()

    # 回測摘要
    bts = conn.execute("SELECT * FROM backtest_results ORDER BY ts DESC LIMIT 5").fetchall()
    bt_html = ""
    if bts:
        bt_rows = ""
        for b in bts:
            ret = b["total_return"] or 0
            cls = "pos" if ret >= 0 else "neg"
            bt_rows += f"""<tr>
                <td>{b["strategy"]}</td><td>{b["symbol"]}</td>
                <td class="{cls}">{ret:.2f}%</td>
                <td>{(b["sharpe_ratio"] or 0):.2f}</td>
                <td>{b["ts"][:16]}</td></tr>"""
        bt_html = f"""<div class="card"><h2>最近回測</h2>
            <table><tr><th>策略</th><th>標的</th><th>報酬率</th><th>Sharpe</th><th>時間</th></tr>
            {bt_rows}</table></div>"""
    else:
        bt_html = '<div class="card empty">尚無回測紀錄</div>'

    # 標的統計
    stats = conn.execute("""
        SELECT symbol, COUNT(*) as cnt, MIN(date) as first_date, MAX(date) as last_date
        FROM market_data GROUP BY symbol ORDER BY symbol
    """).fetchall()
    stat_html = ""
    if stats:
        stat_rows = ""
        for s in stats:
            stat_rows += f"""<tr><td><a href="/market/{s["symbol"]}">{s["symbol"]}</a></td>
                <td>{s["cnt"]}</td><td>{s["first_date"]}</td><td>{s["last_date"]}</td></tr>"""
        stat_html = f"""<div class="card"><h2>行情資料</h2>
            <table><tr><th>標的</th><th>筆數</th><th>起始</th><th>最新</th></tr>
            {stat_rows}</table></div>"""

    # 交易紀錄
    trades = conn.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT 10").fetchall()
    trade_html = ""
    if trades:
        t_rows = ""
        for t in trades:
            pnl = t["pnl"] or 0
            cls = "pos" if pnl >= 0 else "neg"
            t_rows += f"""<tr><td>{t["strategy"]}</td><td>{t["symbol"]}</td>
                <td>{t["action"]}</td><td>{t["price"]:.2f}</td><td>{t["size"]}</td>
                <td class="{cls}">{pnl:.2f}</td><td>{t["ts"][:16]}</td></tr>"""
        trade_html = f"""<div class="card"><h2>最近交易</h2>
            <table><tr><th>策略</th><th>標的</th><th>方向</th><th>價格</th><th>數量</th><th>損益</th><th>時間</th></tr>
            {t_rows}</table></div>"""
    else:
        trade_html = '<div class="card empty">尚無交易紀錄</div>'

    # 市場情緒卡片
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    mood_rows = conn.execute(
        """SELECT sentiment, score FROM news_intelligence
           WHERE analyzed_at > ? AND sentiment IN ('bullish', 'bearish', 'neutral')""",
        (cutoff,)
    ).fetchall()
    mood_html = ""
    if mood_rows:
        mc = {'bullish': 0, 'bearish': 0, 'neutral': 0}
        ms = 0
        for mr in mood_rows:
            mc[mr['sentiment']] = mc.get(mr['sentiment'], 0) + 1
            ms += (mr['score'] or 5)
        mt = len(mood_rows)
        mavg = round(ms / mt, 1)
        dominant = max(mc, key=mc.get)
        mood_colors = {'bullish': '#f87171', 'bearish': '#4ade80', 'neutral': '#94a3b8'}
        mood_labels = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性'}
        dc = mood_colors[dominant]
        dl = mood_labels[dominant]
        mood_html = f"""<a href="/intelligence" style="text-decoration:none"><div class="card" style="display:flex;align-items:center;gap:16px;cursor:pointer">
            <div style="text-align:center;min-width:80px">
                <div style="font-size:2rem;font-weight:bold;color:{dc}">{dl}</div>
                <div style="color:#94a3b8;font-size:12px">市場情緒</div>
            </div>
            <div style="flex:1;font-size:13px;color:#cbd5e1">
                <span style="color:#f87171">看多 {mc['bullish']}</span> /
                <span style="color:#4ade80">看空 {mc['bearish']}</span> /
                <span style="color:#94a3b8">中性 {mc['neutral']}</span>
                &nbsp;|&nbsp; 平均分數 {mavg}/10 &nbsp;|&nbsp; 共 {mt} 則
            </div>
        </div></a>"""
    else:
        mood_html = ""

    # TG 監聽卡片
    tg_total = conn.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    tg_groups = conn.execute("SELECT COUNT(DISTINCT group_name) FROM tg_messages").fetchone()[0]
    tg_html = ""
    if tg_total > 0:
        tg_html = f"""<a href="/messages" style="text-decoration:none"><div class="card" style="display:flex;align-items:center;gap:16px;cursor:pointer">
            <div style="font-size:2rem">📨</div>
            <div style="color:#cbd5e1;font-size:13px">
                TG 監聽：<b>{tg_total}</b> 則訊息 / <b>{tg_groups}</b> 個群組
            </div>
        </div></a>"""

    # 法人動向卡片
    chip_html = ""
    try:
        latest_date = conn.execute("SELECT MAX(date) FROM tw_institutional").fetchone()[0]
        if latest_date:
            inst_rows = conn.execute("""
                SELECT symbol, foreign_net, trust_net, total_net
                FROM tw_institutional WHERE date = ?
                ORDER BY ABS(total_net) DESC LIMIT 5
            """, (latest_date,)).fetchall()
            if inst_rows:
                items = ""
                for r in inst_rows:
                    net = r['total_net']
                    cls = "pos" if net > 0 else "neg"
                    items += f'<span style="margin-right:12px"><b>{r["symbol"]}</b> <span class="{cls}">{net:+,}</span></span>'
                chip_html = f"""<a href="/chipdata" style="text-decoration:none"><div class="card" style="display:flex;align-items:center;gap:16px;cursor:pointer">
                    <div style="font-size:2rem">🏦</div>
                    <div style="color:#cbd5e1;font-size:13px">
                        法人動向 ({latest_date})：{items}
                    </div>
                </div></a>"""
    except Exception:
        pass

    conn.close()
    return page("儀表板", mood_html + chip_html + tg_html + bt_html + stat_html + trade_html)


# ── 回測結果 ─────────────────────────────────────────

@app.route("/backtests")
def backtests():
    return render_template('backtests.html')


def backtests_old():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM backtest_results ORDER BY ts DESC").fetchall()
    conn.close()

    if not rows:
        return page("回測結果", '<div class="card empty">尚無回測紀錄</div>')

    trs = ""
    for b in rows:
        ret = b["total_return"] or 0
        dd = b["max_drawdown"] or 0
        sr = b["sharpe_ratio"] or 0
        wr = b["win_rate"] or 0
        cls_ret = "pos" if ret >= 0 else "neg"
        trs += f"""<tr>
            <td>{b["strategy"]}</td><td>{b["symbol"]}</td>
            <td>{b["start_date"] or "N/A"}</td><td>{b["end_date"] or "N/A"}</td>
            <td>{(b["initial_cash"] or 0):,.0f}</td>
            <td>{(b["final_value"] or 0):,.0f}</td>
            <td class="{cls_ret}">{ret:.2f}%</td>
            <td class="neg">{dd:.2f}%</td>
            <td>{sr:.2f}</td>
            <td>{wr:.1f}%</td>
            <td>{b["total_trades"] or 0}</td>
            <td>{b["ts"][:16]}</td></tr>"""

    body = f"""<div class="card"><table>
        <tr><th>策略</th><th>標的</th><th>開始</th><th>結束</th>
        <th>初始資金</th><th>最終價值</th><th>報酬率</th><th>最大回撤</th>
        <th>Sharpe</th><th>勝率</th><th>交易次數</th><th>時間</th></tr>
        {trs}</table></div>"""
    return page("回測結果", body)


# ── 行情頁 ───────────────────────────────────────────

@app.route("/market/<symbol>")
def market(symbol):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 120",
        (symbol,)
    ).fetchall()
    conn.close()

    if not rows:
        return page(f"{symbol} 行情", '<div class="card empty">無此標的資料</div>')

    # 表格（最近 20 筆）
    trs = ""
    for r in rows[:20]:
        chg = (r["close"] or 0) - (r["open"] or 0)
        cls = "pos" if chg >= 0 else "neg"
        trs += f"""<tr class="{cls}">
            <td>{r["date"]}</td><td>{r["open"]:.2f}</td><td>{r["high"]:.2f}</td>
            <td>{r["low"]:.2f}</td><td>{r["close"]:.2f}</td>
            <td>{(r["volume"] or 0):,}</td></tr>"""

    table = f"""<div class="card"><h2>最近行情</h2><table>
        <tr><th>日期</th><th>開盤</th><th>最高</th><th>最低</th><th>收盤</th><th>成交量</th></tr>
        {trs}</table></div>"""

    # K 線圖資料（時間正序）
    chart_data = []
    for r in reversed(rows):
        chart_data.append({
            "d": r["date"],
            "o": r["open"] or 0,
            "h": r["high"] or 0,
            "l": r["low"] or 0,
            "c": r["close"] or 0
        })
    data_json = json.dumps(chart_data)

    chart = f"""<div class="card"><h2>K 線圖</h2>
    <canvas id="kc" height="360"></canvas>
    <script>
    (function(){{
      const D={data_json};
      if(!D.length) return;
      const cv=document.getElementById('kc');
      const W=cv.parentElement.clientWidth-28;
      cv.width=W; cv.height=360;
      const ctx=cv.getContext('2d');
      const pad={{t:20,b:30,l:60,r:10}};
      const cw=W-pad.l-pad.r, ch=360-pad.t-pad.b;
      const n=D.length;
      const bw=Math.max(2,Math.floor(cw/n*0.7));
      const gap=Math.max(1,Math.floor(cw/n*0.15));

      let mn=Infinity, mx=-Infinity;
      D.forEach(d=>{{ if(d.l<mn)mn=d.l; if(d.h>mx)mx=d.h; }});
      const rng=mx-mn||1;
      mn-=rng*0.05; mx+=rng*0.05;
      const ry=ch/(mx-mn);

      function y(v){{ return pad.t+ch-(v-mn)*ry; }}

      // grid
      ctx.strokeStyle='#334155'; ctx.lineWidth=0.5;
      ctx.fillStyle='#64748b'; ctx.font='11px sans-serif'; ctx.textAlign='right';
      for(let i=0;i<=5;i++){{
        const v=mn+(mx-mn)*i/5;
        const yy=y(v);
        ctx.beginPath(); ctx.moveTo(pad.l,yy); ctx.lineTo(W-pad.r,yy); ctx.stroke();
        ctx.fillText(v.toFixed(0),pad.l-4,yy+4);
      }}

      // candles
      D.forEach((d,i)=>{{
        const x=pad.l+i*(bw+gap)+gap;
        const up=d.c>=d.o;
        ctx.strokeStyle=up?'#4ade80':'#f87171';
        ctx.fillStyle=up?'#4ade80':'#f87171';
        // wick
        ctx.beginPath();
        ctx.moveTo(x+bw/2,y(d.h));
        ctx.lineTo(x+bw/2,y(d.l));
        ctx.stroke();
        // body
        const top=y(Math.max(d.o,d.c));
        const bot=y(Math.min(d.o,d.c));
        const bh=Math.max(1,bot-top);
        if(up){{ctx.strokeRect(x,top,bw,bh);}}
        else{{ctx.fillRect(x,top,bw,bh);}}
      }});

      // x labels
      ctx.fillStyle='#64748b'; ctx.textAlign='center'; ctx.font='10px sans-serif';
      const step=Math.max(1,Math.floor(n/6));
      for(let i=0;i<n;i+=step){{
        const x=pad.l+i*(bw+gap)+gap+bw/2;
        ctx.fillText(D[i].d.slice(5),x,360-6);
      }}
    }})();
    </script></div>"""

    return page(f"{symbol} 行情", chart + table)


# ── 市場情報頁 ─────────────────────────────────────────

@app.route("/intelligence")
def intelligence():
    return render_template('intelligence.html')


def intelligence_old():
    conn = get_conn()

    # 情緒摘要（24h）
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    mood_rows = conn.execute(
        """SELECT sentiment, score FROM news_intelligence
           WHERE analyzed_at > ? AND sentiment IN ('bullish', 'bearish', 'neutral')""",
        (cutoff,)
    ).fetchall()

    if mood_rows:
        mc = {'bullish': 0, 'bearish': 0, 'neutral': 0}
        ms = 0
        for mr in mood_rows:
            mc[mr['sentiment']] = mc.get(mr['sentiment'], 0) + 1
            ms += (mr['score'] or 5)
        mt = len(mood_rows)
        mavg = round(ms / mt, 1)
        dominant = max(mc, key=mc.get)
        mood_colors = {'bullish': '#f87171', 'bearish': '#4ade80', 'neutral': '#94a3b8'}
        mood_labels = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性'}
        dc = mood_colors[dominant]
        dl = mood_labels[dominant]

        # 圓餅圖用 SVG
        def pie_svg(b, br, n, total):
            if total == 0:
                return ''
            items = [('#f87171', b), ('#4ade80', br), ('#94a3b8', n)]
            svg = '<svg viewBox="0 0 100 100" width="140" height="140" style="transform:rotate(-90deg)">'
            offset = 0
            for color, count in items:
                if count == 0:
                    continue
                pct = count / total * 100
                r = 40
                circ = 2 * 3.14159 * r
                dash = circ * pct / 100
                gap = circ - dash
                svg += (f'<circle cx="50" cy="50" r="{r}" fill="none" '
                        f'stroke="{color}" stroke-width="18" '
                        f'stroke-dasharray="{dash:.1f} {gap:.1f}" '
                        f'stroke-dashoffset="{-offset * circ / 100:.1f}"/>')
                offset += pct
            svg += '</svg>'
            return svg

        pie = pie_svg(mc['bullish'], mc['bearish'], mc['neutral'], mt)

        mood_card = f"""<div class="card" style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;justify-content:center">
            <div style="text-align:center">{pie}</div>
            <div style="flex:1;min-width:200px">
                <div style="font-size:1.6rem;font-weight:bold;color:{dc};margin-bottom:8px">主導情緒：{dl}</div>
                <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:8px">
                    <div style="text-align:center"><div style="font-size:1.8rem;font-weight:bold;color:#f87171">{mc['bullish']}</div><div style="color:#94a3b8;font-size:12px">看多</div></div>
                    <div style="text-align:center"><div style="font-size:1.8rem;font-weight:bold;color:#4ade80">{mc['bearish']}</div><div style="color:#94a3b8;font-size:12px">看空</div></div>
                    <div style="text-align:center"><div style="font-size:1.8rem;font-weight:bold;color:#94a3b8">{mc['neutral']}</div><div style="color:#94a3b8;font-size:12px">中性</div></div>
                </div>
                <div style="color:#cbd5e1;font-size:13px">平均分數 <b>{mavg}</b>/10 &nbsp;|&nbsp; 近 24 小時共 <b>{mt}</b> 則</div>
            </div>
        </div>"""
    else:
        mood_card = '<div class="card empty">近 24 小時無分析資料</div>'

    # 新聞列表（最新 50 則已分析）
    rows = conn.execute("""
        SELECT title, url, sentiment, score, reason, published_at, analyzed_at
        FROM news_intelligence
        WHERE sentiment IS NOT NULL AND sentiment != 'error'
        ORDER BY analyzed_at DESC LIMIT 50
    """).fetchall()
    conn.close()

    if rows:
        sent_style = {
            'bullish': 'color:#f87171;font-weight:bold',
            'bearish': 'color:#4ade80;font-weight:bold',
            'neutral': 'color:#94a3b8',
        }
        sent_label = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性'}
        trs = ""
        for r in rows:
            s = r['sentiment'] or 'neutral'
            ss = sent_style.get(s, '')
            sl = sent_label.get(s, s)
            sc = r['score'] or 0
            reason = r['reason'] or ''
            raw_pub = r['published_at'] or ''
            # 嘗試解析各種日期格式為 YYYY-MM-DD
            pub = raw_pub[:10]
            try:
                from email.utils import parsedate_to_datetime
                pub = parsedate_to_datetime(raw_pub).strftime('%Y-%m-%d')
            except Exception:
                if 'T' in raw_pub:
                    pub = raw_pub[:10]
            title_safe = (r['title'] or '').replace('<', '&lt;').replace('>', '&gt;')
            url = r['url'] or '#'
            trs += f"""<tr>
                <td style="white-space:normal;min-width:80px">{pub}</td>
                <td style="white-space:normal"><a href="{url}" target="_blank" rel="noopener">{title_safe}</a></td>
                <td style="{ss}">{sl}</td>
                <td>{sc}</td>
                <td style="white-space:normal;color:#94a3b8;font-size:12px">{reason}</td></tr>"""
        news_html = f"""<div class="card"><h2>新聞列表</h2><table>
            <tr><th>時間</th><th>標題</th><th>情感</th><th>分數</th><th>理由</th></tr>
            {trs}</table></div>"""
    else:
        news_html = '<div class="card empty">尚無已分析新聞</div>'

    return page("市場情報", mood_card + news_html)


# ── 群組監聽頁 ───────────────────────────────────────

@app.route("/messages")
def messages():
    return render_template('messages.html')


def messages_old():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = conn.execute(
        "SELECT COUNT(*) FROM tg_messages WHERE ts >= ?", (today,)
    ).fetchone()[0]
    groups = conn.execute(
        "SELECT DISTINCT group_name FROM tg_messages ORDER BY group_name"
    ).fetchall()
    group_count = len(groups)
    msgs = conn.execute(
        "SELECT * FROM tg_messages ORDER BY ts DESC LIMIT 100"
    ).fetchall()
    conn.close()

    # 統計卡片
    stats_html = f"""<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px">
        <div class="card" style="flex:1;min-width:120px;text-align:center">
            <div style="font-size:1.8rem;font-weight:bold;color:#38bdf8">{total}</div>
            <div style="color:#94a3b8;font-size:12px">總訊息數</div>
        </div>
        <div class="card" style="flex:1;min-width:120px;text-align:center">
            <div style="font-size:1.8rem;font-weight:bold;color:#a78bfa">{group_count}</div>
            <div style="color:#94a3b8;font-size:12px">活躍群組</div>
        </div>
        <div class="card" style="flex:1;min-width:120px;text-align:center">
            <div style="font-size:1.8rem;font-weight:bold;color:#4ade80">{today_count}</div>
            <div style="color:#94a3b8;font-size:12px">今日訊息</div>
        </div>
    </div>"""

    # 群組篩選
    opts = '<option value="">全部群組</option>'
    for g in groups:
        name = (g['group_name'] or '').replace('"', '&quot;')
        opts += f'<option value="{name}">{name}</option>'
    filter_html = f"""<div style="margin-bottom:14px">
        <select id="groupFilter" onchange="filterMsgs()" style="background:#1e293b;color:#e2e8f0;
            border:1px solid #475569;border-radius:6px;padding:8px 12px;font-size:14px;width:100%;max-width:320px">
            {opts}
        </select>
    </div>"""

    # 訊息列表
    rows_html = ""
    for m in msgs:
        ts = (m['ts'] or '')[:19]
        gn = (m['group_name'] or '').replace('<', '&lt;')
        sn = (m['sender_name'] or '').replace('<', '&lt;')
        txt = (m['message_text'] or '').replace('<', '&lt;').replace('>', '&gt;')
        rows_html += f"""<tr data-group="{(m['group_name'] or '').replace('"', '&quot;')}">
            <td style="white-space:nowrap;color:#94a3b8">{ts}</td>
            <td><span class="badge" style="background:#312e81;color:#a78bfa">{gn}</span></td>
            <td style="color:#7dd3fc">{sn}</td>
            <td style="white-space:normal;max-width:400px;word-break:break-all">{txt}</td></tr>"""

    table_html = f"""<div class="card"><table id="msgTable">
        <tr><th>時間</th><th>群組</th><th>發送者</th><th>內容</th></tr>
        {rows_html}</table></div>"""

    script = """<script>
    function filterMsgs(){
        var v=document.getElementById('groupFilter').value;
        var rows=document.querySelectorAll('#msgTable tr[data-group]');
        rows.forEach(function(r){r.style.display=(!v||r.getAttribute('data-group')===v)?'':'none';});
    }
    setTimeout(function(){location.reload();},30000);
    </script>"""

    return page("群組監聽", stats_html + filter_html + table_html + script)


@app.route("/api/chipdata/<symbol>")
def api_chipdata(symbol):
    """個股籌碼面資料：法人/融資券/PER/月營收"""
    conn = get_conn()
    days = int(os.environ.get("CHIP_DAYS", 60))
    inst = conn.execute(
        "SELECT * FROM tw_institutional WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, days)).fetchall()
    margin = conn.execute(
        "SELECT * FROM tw_margin WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, days)).fetchall()
    per = conn.execute(
        "SELECT * FROM tw_per WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, days)).fetchall()
    revenue = conn.execute(
        "SELECT * FROM tw_revenue WHERE symbol=? ORDER BY date DESC LIMIT 24",
        (symbol,)).fetchall()
    eps = conn.execute(
        "SELECT * FROM tw_eps WHERE symbol=? ORDER BY year DESC, quarter DESC LIMIT 8",
        (symbol,)).fetchall()
    # 計算新指標
    # 1. 法人連續買超天數
    consecutive_buy = 0
    for row in inst:
        if row["total_net"] and row["total_net"] > 0:
            consecutive_buy += 1
        else:
            break

    # 2. 營收連續成長月數
    consecutive_growth = 0
    for row in revenue:
        if row["revenue_yoy"] and row["revenue_yoy"] > 0:
            consecutive_growth += 1
        else:
            break

    # 3. 融資減少（籌碼洗淨訊號）+ 股價上漲
    chip_clean = False
    if len(margin) >= 5:
        # 近5日融資餘額持續減少
        mb = [r["margin_balance"] for r in margin[:5] if r["margin_balance"]]
        if len(mb) >= 2:
            margin_decreasing = all(mb[i] <= mb[i+1] for i in range(len(mb)-1))
            # 加上股價是否上漲
            price_rows = conn.execute(
                "SELECT close FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 5",
                (symbol,)).fetchall()
            price_up = False
            if len(price_rows) >= 2:
                price_up = (price_rows[0]["close"] or 0) > (price_rows[-1]["close"] or 0)
            chip_clean = margin_decreasing and price_up

    # 4. 近4季 EPS 合計（年化 EPS）
    annual_eps = None
    if eps:
        recent_eps = [r["eps"] for r in eps[:4] if r["eps"] is not None]
        if recent_eps:
            annual_eps = round(sum(recent_eps), 2)

    conn.close()
    return jsonify({
        "symbol": symbol,
        "institutional": rows_to_dicts(inst),
        "margin": rows_to_dicts(margin),
        "per": rows_to_dicts(per),
        "revenue": rows_to_dicts(revenue),
        "eps": rows_to_dicts(eps),
        "indicators": {
            "consecutive_buy_days": consecutive_buy,
            "consecutive_growth_months": consecutive_growth,
            "chip_clean_signal": chip_clean,
            "annual_eps": annual_eps,
        },
    })


@app.route("/api/screener/vix-panic")
def api_vix_screener():
    """VIX 恐慌篩選：VIX > 30 時找低 PER 高殖利率股"""
    conn = get_conn()
    vix = conn.execute("SELECT close FROM market_data WHERE symbol='^VIX' ORDER BY date DESC LIMIT 1").fetchone()
    vix_val = vix["close"] if vix else 0

    results = []
    if vix_val > 30:
        # Find stocks with low PER and high dividend yield
        stocks = conn.execute("""
            SELECT p.symbol, p.per, p.pbr, p.dividend_yield, p.date,
                   n.name_zh
            FROM tw_per p
            LEFT JOIN symbol_names n ON n.symbol = p.symbol
            WHERE p.date = (SELECT MAX(date) FROM tw_per WHERE symbol = p.symbol)
            AND CAST(p.per AS REAL) > 0 AND CAST(p.per AS REAL) < 15
            AND CAST(p.dividend_yield AS REAL) > 3
            ORDER BY CAST(p.dividend_yield AS REAL) DESC
            LIMIT 20
        """).fetchall()
        results = rows_to_dicts(stocks)

    conn.close()
    return jsonify({"vix": vix_val, "panic_mode": vix_val > 30, "stocks": results})


@app.route("/api/top-flow")
def api_top_flow():
    """法人買賣超 Top 10（最新日期，按淨買超絕對值排序）"""
    conn = get_conn()
    latest_date = conn.execute("SELECT MAX(date) FROM tw_institutional").fetchone()[0]
    if not latest_date:
        conn.close()
        return jsonify({"date": None, "top_buy": [], "top_sell": []})

    top_buy = conn.execute("""
        SELECT i.symbol, i.foreign_net, i.trust_net, i.dealer_net, i.total_net, i.date,
               COALESCE(n.name_zh, i.symbol) as name_zh
        FROM tw_institutional i
        LEFT JOIN symbol_names n ON n.symbol = i.symbol
        WHERE i.date = ? AND i.total_net > 0
        ORDER BY i.total_net DESC LIMIT 10
    """, (latest_date,)).fetchall()

    top_sell = conn.execute("""
        SELECT i.symbol, i.foreign_net, i.trust_net, i.dealer_net, i.total_net, i.date,
               COALESCE(n.name_zh, i.symbol) as name_zh
        FROM tw_institutional i
        LEFT JOIN symbol_names n ON n.symbol = i.symbol
        WHERE i.date = ? AND i.total_net < 0
        ORDER BY i.total_net ASC LIMIT 10
    """, (latest_date,)).fetchall()

    conn.close()
    return jsonify({
        "date": latest_date,
        "top_buy": rows_to_dicts(top_buy),
        "top_sell": rows_to_dicts(top_sell),
    })


@app.route("/api/eps-leaders")
def api_eps_leaders():
    """EPS 排行 — 最新季度 EPS Top 20"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.symbol, e.year, e.quarter, e.eps, e.revenue, e.profit, e.date,
               COALESCE(n.name_zh, e.symbol) as name_zh,
               p.per, p.pbr, p.dividend_yield
        FROM tw_eps e
        LEFT JOIN symbol_names n ON n.symbol = e.symbol
        LEFT JOIN (
            SELECT symbol, per, pbr, dividend_yield,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
            FROM tw_per
        ) p ON p.symbol = e.symbol AND p.rn = 1
        WHERE e.eps IS NOT NULL
        ORDER BY e.eps DESC LIMIT 20
    """).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/screener/high-yield")
def api_high_yield_screener():
    """高殖利率篩選：殖利率 > 5% 且 PER < 20 的價值股"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.symbol, p.per, p.pbr, p.dividend_yield, p.date,
               COALESCE(n.name_zh, p.symbol) as name_zh,
               e.eps
        FROM tw_per p
        LEFT JOIN symbol_names n ON n.symbol = p.symbol
        LEFT JOIN tw_eps e ON e.symbol = p.symbol
        WHERE p.date = (SELECT MAX(date) FROM tw_per WHERE symbol = p.symbol)
        AND CAST(p.dividend_yield AS REAL) > 5
        AND CAST(p.per AS REAL) > 0 AND CAST(p.per AS REAL) < 20
        ORDER BY CAST(p.dividend_yield AS REAL) DESC
        LIMIT 30
    """).fetchall()
    conn.close()
    return jsonify({"count": len(rows), "stocks": rows_to_dicts(rows)})


@app.route("/api/screener/foreign-buy-streak")
def api_foreign_buy_streak():
    """外資連買排行：外資連續淨買超天數最多的股票"""
    conn = get_conn()
    # 取所有有籌碼的股票
    symbols = conn.execute(
        "SELECT DISTINCT symbol FROM tw_institutional ORDER BY symbol"
    ).fetchall()

    streaks = []
    for row in symbols:
        sym = row["symbol"]
        data = conn.execute(
            "SELECT date, foreign_net FROM tw_institutional WHERE symbol=? ORDER BY date DESC LIMIT 30",
            (sym,)).fetchall()
        streak = 0
        total_net = 0
        for d in data:
            if d["foreign_net"] and d["foreign_net"] > 0:
                streak += 1
                total_net += d["foreign_net"]
            else:
                break
        if streak >= 3:
            streaks.append({"symbol": sym, "streak_days": streak, "total_net": total_net})

    # 加中文名
    name_rows = conn.execute("SELECT symbol, name_zh FROM symbol_names").fetchall()
    names = {r["symbol"]: r["name_zh"] for r in name_rows}
    for s in streaks:
        s["name_zh"] = names.get(s["symbol"], s["symbol"])

    conn.close()
    streaks.sort(key=lambda x: x["streak_days"], reverse=True)
    return jsonify({"count": len(streaks), "stocks": streaks[:20]})


@app.route("/api/screener/revenue-growth")
def api_revenue_growth_screener():
    """營收連續成長篩選：月營收 YoY 連續正成長"""
    conn = get_conn()
    symbols = conn.execute(
        "SELECT DISTINCT symbol FROM tw_revenue ORDER BY symbol"
    ).fetchall()

    growers = []
    for row in symbols:
        sym = row["symbol"]
        data = conn.execute(
            "SELECT date, revenue_yoy FROM tw_revenue WHERE symbol=? ORDER BY date DESC LIMIT 12",
            (sym,)).fetchall()
        streak = 0
        for d in data:
            if d["revenue_yoy"] and d["revenue_yoy"] > 0:
                streak += 1
            else:
                break
        if streak >= 3:
            latest_yoy = data[0]["revenue_yoy"] if data else 0
            growers.append({"symbol": sym, "growth_months": streak, "latest_yoy": round(latest_yoy, 1)})

    name_rows = conn.execute("SELECT symbol, name_zh FROM symbol_names").fetchall()
    names = {r["symbol"]: r["name_zh"] for r in name_rows}
    for g in growers:
        g["name_zh"] = names.get(g["symbol"], g["symbol"])

    conn.close()
    growers.sort(key=lambda x: x["growth_months"], reverse=True)
    return jsonify({"count": len(growers), "stocks": growers[:20]})


@app.route("/api/chipdata")
def api_chipdata_list():
    """有籌碼資料的股票清單"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, COUNT(*) as days, MIN(date) as from_date, MAX(date) as to_date
        FROM tw_institutional GROUP BY symbol ORDER BY symbol
    """).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/screener")
def screener_page():
    return render_template('screener.html')


@app.route("/chipdata")
@app.route("/chipdata/<symbol>")
def chipdata_page(symbol=None):
    return render_template('chipdata.html')


def chipdata_page_old(symbol=None):
    conn = get_conn()
    stocks = conn.execute(
        "SELECT DISTINCT symbol FROM tw_institutional ORDER BY symbol"
    ).fetchall()
    stock_list = [r['symbol'] for r in stocks]

    if not symbol and stock_list:
        symbol = stock_list[0]

    # 取最近 30 天法人
    inst = []
    margin_data = []
    per_data = []
    rev_data = []
    if symbol:
        inst = conn.execute(
            "SELECT * FROM tw_institutional WHERE symbol=? ORDER BY date DESC LIMIT 30",
            (symbol,)).fetchall()
        margin_data = conn.execute(
            "SELECT * FROM tw_margin WHERE symbol=? ORDER BY date DESC LIMIT 30",
            (symbol,)).fetchall()
        per_data = conn.execute(
            "SELECT * FROM tw_per WHERE symbol=? ORDER BY date DESC LIMIT 5",
            (symbol,)).fetchall()
        rev_data = conn.execute(
            "SELECT * FROM tw_revenue WHERE symbol=? ORDER BY date DESC LIMIT 12",
            (symbol,)).fetchall()
    conn.close()

    # 股票選擇
    stock_options = "".join(
        f'<option value="{s}" {"selected" if s == symbol else ""}>{s}</option>'
        for s in stock_list
    )
    selector = f'''<div class="card" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <span style="font-size:15px">📊 選擇股票</span>
        <select onchange="location.href='/chipdata/'+this.value"
                style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:6px 12px;font-size:14px;cursor:pointer">
            {stock_options}
        </select>
        <span style="color:#64748b;font-size:12px">{len(stock_list)} 支股票有籌碼資料</span>
    </div>'''

    # PER/PBR 卡片
    per_html = ""
    if per_data:
        p = per_data[0]
        per_val = f"{p['per']:.1f}" if p['per'] else "N/A"
        pbr_val = f"{p['pbr']:.2f}" if p['pbr'] else "N/A"
        dy_val = f"{p['dividend_yield']:.2f}%" if p['dividend_yield'] else "N/A"
        per_html = f'''<div class="card" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;text-align:center">
            <div><div style="color:#94a3b8;font-size:11px">本益比 PER</div><div style="font-size:1.5em;font-weight:700;color:#38bdf8">{per_val}</div></div>
            <div><div style="color:#94a3b8;font-size:11px">淨值比 PBR</div><div style="font-size:1.5em;font-weight:700;color:#a78bfa">{pbr_val}</div></div>
            <div><div style="color:#94a3b8;font-size:11px">殖利率</div><div style="font-size:1.5em;font-weight:700;color:#4ade80">{dy_val}</div></div>
        </div>'''

    # 法人買賣超表
    inst_html = ""
    if inst:
        rows_str = ""
        for r in inst[:20]:
            fn = r['foreign_net']
            tn = r['trust_net']
            dn = r['dealer_net']
            total = r['total_net']
            fc = "pos" if fn > 0 else "neg" if fn < 0 else ""
            tc = "pos" if tn > 0 else "neg" if tn < 0 else ""
            dc = "pos" if dn > 0 else "neg" if dn < 0 else ""
            ttc = "pos" if total > 0 else "neg" if total < 0 else ""
            rows_str += f'''<tr><td>{r['date'][5:]}</td>
                <td class="{fc}">{fn:+,}</td>
                <td class="{tc}">{tn:+,}</td>
                <td class="{dc}">{dn:+,}</td>
                <td class="{ttc}" style="font-weight:700">{total:+,}</td></tr>'''
        inst_html = f'''<div class="card"><h2>三大法人買賣超</h2>
            <table><tr><th>日期</th><th>外資</th><th>投信</th><th>自營商</th><th>合計</th></tr>
            {rows_str}</table></div>'''

    # 融資融券表
    margin_html = ""
    if margin_data:
        rows_str = ""
        for r in margin_data[:20]:
            rows_str += f'''<tr><td>{r['date'][5:]}</td>
                <td>{r['margin_buy']:,}</td><td>{r['margin_sell']:,}</td>
                <td style="color:#38bdf8">{r['margin_balance']:,}</td>
                <td>{r['short_buy']:,}</td><td>{r['short_sell']:,}</td>
                <td style="color:#f59e0b">{r['short_balance']:,}</td></tr>'''
        margin_html = f'''<div class="card"><h2>融資融券</h2>
            <table><tr><th>日期</th><th>融資買</th><th>融資賣</th><th>融資餘額</th>
            <th>融券買</th><th>融券賣</th><th>融券餘額</th></tr>
            {rows_str}</table></div>'''

    # 月營收表
    rev_html = ""
    if rev_data:
        rows_str = ""
        for r in rev_data:
            yoy = r['revenue_yoy'] or 0
            mom = r['revenue_mom'] or 0
            yc = "pos" if yoy > 0 else "neg" if yoy < 0 else ""
            mc = "pos" if mom > 0 else "neg" if mom < 0 else ""
            rev_m = r['revenue'] / 100000000 if r['revenue'] else 0
            rows_str += f'''<tr><td>{r['date'][:7]}</td>
                <td>{rev_m:.2f} 億</td>
                <td class="{yc}">{yoy:+.1f}%</td>
                <td class="{mc}">{mom:+.1f}%</td></tr>'''
        rev_html = f'''<div class="card"><h2>月營收</h2>
            <table><tr><th>月份</th><th>營收</th><th>年增率</th><th>月增率</th></tr>
            {rows_str}</table></div>'''

    content = selector + per_html + inst_html + margin_html + rev_html

    if not symbol:
        content = '<div class="empty">尚無籌碼資料，請先執行 FinMind 下載</div>'

    return page(f"籌碼分析 — {symbol or ''}", content)


@app.route("/api/analyze/<symbol>")
def api_analyze(symbol):
    """個股綜合分析報告"""
    from investment_analyst import analyze_stock
    report = analyze_stock(symbol)
    return jsonify(report)


@app.route("/api/manifest")
def api_manifest():
    """服務清單 — 供 SBS Dashboard 動態偵測"""
    return jsonify({
        "name": "投資系統",
        "version": "2.0.0",
        "port": 18900,
        "icon": "📊",
        "pages": [
            {"path": "/", "name": "投資儀表板", "icon": "💰"},
            {"path": "/trading", "name": "策略監控", "icon": "📈"},
            {"path": "/intelligence", "name": "市場情報", "icon": "📰"},
            {"path": "/backtests", "name": "回測結果", "icon": "🏆"},
            {"path": "/messages", "name": "群組監聽", "icon": "📨"},
            {"path": "/chipdata", "name": "籌碼分析", "icon": "🏦"},
            {"path": "/screener", "name": "智慧篩選", "icon": "🔍"},
            {"path": "/simulator", "name": "模擬交易", "icon": "🎯"},
        ],
        "apis": [
            "/api/backtests", "/api/market/<symbol>", "/api/trades",
            "/api/symbols", "/api/intelligence", "/api/mood",
            "/api/tg-messages", "/api/tg-stats", "/api/symbol-names",
            "/api/chipdata/<symbol>", "/api/top-flow", "/api/eps-leaders",
            "/api/screener/high-yield", "/api/screener/foreign-buy-streak",
            "/api/screener/revenue-growth", "/api/screener/vix-panic",
            "/api/manifest", "/health",
        ],
        "status": "running",
    })




# ── 模擬交易 ───────────────────────────────────────────

@app.route("/simulator")
def simulator():
    return render_template("simulator.html")


@app.route("/api/sim/account")
def api_sim_account():
    conn = get_conn()
    acct = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    # 計算持倉市值
    positions = conn.execute("SELECT * FROM sim_portfolio WHERE quantity > 0").fetchall()
    position_value = sum((r["current_price"] or r["avg_price"]) * r["quantity"] * 1000 for r in positions)
    unrealized = sum(r["unrealized_pnl"] or 0 for r in positions)
    cash = acct["cash"]
    total = cash + position_value
    conn.execute("UPDATE sim_account SET total_value=?, updated_at=datetime('now','localtime') WHERE id=1", (total,))
    conn.commit()
    conn.close()
    return jsonify({
        "cash": cash,
        "total_value": total,
        "position_value": position_value,
        "realized_pnl": acct["realized_pnl"],
        "unrealized_pnl": unrealized,
    })


@app.route("/api/sim/portfolio")
def api_sim_portfolio():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sim_portfolio WHERE quantity > 0 ORDER BY symbol").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/sim/orders")
def api_sim_orders():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sim_orders ORDER BY created_at DESC LIMIT 100").fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/sim/order", methods=["POST"])
def api_sim_place_order():
    data = request.get_json(force=True)
    symbol = data.get("symbol", "").strip()
    action = data.get("action", "buy")
    order_type = data.get("order_type", "limit")
    price = data.get("price")
    quantity = int(data.get("quantity", 0))
    strategy = data.get("strategy", "")
    note = data.get("note", "")
    name_zh = data.get("name_zh", "")

    if not symbol or quantity <= 0:
        return jsonify({"error": "symbol 和 quantity 為必填"}), 400

    if order_type == "limit" and (price is None or price <= 0):
        return jsonify({"error": "限價單需要有效的 price"}), 400

    conn = get_conn()
    conn.execute("""
        INSERT INTO sim_orders (symbol, name_zh, action, order_type, price, quantity, status, strategy, note)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    """, (symbol, name_zh, action, order_type, price, quantity, strategy, note))
    conn.commit()
    order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return jsonify({"ok": True, "id": order_id})


@app.route("/api/sim/cancel/<int:order_id>", methods=["POST"])
def api_sim_cancel(order_id):
    conn = get_conn()
    order = conn.execute("SELECT * FROM sim_orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "找不到此委託"}), 404
    if order["status"] != "pending":
        conn.close()
        return jsonify({"error": "只能取消待成交委託"}), 400
    conn.execute("UPDATE sim_orders SET status='cancelled', updated_at=datetime('now','localtime') WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/sim/fill/<int:order_id>", methods=["POST"])
def api_sim_fill(order_id):
    """模擬成交 — 更新持倉與帳戶"""
    data = request.get_json(force=True) if request.is_json else {}
    conn = get_conn()
    order = conn.execute("SELECT * FROM sim_orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        return jsonify({"error": "找不到此委託"}), 404
    if order["status"] != "pending":
        conn.close()
        return jsonify({"error": "只能成交待成交委託"}), 400

    fill_price = data.get("price") or order["price"]
    if not fill_price or fill_price <= 0:
        conn.close()
        return jsonify({"error": "成交價格無效"}), 400

    symbol = order["symbol"]
    name_zh = order["name_zh"] or ""
    quantity = order["quantity"]  # 張數
    shares = quantity * 1000  # 股數
    cost = fill_price * shares
    action = order["action"]

    acct = conn.execute("SELECT * FROM sim_account WHERE id=1").fetchone()
    cash = acct["cash"]
    realized_pnl = acct["realized_pnl"]

    if action == "buy":
        if cash < cost:
            conn.close()
            return jsonify({"error": f"現金不足：需要 {cost:,.0f}，現有 {cash:,.0f}"}), 400
        cash -= cost
        # 更新持倉
        pos = conn.execute("SELECT * FROM sim_portfolio WHERE symbol=?", (symbol,)).fetchone()
        if pos:
            old_qty = pos["quantity"]
            old_avg = pos["avg_price"]
            new_qty = old_qty + quantity
            new_avg = (old_avg * old_qty * 1000 + cost) / (new_qty * 1000)
            conn.execute("""UPDATE sim_portfolio SET avg_price=?, quantity=?, name_zh=?,
                            current_price=?, updated_at=datetime('now','localtime') WHERE symbol=?""",
                         (round(new_avg, 2), new_qty, name_zh or pos["name_zh"], fill_price, symbol))
        else:
            conn.execute("""INSERT INTO sim_portfolio (symbol, name_zh, avg_price, quantity, current_price)
                            VALUES (?, ?, ?, ?, ?)""",
                         (symbol, name_zh, fill_price, quantity, fill_price))
    elif action == "sell":
        pos = conn.execute("SELECT * FROM sim_portfolio WHERE symbol=?", (symbol,)).fetchone()
        if not pos or pos["quantity"] < quantity:
            conn.close()
            return jsonify({"error": f"持倉不足：持有 {pos['quantity'] if pos else 0} 張"}), 400
        cash += cost
        pnl = (fill_price - pos["avg_price"]) * shares
        realized_pnl += pnl
        new_qty = pos["quantity"] - quantity
        if new_qty == 0:
            conn.execute("DELETE FROM sim_portfolio WHERE symbol=?", (symbol,))
        else:
            conn.execute("""UPDATE sim_portfolio SET quantity=?, current_price=?,
                            unrealized_pnl=?, updated_at=datetime('now','localtime') WHERE symbol=?""",
                         (new_qty, fill_price,
                          (fill_price - pos["avg_price"]) * new_qty * 1000, symbol))

    # 更新帳戶
    conn.execute("""UPDATE sim_account SET cash=?, realized_pnl=?,
                    updated_at=datetime('now','localtime') WHERE id=1""", (cash, realized_pnl))
    # 更新委託狀態
    conn.execute("""UPDATE sim_orders SET status='filled', filled_price=?,
                    filled_at=datetime('now','localtime'), updated_at=datetime('now','localtime')
                    WHERE id=?""", (fill_price, order_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "filled_price": fill_price})


@app.route("/api/sim/signals")
def api_sim_signals():
    """取得最新策略信號（從 backtest_results 讀取最新一筆每個策略）"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT b.strategy, b.symbol, b.total_return, b.sharpe_ratio, b.win_rate, b.ts,
               COALESCE(n.name_zh, b.symbol) as name_zh
        FROM backtest_results b
        LEFT JOIN symbol_names n ON n.symbol = b.symbol
        WHERE b.ts = (SELECT MAX(ts) FROM backtest_results WHERE strategy = b.strategy AND symbol = b.symbol)
        ORDER BY b.ts DESC
        LIMIT 30
    """).fetchall()
    conn.close()
    signals = []
    for r in rows:
        ret = r["total_return"] or 0
        signal = "buy" if ret > 5 else ("sell" if ret < -5 else "hold")
        confidence = min(100, abs(ret) * 3)
        signals.append({
            "strategy": r["strategy"],
            "symbol": r["symbol"],
            "name_zh": r["name_zh"],
            "signal": signal,
            "confidence": round(confidence, 1),
            "total_return": round(ret, 2),
            "sharpe": round(r["sharpe_ratio"] or 0, 2),
            "win_rate": round(r["win_rate"] or 0, 1),
            "ts": r["ts"],
        })
    return jsonify(signals)


# ── PTT 股版 API ─────────────────────────────────────

@app.route("/api/ptt")
def api_ptt():
    """最新 PTT 股版文章"""
    limit = request.args.get("limit", 30, type=int)
    category = request.args.get("category", None)
    conn = get_conn()
    if category:
        rows = conn.execute(
            "SELECT * FROM ptt_posts WHERE category=? ORDER BY crawled_at DESC LIMIT ?",
            (category, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ptt_posts ORDER BY crawled_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


@app.route("/api/ptt-sentiment")
def api_ptt_sentiment():
    """PTT 股版情緒統計"""
    hours = request.args.get("hours", 24, type=int)
    try:
        from ptt_monitor import get_ptt_sentiment
        result = get_ptt_sentiment(hours=hours)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/bubble-indicators")
@cached(ttl_seconds=300)
def api_bubble_indicators():
    """泡沫指標 — 5 項市場風險訊號"""
    conn = get_conn()
    indicators = []

    def _latest(symbol):
        """取得 symbol 最新收盤價"""
        row = conn.execute(
            "SELECT close, date FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (symbol,)).fetchone()
        return (row["close"], row["date"]) if row else (None, None)

    def _close_30d_ago(symbol):
        """取得約 30 天前的收盤價"""
        row = conn.execute(
            "SELECT close FROM market_data WHERE symbol=? AND date <= date('now', '-30 days') ORDER BY date DESC LIMIT 1",
            (symbol,)).fetchone()
        return row["close"] if row else None

    def _level_color(value, green_max, yellow_max):
        """根據閾值回傳 green/yellow/red"""
        if value < green_max:
            return "green"
        elif value < yellow_max:
            return "yellow"
        return "red"

    # 1) VIX 恐慌指數
    vix_val, vix_date = _latest("^VIX")
    if vix_val is not None:
        vix_level = _level_color(vix_val, 20, 30)
        desc_map = {"green": "市場恐慌程度正常", "yellow": "市場出現緊張情緒", "red": "市場極度恐慌"}
        indicators.append({
            "name": "VIX 恐慌指數",
            "value": round(vix_val, 2),
            "level": vix_level,
            "threshold": {"green": "<20", "yellow": "20-30", "red": ">30"},
            "description": desc_map[vix_level],
        })

    # 2) 銅金比
    cu_val, _ = _latest("HG=F")
    au_val, _ = _latest("GC=F")
    if cu_val and au_val and au_val > 0:
        ratio = cu_val / au_val
        cu_30 = _close_30d_ago("HG=F")
        au_30 = _close_30d_ago("GC=F")
        change_30d = None
        ratio_level = "green"
        if cu_30 and au_30 and au_30 > 0:
            old_ratio = cu_30 / au_30
            if old_ratio > 0:
                change_30d = round((ratio - old_ratio) / old_ratio * 100, 2)
                if change_30d < -10:
                    ratio_level = "red"
                elif change_30d < -3:
                    ratio_level = "yellow"
        desc_map = {"green": "銅金比穩定，經濟正常", "yellow": "銅金比下滑，經濟放緩訊號", "red": "銅金比大跌，衰退警訊"}
        ind = {
            "name": "銅金比",
            "value": round(ratio, 6),
            "level": ratio_level,
            "description": desc_map[ratio_level],
        }
        if change_30d is not None:
            ind["change_30d"] = change_30d
        indicators.append(ind)

    # 3) 台幣匯率
    twd_val, _ = _latest("USDTWD=X")
    if twd_val is not None:
        twd_30 = _close_30d_ago("USDTWD=X")
        change_30d = None
        twd_level = "green"
        if twd_30 and twd_30 > 0:
            change_30d = round((twd_val - twd_30) / twd_30 * 100, 2)
            # USD/TWD 上升 = 台幣貶值
            if change_30d > 5:
                twd_level = "red"
            elif change_30d > 2:
                twd_level = "yellow"
        desc_map = {"green": "台幣穩定", "yellow": "台幣走貶中", "red": "台幣急貶警訊"}
        ind = {
            "name": "台幣匯率",
            "value": round(twd_val, 2),
            "level": twd_level,
            "description": desc_map[twd_level],
        }
        if change_30d is not None:
            ind["change_30d"] = change_30d
        indicators.append(ind)

    # 4) 美債 10Y 殖利率
    tnx_val, _ = _latest("^TNX")
    if tnx_val is not None:
        tnx_level = _level_color(tnx_val, 3.5, 4.5)
        tnx_30 = _close_30d_ago("^TNX")
        change_30d = None
        if tnx_30 is not None:
            change_30d = round(tnx_val - tnx_30, 2)
        desc_map = {"green": "殖利率偏低，寬鬆環境", "yellow": "殖利率偏高", "red": "殖利率過高，緊縮壓力大"}
        ind = {
            "name": "美債 10Y 殖利率",
            "value": round(tnx_val, 2),
            "level": tnx_level,
            "threshold": {"green": "<3.5", "yellow": "3.5-4.5", "red": ">4.5"},
            "description": desc_map[tnx_level],
        }
        if change_30d is not None:
            ind["change_30d"] = change_30d
        indicators.append(ind)

    # 5) BTC 30 日波動率 (年化)
    btc_rows = conn.execute(
        "SELECT close FROM market_data WHERE symbol='BTC-USD' ORDER BY date DESC LIMIT 31"
    ).fetchall()
    if len(btc_rows) >= 2:
        closes = [r["close"] for r in btc_rows]
        daily_returns = []
        for i in range(len(closes) - 1):
            if closes[i + 1] > 0:
                daily_returns.append(closes[i] / closes[i + 1] - 1)
        if daily_returns:
            mean_r = sum(daily_returns) / len(daily_returns)
            variance = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            annual_vol = math.sqrt(variance) * math.sqrt(252) * 100  # 百分比
            btc_level = _level_color(annual_vol, 30, 60)
            desc_map = {"green": "加密市場波動低", "yellow": "加密市場波動中等", "red": "加密市場劇烈波動"}
            indicators.append({
                "name": "BTC 30 日波動率",
                "value": round(annual_vol, 1),
                "level": btc_level,
                "threshold": {"green": "<30", "yellow": "30-60", "red": ">60"},
                "description": desc_map[btc_level],
            })

    conn.close()

    # 綜合分數
    score_map = {"green": 0, "yellow": 10, "red": 20}
    total = sum(score_map.get(ind["level"], 0) for ind in indicators)
    if indicators:
        # 按 5 項滿分 100 等比例換算
        overall_score = int(total / len(indicators) * 5)
    else:
        overall_score = 0
    if overall_score <= 30:
        overall_level = "green"
    elif overall_score <= 60:
        overall_level = "yellow"
    else:
        overall_level = "red"

    return jsonify({
        "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "overall_score": overall_score,
        "overall_level": overall_level,
        "indicators": indicators,
    })


@app.route("/api/weekly-summary")
@cached(ttl_seconds=600)
def api_weekly_summary():
    """本週市場週報摘要"""
    conn = get_conn()

    # 用實際最新 market_data 日期當作週報終點
    latest_row = conn.execute(
        "SELECT MAX(date) as d FROM market_data"
    ).fetchone()
    period_end = latest_row['d'] if latest_row and latest_row['d'] else datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.strptime(period_end, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')

    # ── 主要市場 ──
    key_symbols = {
        '^TWII': '台灣加權', '^GSPC': 'S&P 500', '^N225': '日經225',
        '^HSI': '恆生', 'GC=F': '黃金', 'BTC-USD': '比特幣', 'CL=F': '原油'
    }
    markets = []
    for sym, name in key_symbols.items():
        rows = conn.execute(
            "SELECT date, close FROM market_data WHERE symbol=? ORDER BY date DESC LIMIT 6",
            (sym,)
        ).fetchall()
        if len(rows) >= 2:
            latest = rows[0]['close']
            prev = rows[-1]['close']
            change_pct = round((latest - prev) / prev * 100, 2) if prev else 0
            markets.append({
                'symbol': sym, 'name': name,
                'latest': round(latest, 2), 'prev': round(prev, 2),
                'change_pct': change_pct,
                'date_range': f"{rows[-1]['date']} ~ {rows[0]['date']}"
            })

    # ── 新聞情緒統計 ──
    mood = conn.execute("""
        SELECT sentiment, COUNT(*) as cnt, ROUND(AVG(score), 1) as avg_score
        FROM news_intelligence
        WHERE analyzed_at >= ? AND sentiment IN ('bullish','bearish','neutral')
        GROUP BY sentiment
    """, (week_ago,)).fetchall()
    sentiment = {r['sentiment']: {'count': r['cnt'], 'avg_score': r['avg_score']} for r in mood}

    # ── 本週高分新聞 Top 5 ──
    top_news = []
    try:
        news_rows = conn.execute("""
            SELECT title, source, score, sentiment, published_at
            FROM news_intelligence
            WHERE published_at >= ? AND score IS NOT NULL
            ORDER BY score DESC LIMIT 5
        """, (week_ago,)).fetchall()
        top_news = rows_to_dicts(news_rows)
    except Exception:
        pass

    # ── 法人資金流向（週合計）──
    institutional_flow = {}
    try:
        flow = conn.execute("""
            SELECT SUM(foreign_net) as foreign_net,
                   SUM(trust_net) as trust_net,
                   SUM(dealer_net) as dealer_net,
                   SUM(total_net) as total_net,
                   COUNT(DISTINCT date) as trading_days
            FROM tw_institutional WHERE date >= ?
        """, (week_ago,)).fetchone()
        if flow and flow['trading_days']:
            institutional_flow = {
                'foreign_net': flow['foreign_net'] or 0,
                'trust_net': flow['trust_net'] or 0,
                'dealer_net': flow['dealer_net'] or 0,
                'total_net': flow['total_net'] or 0,
                'trading_days': flow['trading_days'],
            }
    except Exception:
        pass

    # ── 泡沫 / 風險指標摘要 ──
    bubble_summary = {}
    try:
        vix_row = conn.execute(
            "SELECT close, date FROM market_data WHERE symbol='^VIX' ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if vix_row:
            vix_val = vix_row['close']
            if vix_val < 20:
                vix_level = 'green'
            elif vix_val < 30:
                vix_level = 'yellow'
            else:
                vix_level = 'red'
            bubble_summary['vix'] = {
                'value': round(vix_val, 2),
                'level': vix_level,
                'date': vix_row['date'],
            }
        # 台股融資餘額變化
        margin_row = conn.execute("""
            SELECT SUM(margin_balance_change) as margin_chg,
                   SUM(short_balance_change) as short_chg
            FROM tw_margin WHERE date >= ?
        """, (week_ago,)).fetchone()
        if margin_row and margin_row['margin_chg'] is not None:
            bubble_summary['margin_change'] = {
                'margin_balance_change': margin_row['margin_chg'],
                'short_balance_change': margin_row['short_chg'] or 0,
            }
    except Exception:
        pass

    # ── 本週有交易訊號的策略 ──
    top_strategies = []
    try:
        strat_rows = conn.execute("""
            SELECT b.symbol, b.strategy, b.total_return, b.sharpe_ratio,
                   MAX(t.ts) as last_trade
            FROM backtest_results b
            INNER JOIN trades t ON t.symbol = b.symbol AND t.strategy = b.strategy
            WHERE t.ts >= ?
            GROUP BY b.symbol, b.strategy
            ORDER BY b.total_return DESC LIMIT 5
        """, (week_ago,)).fetchall()
        top_strategies = rows_to_dicts(strat_rows)
    except Exception:
        # trades 表可能結構不同或為空，fallback 到本週回測
        try:
            fallback = conn.execute("""
                SELECT symbol, strategy, total_return, sharpe_ratio
                FROM backtest_results
                WHERE updated_at >= ?
                ORDER BY total_return DESC LIMIT 5
            """, (week_ago,)).fetchall()
            top_strategies = rows_to_dicts(fallback)
        except Exception:
            pass

    conn.close()
    return jsonify({
        'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'period': f"{week_ago} ~ {period_end}",
        'markets': markets,
        'sentiment': sentiment,
        'top_news': top_news,
        'institutional_flow': institutional_flow,
        'bubble_summary': bubble_summary,
        'top_strategies': top_strategies,
    })


@app.route("/api/cache-stats")
def api_cache_stats():
    """快取統計"""
    now = time.time()
    active = sum(1 for _, (_, ts) in _cache.items() if now - ts < 3600)
    return jsonify({'total_entries': len(_cache), 'active': active})


@app.route("/debate")
def debate_page():
    """AI 辯論分析頁面"""
    return render_template("debate.html")


@app.route("/api/debate/<symbol>")
def api_debate(symbol):
    """投資辯論 API — 多角色 AI 辯論分析個股"""
    try:
        from investment_debate import run_debate, format_debate_report
        max_rounds = min(int(request.args.get('rounds', 1)), 3)  # 最多 3 輪
        result = run_debate(symbol, max_rounds=max_rounds)
        fmt = request.args.get('format', 'json')
        if fmt == 'text':
            return format_debate_report(result), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── 財經日曆 ─────────────────────────────────────────────

@app.route("/economic-calendar")
def economic_calendar_page():
    """財經日曆頁面"""
    return render_template("economic_calendar.html")


@app.route("/api/economic-calendar")
def api_economic_calendar():
    """財經日曆 API — 列出事件"""
    from economic_calendar import get_events, init_calendar_table
    init_calendar_table()
    date_from = request.args.get('from')
    date_to = request.args.get('to')
    country = request.args.get('country')
    importance = request.args.get('importance')
    limit = request.args.get('limit', 200, type=int)

    if not date_from:
        date_from = datetime.now().strftime("%Y-%m-%d")
    if not date_to:
        date_to = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")

    return jsonify(get_events(date_from=date_from, date_to=date_to,
                              country=country, importance=importance, limit=limit))


@app.route("/api/economic-calendar/today")
def api_economic_calendar_today():
    """今日財經事件"""
    from economic_calendar import get_today_events, init_calendar_table
    init_calendar_table()
    return jsonify(get_today_events())


@app.route("/api/economic-calendar/refresh", methods=["POST"])
def api_economic_calendar_refresh():
    """手動觸發抓取財經日曆"""
    from economic_calendar import fetch_and_store
    days = request.args.get('days', 7, type=int)
    result = fetch_and_store(days=min(days, 30))
    return jsonify(result)


# ── 股東紀念品 ─────────────────────────────────────────

@app.route("/shareholder-gifts")
def shareholder_gifts_page():
    return render_template('shareholder_gifts.html')


@app.route("/api/shareholder-gifts")
def api_shareholder_gifts():
    """股東紀念品列表，可選 ?year=2026&month=6"""
    from shareholder_gifts import get_all_gifts, init_gifts_table
    init_gifts_table()
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    return jsonify(get_all_gifts(year=year, month=month))


@app.route("/api/shareholder-gifts/upcoming")
def api_shareholder_gifts_upcoming():
    """即將截止的紀念品 (未來 ?days=30 天)"""
    from shareholder_gifts import get_upcoming_gifts, init_gifts_table
    init_gifts_table()
    days = request.args.get('days', 30, type=int)
    return jsonify(get_upcoming_gifts(days=days))


# ── 分點主力 ──────────────────────────────────────────

@app.route("/broker-trading")
@app.route("/broker-trading/<symbol>")
def broker_trading_page(symbol=None):
    return render_template('broker_trading.html')


@app.route("/api/broker-trading")
def api_broker_trading():
    """分點主力資料
    GET /api/broker-trading?stock_id=2330&period=1
    period: 1=近1日, 2=近5日, 3=近10日, 4=近20日, 5=近40日, 6=近60日
    """
    from broker_trading import get_broker_trading, init_broker_table
    init_broker_table()

    stock_id = request.args.get('stock_id', '2330')
    period = request.args.get('period', 1, type=int)
    if period < 1 or period > 8:
        period = 1

    result = get_broker_trading(stock_id, period)
    if not result:
        return jsonify({"error": "無法取得資料", "stock_id": stock_id}), 404

    return jsonify(result)


@app.route("/api/margin/<symbol>")
def api_margin(symbol):
    """融資融券趨勢 — 近 N 日"""
    days = request.args.get('days', 30, type=int)
    conn = get_conn()
    rows = conn.execute("""
        SELECT date, margin_buy, margin_sell, margin_balance,
               short_sell, short_buy, short_balance
        FROM tw_margin
        WHERE symbol = ? AND date >= date('now', ? || ' days')
        ORDER BY date DESC
    """, (symbol, f"-{days}")).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/margin-alert")
def api_margin_alert():
    """融資融券異動警示 — 融資增減 > 10% 或融券暴增"""
    conn = get_conn()
    rows = conn.execute("""
        WITH latest AS (
            SELECT symbol, margin_balance, short_balance, date,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
            FROM tw_margin
        ),
        prev AS (
            SELECT symbol, margin_balance as prev_margin, short_balance as prev_short
            FROM latest WHERE rn = 2
        )
        SELECT l.symbol, n.name as name,
               l.margin_balance, p.prev_margin,
               l.short_balance, p.prev_short,
               CASE WHEN p.prev_margin > 0
                    THEN ROUND((l.margin_balance - p.prev_margin) * 100.0 / p.prev_margin, 2)
                    ELSE 0 END as margin_change_pct,
               CASE WHEN p.prev_short > 0
                    THEN ROUND((l.short_balance - p.prev_short) * 100.0 / p.prev_short, 2)
                    ELSE 0 END as short_change_pct
        FROM latest l
        LEFT JOIN prev p ON l.symbol = p.symbol
        LEFT JOIN symbol_names n ON l.symbol = n.symbol
        WHERE l.rn = 1 AND p.prev_margin IS NOT NULL
        AND (ABS(l.margin_balance - p.prev_margin) * 100.0 / MAX(p.prev_margin, 1) > 10
             OR ABS(l.short_balance - p.prev_short) > 500)
        ORDER BY ABS(margin_change_pct) DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/trading-day")
def api_trading_day():
    """查詢是否為交易日"""
    from data.twse_fetcher import is_trading_day
    date_str = request.args.get('date')
    trading = is_trading_day(date_str)
    return jsonify({
        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
        "is_trading_day": trading
    })


if __name__ == "__main__":
    print("投資系統 Web App 啟動中...")
    print("http://localhost:18900")
    app.run(host="0.0.0.0", port=18900, debug=False)
