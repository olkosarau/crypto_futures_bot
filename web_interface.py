from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import asyncio
import logging
from db import get_open_positions, get_portfolio_summary, get_signals
import pandas as pd
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Создаем FastAPI приложение для веб-интерфейса
web_app = FastAPI(title="Trading Bot Dashboard")

# Создаем необходимые папки
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Монтируем статические файлы
web_app.mount("/static", StaticFiles(directory="static"), name="static")

# Настраиваем шаблоны
templates = Jinja2Templates(directory="templates")


# WebSocket соединения для реального времени
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                self.disconnect(connection)


manager = ConnectionManager()


@web_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Главная панель управления"""
    print('111111111111111111')
    try:
        print('22222222222222')
        portfolio = get_portfolio_summary()
        recent_signals = get_signals(limit=10)

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "portfolio": portfolio,
            "recent_signals": recent_signals
        })
    except Exception as e:
        print('333333333333333333')
        logger.error(f"Dashboard error: {e}")
        # Возвращаем простую HTML страницу если шаблон не работает
        return HTMLResponse(content=f"""
        <html>
            <head><title>Trading Bot</title></head>
            <body>
                <h1>🤖 Trading Bot Dashboard</h1>
                <p>Веб-интерфейс загружается...</p>
                <p>Если эта страница не обновляется, проверьте консоль браузера (F12)</p>
                <div id="content"></div>
                <script>
                    // Простой JavaScript для загрузки данных
                    async function loadData() {{
                        try {{
                            const response = await fetch('/api/status');
                            const data = await response.json();
                            document.getElementById('content').innerHTML = 
                                '<h3>Статус бота: ✅ Работает</h3>' +
                                '<p>Открытых позиций: ' + data.open_positions + '</p>' +
                                '<p>Последнее обновление: ' + new Date().toLocaleString() + '</p>';
                        }} catch (error) {{
                            document.getElementById('content').innerHTML = 
                                '<p style="color: red">Ошибка загрузки: ' + error + '</p>';
                        }}
                    }}
                    loadData();
                </script>
            </body>
        </html>
        """)


@web_app.get("/api/status")
async def api_status():
    """API статуса бота"""
    try:
        portfolio = get_portfolio_summary()
        return {
            "status": "running",
            "open_positions": portfolio['total_positions'],
            "total_pnl": portfolio['total_pnl'],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@web_app.get("/api/portfolio")
async def api_portfolio():
    """API портфеля"""
    try:
        return get_portfolio_summary()
    except Exception as e:
        return {"error": str(e)}


@web_app.get("/api/signals")
async def api_signals(limit: int = 10):
    """API сигналов"""
    try:
        return get_signals(limit=limit)
    except Exception as e:
        return {"error": str(e)}


@web_app.post("/api/scan")
async def api_scan():
    """API для запуска сканирования"""
    try:
        # Импортируем здесь чтобы избежать циклических импортов
        from bot import check_signals
        await check_signals()
        return {"status": "scan_started"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@web_app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket для реального времени"""
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(5)
            portfolio = get_portfolio_summary()
            await websocket.send_json({
                "type": "portfolio_update",
                "data": portfolio
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def notify_websocket_clients(message_type: str, data: dict):
    """Отправить уведомление всем WebSocket клиентам"""
    message = {
        "type": message_type,
        "data": data,
        "timestamp": datetime.now().isoformat()
    }
    await manager.broadcast(json.dumps(message))