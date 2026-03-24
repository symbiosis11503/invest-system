"""投資系統 Web App — 後端 API"""
import sqlite3
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "db/trades.db")
app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id    INTEGER NOT NULL,
            group_name  TEXT,
            sender_id   INTEGER,
            sender_name TEXT,
            message_text TEXT,
            ts          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tg_messages_group_ts
        ON tg_messages (group_id, ts)
    """)
    conn.commit()
    conn.close()


init_db()


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


@app.route("/api/manifest")
def api_manifest():
    """服務清單 — 供 SBS Dashboard 動態偵測"""
    return jsonify({
        "name": "投資系統",
        "version": "1.0",
        "port": 18900,
        "icon": "📊",
        "apis": [
            "/api/backtests", "/api/market/<symbol>", "/api/trades",
            "/api/symbols", "/api/intelligence", "/api/mood",
            "/api/tg-messages", "/api/tg-stats", "/api/manifest",
            "/api/chipdata", "/api/chipdata/<symbol>", "/api/chipdata/summary",
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
