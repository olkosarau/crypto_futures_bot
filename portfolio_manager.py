import logging
from data import fetch_klines
from db import get_open_positions, update_position_price  # Теперь функция есть
import asyncio

logger = logging.getLogger(__name__)


async def update_portfolio_prices():
    """Обновить цены в открытых позициях"""
    try:
        positions = get_open_positions()
        if not positions:
            return

        logger.info(f"Updating prices for {len(positions)} open positions")

        for position in positions:
            symbol = position['symbol']
            try:
                # Получаем текущую цену
                df = await fetch_klines(symbol, '1m', limit=1)
                if not df.empty:
                    current_price = float(df.iloc[-1]['close'])
                    entry_price = position['entry_price']
                    qty = position['qty']

                    # Рассчитываем PnL
                    if position['side'] == 'BUY':
                        pnl = (current_price - entry_price) * qty
                    else:  # SHORT
                        pnl = (entry_price - current_price) * qty

                    # Обновляем позицию в базе
                    update_position_price(symbol, current_price, pnl)

                    logger.debug(f"Updated {symbol}: price={current_price:.4f}, PnL={pnl:.2f}")

            except Exception as e:
                logger.error(f"Error updating price for {symbol}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error updating portfolio prices: {e}")