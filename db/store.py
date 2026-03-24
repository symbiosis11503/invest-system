"""SQLite 交易紀錄儲存"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / 'trades.db'


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建立資料表"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,          -- BUY / SELL
            price REAL NOT NULL,
            size INTEGER NOT NULL,
            value REAL NOT NULL,
            pnl REAL DEFAULT 0,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            symbol TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            initial_cash REAL,
            final_value REAL,
            total_return REAL,
            max_drawdown REAL,
            sharpe_ratio REAL,
            win_rate REAL,
            total_trades INTEGER,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS market_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER,
            source TEXT DEFAULT 'yfinance',
            UNIQUE(symbol, date)
        );
    """)
    conn.commit()
    conn.close()


def save_trade(strategy, symbol, action, price, size, value, pnl=0):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trades (strategy, symbol, action, price, size, value, pnl) VALUES (?,?,?,?,?,?,?)",
        (strategy, symbol, action, price, size, value, pnl)
    )
    conn.commit()
    conn.close()


def save_backtest(strategy, symbol, start_date, end_date, initial_cash,
                  final_value, total_return, max_drawdown, sharpe_ratio,
                  win_rate, total_trades):
    conn = get_conn()
    conn.execute(
        """INSERT INTO backtest_results
           (strategy, symbol, start_date, end_date, initial_cash, final_value,
            total_return, max_drawdown, sharpe_ratio, win_rate, total_trades)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (strategy, symbol, start_date, end_date, initial_cash, final_value,
         total_return, max_drawdown, sharpe_ratio, win_rate, total_trades)
    )
    conn.commit()
    conn.close()


def save_market_data(symbol, date, o, h, l, c, vol, source='yfinance'):
    conn = get_conn()
    conn.execute(
        """INSERT OR IGNORE INTO market_data
           (symbol, date, open, high, low, close, volume, source)
           VALUES (?,?,?,?,?,?,?,?)""",
        (symbol, date, o, h, l, c, vol, source)
    )
    conn.commit()
    conn.close()


def get_trades(strategy=None, limit=50):
    conn = get_conn()
    if strategy:
        rows = conn.execute(
            "SELECT * FROM trades WHERE strategy=? ORDER BY ts DESC LIMIT ?",
            (strategy, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backtest_results(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM backtest_results ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# 初始化
init_db()
