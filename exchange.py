import os
from binance.client import Client
from dataclasses import dataclass
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_SECRET_KEY')
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'

if not API_KEY or not API_SECRET:
    logger.warning("Binance API keys not found. Using dry run mode only.")
    client = None
else:
    client = Client(API_KEY, API_SECRET)

@dataclass
class OrderResult:
    success: bool
    info: dict

async def place_market_order(symbol: str, side: str, quantity: float) -> OrderResult:
    symbol = symbol.upper()
    side = side.upper()
    if DRY_RUN or client is None:
        fake = {'symbol': symbol, 'side': side, 'origQty': str(quantity), 'status': 'FILLED', 'note': 'dry_run'}
        return OrderResult(True, fake)
    try:
        res = client.futures_create_order(symbol=symbol, side=side, type='MARKET', quantity=quantity)
        return OrderResult(True, res)
    except Exception as e:
        return OrderResult(False, {'error': str(e)})

# ДОБАВЛЯЕМ ФУНКЦИЮ ДЛЯ ЗАКРЫТИЯ ПОЗИЦИЙ
async def close_position_order(symbol: str) -> OrderResult:
    symbol = symbol.upper()
    if DRY_RUN or client is None:
        fake = {'symbol': symbol, 'side': 'CLOSE', 'status': 'FILLED', 'note': 'dry_run_close'}
        return OrderResult(True, fake)
    try:
        # В реальном режиме нужно получить информацию о позиции и закрыть ее
        # Это упрощенная реализация - в реальности нужно учитывать сторону позиции
        position_info = client.futures_position_information(symbol=symbol)
        if position_info and float(position_info[0].get('positionAmt', 0)) != 0:
            # Закрываем позицию встречной сделкой
            quantity = abs(float(position_info[0]['positionAmt']))
            side = 'SELL' if float(position_info[0]['positionAmt']) > 0 else 'BUY'
            res = client.futures_create_order(symbol=symbol, side=side, type='MARKET', quantity=quantity)
            return OrderResult(True, res)
        else:
            return OrderResult(False, {'error': 'No open position found'})
    except Exception as e:
        return OrderResult(False, {'error': str(e)})