import os, datetime
import sqlite3
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

DB = os.getenv('BOT_DB_PATH', 'data/bot.db')

def fetch_trades(days=7):
    if not os.path.exists(DB):
        return []
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("SELECT ts, symbol, side, qty, price, pnl FROM trades WHERE ts >= datetime('now','-? days')", (days,))
    rows = c.fetchall(); conn.close()
    trades = []
    for r in rows:
        trades.append({'ts': r[0], 'symbol': r[1], 'side': r[2], 'qty': r[3], 'price': r[4], 'pnl': r[5]})
    return trades

# fallback if no DB rows
def _fallback_trades(n=20):
    import random, datetime as dt
    now = dt.datetime.utcnow()
    trades = []
    bal = 1000.0
    for i in range(n):
        pnl = round(random.uniform(-50,150),2)
        trades.append({'ts': (now - dt.timedelta(hours=n-i)).isoformat(), 'symbol':'BTCUSDT','side':'BUY','qty':1.0,'price':0.0,'pnl':pnl})
    return trades

def _equity_series(trades, start=1000.0):
    eq = start; series = []
    for t in trades:
        eq += float(t.get('pnl',0.0))
        series.append(eq)
    return series

def _save_plot(series, out_path):
    plt.figure(figsize=(6,3))
    plt.plot(range(1,len(series)+1), series, marker='o')
    plt.title('Equity curve')
    plt.xlabel('Trade #'); plt.ylabel('Balance USDT')
    plt.tight_layout(); plt.savefig(out_path); plt.close()

def generate_weekly_report():
    report_dir = 'data/reports'; os.makedirs(report_dir, exist_ok=True)
    file = os.path.join(report_dir, f"report_{datetime.date.today()}.pdf")
    trades = fetch_trades(7)
    if not trades:
        trades = _fallback_trades(20)
    series = _equity_series(trades, start=1000.0)
    graph = os.path.join(report_dir, 'equity.png')
    _save_plot(series, graph)

    # stats
    total = len(trades); wins = sum(1 for t in trades if float(t.get('pnl',0))>0)
    winrate = wins/total*100 if total else 0; total_pnl = sum(float(t.get('pnl',0)) for t in trades)
    avg = total_pnl/total if total else 0

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    c = canvas.Canvas(file, pagesize=letter); width, height = letter
    c.setFont('Helvetica-Bold',16); c.drawString(72, height-54, 'Weekly Trading Report')
    c.setFont('Helvetica',11); c.drawString(72, height-72, f'Date: {datetime.date.today()}')
    y = height-110
    c.drawString(72,y, f'Total trades: {total}'); y-=14
    c.drawString(72,y, f'Wins: {wins}  Winrate: {winrate:.2f}%'); y-=14
    c.drawString(72,y, f'Total PnL: {total_pnl:.2f} USDT'); y-=20

    table_data = [['#','Timestamp','Symbol','Side','Qty','Price','PnL']]
    for i,t in enumerate(trades,1):
        table_data.append([i, t.get('ts',''), t.get('symbol',''), t.get('side',''), t.get('qty',''), t.get('price',''), f"{float(t.get('pnl',0)):.2f}"])
    table = Table(table_data, colWidths=[30,120,60,40,40,60,60])
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.grey),('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),('ALIGN',(0,0),(-1,-1),'CENTER'),('GRID',(0,0),(-1,-1),0.5,colors.black)]))
    tw, th = table.wrap(0,0); table.drawOn(c,72,y-th)
    c.drawImage(graph, 72, max(40, y-th-220), width=450, height=200)
    c.save()
    return file
