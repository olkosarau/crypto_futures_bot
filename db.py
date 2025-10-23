import sqlite3, os
from datetime import datetime

DB = os.getenv('BOT_DB_PATH', 'data/bot.db')


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Таблица сделок
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TIMESTAMP,
        symbol TEXT,
        side TEXT,
        qty REAL,
        price REAL,
        pnl REAL
    )''')

    # Таблица сигналов
    c.execute('''CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TIMESTAMP,
        symbol TEXT,
        timeframe TEXT,
        side TEXT,
        entry REAL,
        stop REAL,
        tp1 REAL,
        tp2 REAL,
        tp3 REAL
    )''')

    # Таблица открытых позиций
    c.execute('''CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TIMESTAMP,
        symbol TEXT,
        side TEXT,
        qty REAL,
        entry_price REAL,
        current_price REAL,
        pnl REAL,
        status TEXT DEFAULT 'OPEN'
    )''')

    conn.commit()
    conn.close()


def log_trade(symbol, side, qty, price, pnl=0.0):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO trades (ts,symbol,side,qty,price,pnl) VALUES (?,?,?,?,?,?)",
              (datetime.utcnow(), symbol, side, qty, price, pnl))
    conn.commit()
    conn.close()


def log_signal(symbol, timeframe, side, entry, stop, tp1, tp2, tp3):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT INTO signals (ts,symbol,timeframe,side,entry,stop,tp1,tp2,tp3) VALUES (?,?,?,?,?,?,?,?,?)",
              (datetime.utcnow(), symbol, timeframe, side, entry, stop, tp1, tp2, tp3))
    conn.commit()
    conn.close()


# Функции для работы с позициями
def open_position(symbol, side, qty, entry_price):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO positions (ts,symbol,side,qty,entry_price,current_price,pnl,status) VALUES (?,?,?,?,?,?,?,?)",
        (datetime.utcnow(), symbol, side, qty, entry_price, entry_price, 0.0, 'OPEN'))
    conn.commit()
    conn.close()


def close_position(symbol):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE positions SET status='CLOSED' WHERE symbol=? AND status='OPEN'", (symbol,))
    conn.commit()
    conn.close()


def get_open_positions():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT symbol, side, qty, entry_price, current_price, pnl FROM positions WHERE status='OPEN'")
    rows = c.fetchall()
    conn.close()

    positions = []
    for r in rows:
        positions.append({
            'symbol': r[0],
            'side': r[1],
            'qty': r[2],
            'entry_price': r[3],
            'current_price': r[4],
            'pnl': r[5]
        })
    return positions


def get_portfolio_summary():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT symbol, side, qty, entry_price, current_price, pnl FROM positions WHERE status='OPEN'")
    rows = c.fetchall()
    conn.close()

    total_pnl = 0
    positions_count = len(rows)

    for r in rows:
        total_pnl += r[5]  # pnl

    return {
        'total_positions': positions_count,
        'total_pnl': total_pnl,
        'positions': [
            {'symbol': r[0], 'side': r[1], 'qty': r[2], 'entry_price': r[3], 'current_price': r[4], 'pnl': r[5]} for r
            in rows]
    }


def update_position_price(symbol, current_price, pnl):
    """Обновить текущую цену и PnL для позиции"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE positions SET current_price=?, pnl=? WHERE symbol=? AND status='OPEN'",
              (current_price, pnl, symbol))
    conn.commit()
    conn.close()


# ДОБАВЛЯЕМ НЕДОСТАЮЩИЕ ФУНКЦИИ ДЛЯ WEB ИНТЕРФЕЙСА
def get_trades(limit=100):
    """Получить последние сделки"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()

    trades = []
    for r in rows:
        trades.append({
            'id': r[0],
            'ts': r[1],
            'symbol': r[2],
            'side': r[3],
            'qty': r[4],
            'price': r[5],
            'pnl': r[6]
        })
    return trades


def get_signals(limit=100):
    """Получить последние сигналы"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM signals ORDER BY ts DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()

    signals = []
    for r in rows:
        signals.append({
            'id': r[0],
            'ts': r[1],
            'symbol': r[2],
            'timeframe': r[3],
            'side': r[4],
            'entry': r[5],
            'stop': r[6],
            'tp1': r[7],
            'tp2': r[8],
            'tp3': r[9]
        })
    return signals


def get_trading_stats(days=7):
    """Получить торговую статистику"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    # Общее количество сделок
    c.execute("SELECT COUNT(*) FROM trades WHERE ts >= datetime('now','-? days')", (days,))
    total_trades = c.fetchone()[0]

    # Прибыльные сделки
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND ts >= datetime('now','-? days')", (days,))
    winning_trades = c.fetchone()[0]

    # Общий PnL
    c.execute("SELECT SUM(pnl) FROM trades WHERE ts >= datetime('now','-? days')", (days,))
    total_pnl = c.fetchone()[0] or 0

    # Win rate
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    conn.close()

    return {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl
    }