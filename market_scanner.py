import asyncio
import logging
import httpx
from typing import List, Dict
import pandas as pd
from data import fetch_klines
from strategies import generate_signal_from_dfs

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self):
        self.top_symbols = []
        # Черный список сомнительных монет
        self.blacklist = {
            'PUMPUSDT', 'BLUAIUSDT', 'COAIUSDT', 'LIGHTUSDT', 'ASTERUSDT',
            'RIVERUSDT', 'FARTCOINUSDT', '币安人生USDT', 'ALPACAUSDT',
            'AIAUSDT', 'ALPHAUSDT', 'ZECUSDT', 'TAOUSDT', 'HYPEUSDT'
        }

    async def get_top_volume_symbols(self, limit: int = 25) -> List[str]:
        """Получить топ монет по объему, исключая сомнительные"""
        try:
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                data = response.json()

            def is_valid_symbol(symbol):
                if not symbol.endswith('USDT'):
                    return False
                # Исключаем черный список
                if symbol in self.blacklist:
                    return False
                # Исключаем символы с не-ASCII
                if not symbol.replace('USDT', '').isalnum():
                    return False
                # Исключаем слишком короткие/длинные
                if len(symbol) < 7 or len(symbol) > 12:
                    return False
                return True

            usdt_pairs = [item for item in data if is_valid_symbol(item['symbol'])]

            # Сортируем по объему и берем только ликвидные
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)

            # Берем только монеты с достаточным объемом
            min_volume = 10000000  # 10M USDT минимальный объем
            liquid_pairs = [pair for pair in sorted_pairs if float(pair['quoteVolume']) > min_volume]

            top_symbols = [pair['symbol'] for pair in liquid_pairs[:limit]]
            logger.info(f"Found {len(top_symbols)} valid liquid symbols")
            return top_symbols

        except Exception as e:
            logger.error(f"Error fetching top symbols: {e}")
            # Возвращаем только качественные монеты по умолчанию
            return ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
                    'AVAXUSDT', 'DOTUSDT', 'LINKUSDT', 'MATICUSDT', 'DOGEUSDT', 'LTCUSDT']

    async def scan_symbols(self, symbols: List[str]) -> Dict[str, Dict]:
        """Сканировать список символов на наличие КАЧЕСТВЕННЫХ сигналов"""
        signals = {}

        for symbol in symbols:
            try:
                # Получаем данные для разных таймфреймов
                df_5m = await fetch_klines(symbol, '5m', limit=100)
                df_1h = await fetch_klines(symbol, '1h', limit=100)

                if df_5m.empty or df_1h.empty:
                    continue

                # Генерируем сигнал
                signal = generate_signal_from_dfs(df_5m, df_1h)

                # ФИЛЬТРУЕМ: берем только сигналы с высокой уверенностью
                if signal.side != 'NONE' and signal.confidence > 0.6:
                    signals[symbol] = {
                        'signal': signal,
                        'strength': signal.confidence * 10,
                        'timeframes': ['5m', '1h'],
                        'price': float(df_5m.iloc[-1]['close']),
                        'volume': float(df_5m.iloc[-1]['volume'])
                    }

                    logger.info(
                        f"QUALITY signal found for {symbol}: {signal.side} (confidence: {signal.confidence:.1%})")

            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
                continue

        return signals

    async def get_best_signals(self, max_signals: int = 3) -> List[Dict]:
        """Получить только ЛУЧШИЕ сигналы"""
        if not self.top_symbols:
            self.top_symbols = await self.get_top_volume_symbols(25)

        all_signals = await self.scan_symbols(self.top_symbols)

        # Сортируем по силе сигнала и объему
        sorted_signals = sorted(
            all_signals.items(),
            key=lambda x: (x[1]['strength'], x[1]['volume']),
            reverse=True
        )

        # Берем только топ сигналы
        best_signals = [{'symbol': k, **v} for k, v in sorted_signals[:max_signals]]

        if best_signals:
            logger.info(f"Found {len(best_signals)} quality signals")
        else:
            logger.info("No quality signals found in current market conditions")

        return best_signals


scanner = MarketScanner()