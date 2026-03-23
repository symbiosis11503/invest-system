"""投資系統 Web App — 家人手機瀏覽用"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, Response, send_file

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")
app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


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
def api_symbols():
    conn = get_conn()
    rows = conn.execute("""
        SELECT symbol, COUNT(*) as count, MIN(date) as min_date, MAX(date) as max_date
        FROM market_data GROUP BY symbol ORDER BY symbol
    """).fetchall()
    conn.close()
    return jsonify(rows_to_dicts(rows))


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
    tg_html = ""
    try:
        tg_total = conn.execute("SELECT COUNT(*) FROM tg_messages").fetchone()[0]
        tg_groups = conn.execute("SELECT COUNT(DISTINCT group_name) FROM tg_messages").fetchone()[0]
    except Exception:
        tg_total = 0
        tg_groups = 0
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
    conn.close()
    return jsonify({
        "symbol": symbol,
        "institutional": rows_to_dicts(inst),
        "margin": rows_to_dicts(margin),
        "per": rows_to_dicts(per),
        "revenue": rows_to_dicts(revenue),
    })


@app.route("/api/chipdata/summary")
def api_chipdata_summary():
    """最新一日三大法人合計淨買前 N 名"""
    conn = get_conn()
    try:
        latest_date = conn.execute("SELECT MAX(date) FROM tw_institutional").fetchone()[0]
        if not latest_date:
            return jsonify({"latest_date": None, "rows": []})
        rows = conn.execute("""
            SELECT symbol, foreign_net, trust_net,
                   COALESCE(dealer_net, 0) as dealer_net,
                   (COALESCE(foreign_net,0)+COALESCE(trust_net,0)+COALESCE(dealer_net,0)) as total_net
            FROM tw_institutional WHERE date = ?
            ORDER BY ABS(COALESCE(foreign_net,0)+COALESCE(trust_net,0)+COALESCE(dealer_net,0)) DESC LIMIT 10
        """, (latest_date,)).fetchall()
    except Exception:
        return jsonify({"latest_date": None, "rows": []})
    finally:
        conn.close()
    return jsonify({"latest_date": latest_date, "rows": rows_to_dicts(rows)})


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


@app.route("/chipdata")
@app.route("/chipdata/<symbol>")
def chipdata_page(symbol=None):
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


@app.route("/api/manifest")
def api_manifest():
    """服務清單 — 供 SBS Dashboard 動態偵測"""
    return jsonify({
        "name": "投資系統",
        "version": "1.0",
        "port": 18900,
        "icon": "📊",
        "pages": [
            {"path": "/", "name": "投資儀表板", "icon": "💰"},
            {"path": "/trading", "name": "策略監控", "icon": "📈"},
            {"path": "/intelligence", "name": "市場情報", "icon": "📰"},
            {"path": "/backtests", "name": "回測結果", "icon": "🏆"},
            {"path": "/messages", "name": "群組監聽", "icon": "📨"},
            {"path": "/chipdata", "name": "籌碼分析", "icon": "🏦"},
        ],
        "apis": [
            "/api/backtests", "/api/market/<symbol>", "/api/trades",
            "/api/symbols", "/api/intelligence", "/api/mood",
            "/api/tg-messages", "/api/tg-stats", "/api/manifest",
        ],
        "status": "running",
    })


@app.route("/health")
def health():
    """健康檢查端點"""
    conn = get_conn()
    symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM market_data").fetchone()[0]
    news = conn.execute("SELECT COUNT(*) FROM news_intelligence").fetchone()[0]
    backtests = conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0]
    conn.close()
    return jsonify({
        "status": "ok",
        "name": "投資系統",
        "symbols": symbols,
        "news": news,
        "backtests": backtests,
        "timestamp": datetime.now().isoformat(),
    })


if __name__ == "__main__":
    print("投資系統 Web App 啟動中...")
    print("http://localhost:18900")
    app.run(host="0.0.0.0", port=18900, debug=False)
