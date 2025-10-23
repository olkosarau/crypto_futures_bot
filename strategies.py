import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    side: str  # 'LONG', 'SHORT', 'NONE'
    reason: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    confidence: float = 0.0


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    try:
        # Базовые индикаторы (проверенные и надежные)
        df['ema20'] = ta.ema(df['close'], length=20)
        df['ema50'] = ta.ema(df['close'], length=50)
        df['ema100'] = ta.ema(df['close'], length=100)
        df['rsi'] = ta.rsi(df['close'], length=14)

        # MACD
        macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
        if macd is not None and not macd.empty:
            df['macd'] = macd.iloc[:, 0]  # MACD line
            df['macd_signal'] = macd.iloc[:, 1]  # Signal line

        # ATR для стоп-лосса
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

        # Простые каналы вместо Дончиана (убираем проблемный индикатор)
        df['channel_upper'] = df['high'].rolling(20).max()
        df['channel_lower'] = df['low'].rolling(20).min()

        # Volume SMA для фильтрации
        df['volume_sma'] = ta.sma(df['volume'], length=20)

        return df.dropna().reset_index(drop=True)

    except Exception as e:
        logger.error(f"Error adding indicators: {e}")
        # Возвращаем только самые базовые индикаторы
        basic_cols = ['open', 'high', 'low', 'close', 'volume', 'ema20', 'ema50', 'rsi']
        available_cols = [col for col in basic_cols if col in df.columns]
        return df[available_cols].dropna().reset_index(drop=True)


def trend_bias_from_last(row) -> Tuple[str, float]:
    """Определить тренд и его силу"""
    try:
        if 'ema20' not in row or 'ema50' not in row or 'ema100' not in row:
            return 'flat', 0

        # Мульти-таймфреймовый анализ тренда
        ema_diff_short = (row['ema20'] - row['ema50']) / row['ema50'] * 100
        ema_diff_long = (row['ema50'] - row['ema100']) / row['ema100'] * 100

        # Сильный аптренд
        if row['ema20'] > row['ema50'] > row['ema100'] and ema_diff_short > 0.5:
            strength = min(10.0, (abs(ema_diff_short) + abs(ema_diff_long)) / 2)
            return 'up', strength
        # Сильный даунтренд
        elif row['ema20'] < row['ema50'] < row['ema100'] and ema_diff_short < -0.5:
            strength = min(10.0, (abs(ema_diff_short) + abs(ema_diff_long)) / 2)
            return 'down', strength
        else:
            return 'flat', 0
    except Exception as e:
        logger.debug(f"Trend bias error: {e}")
        return 'flat', 0


def calculate_confidence(bias: str, rsi: float, macd: float, macd_signal: float, volume_ratio: float = 1.0) -> float:
    """Рассчитать уверенность в сигнале с улучшенной логикой"""
    confidence = 0.0

    try:
        # RSI с более строгими условиями
        if bias == 'up':
            if 55 < rsi < 65:  # Оптимальная зона для лонга
                confidence += 0.4
            elif 50 < rsi <= 55:
                confidence += 0.2
            elif rsi > 70:  # Перекупленность - снижаем уверенность
                confidence -= 0.2
        elif bias == 'down':
            if 35 < rsi < 45:  # Оптимальная зона для шорта
                confidence += 0.4
            elif 45 <= rsi < 50:
                confidence += 0.2
            elif rsi < 30:  # Перепроданность - снижаем уверенность
                confidence -= 0.2

        # MACD с весами в зависимости от силы сигнала
        if bias == 'up' and macd > macd_signal:
            macd_strength = (macd - macd_signal) / abs(macd_signal) if macd_signal != 0 else 0
            confidence += min(0.4, macd_strength * 0.5)
        elif bias == 'down' and macd < macd_signal:
            macd_strength = (macd_signal - macd) / abs(macd_signal) if macd_signal != 0 else 0
            confidence += min(0.4, macd_strength * 0.5)

        # Объем (если доступен)
        if volume_ratio > 1.2:  # Объем выше среднего
            confidence += 0.1
        elif volume_ratio < 0.8:  # Низкий объем
            confidence -= 0.1

    except Exception as e:
        logger.debug(f"Confidence calculation error: {e}")

    return min(1.0, max(0.0, confidence))


def generate_signal_from_dfs(df_main: pd.DataFrame, df_higher: pd.DataFrame = None) -> Signal:
    try:
        df = add_indicators(df_main)
        if df.empty:
            return Signal('NONE', 'No data', 0, 0, 0, 0, 0, 0)

        last = df.iloc[-1]

        # Проверяем наличие необходимых колонок
        required_cols = ['ema20', 'ema50', 'rsi', 'close']
        if not all(col in last for col in required_cols):
            return Signal('NONE', 'Missing indicators', float(last['close']), 0, 0, 0, 0, 0)

        bias, trend_strength = trend_bias_from_last(last)

        # Проверяем старший таймфрейм если предоставлен - СТРОГАЯ ПРОВЕРКА
        higher_bias = 'flat'
        higher_strength = 0
        if df_higher is not None:
            try:
                dh = add_indicators(df_higher)
                if not dh.empty:
                    higher_bias, higher_strength = trend_bias_from_last(dh.iloc[-1])
            except Exception as e:
                logger.debug(f"Higher timeframe analysis error: {e}")

        # Получаем значения индикаторов с проверками
        rsi = last['rsi']
        macd = last.get('macd', 0)
        macd_signal = last.get('macd_signal', 0)
        atr = last.get('atr', 0)
        volume_ratio = last.get('volume', 1) / last.get('volume_sma', 1) if 'volume_sma' in last else 1.0

        # Рассчитываем уверенность
        confidence = calculate_confidence(bias, rsi, macd, macd_signal, volume_ratio)

        # УСИЛИВАЕМ ТРЕБОВАНИЯ: старший ТФ должен подтверждать сигнал
        if higher_bias != bias and higher_strength > 2:
            confidence *= 0.7  # Штрафуем за расхождение с старшим ТФ
        elif higher_bias == bias and higher_strength > 3:
            confidence *= 1.2  # Усиливаем за подтверждение

        entry = float(last['close'])

        # БОЛЕЕ СТРОГИЕ УСЛОВИЯ ДЛЯ LONG
        long_conditions = [
            bias == 'up',
            higher_bias == 'up',  # Обязательное подтверждение старшим ТФ
            macd > macd_signal if 'macd' in last else False,
            55 < rsi < 70,  # Уже диапазон
            entry > last['ema20'],  # Цена выше EMA20
            trend_strength > 1.0,  # Минимальная сила тренда
            confidence > 0.5  # Повышенный порог уверенности
        ]

        # БОЛЕЕ СТРОГИЕ УСЛОВИЯ ДЛЯ SHORT
        short_conditions = [
            bias == 'down',
            higher_bias == 'down',  # Обязательное подтверждение старшим ТФ
            macd < macd_signal if 'macd' in last else False,
            30 < rsi < 45,  # Уже диапазон
            entry < last['ema20'],  # Цена ниже EMA20
            trend_strength > 1.0,  # Минимальная сила тренда
            confidence > 0.5  # Повышенный порог уверенности
        ]

        long_score = sum(long_conditions)
        short_score = sum(short_conditions)

        # Используем ATR или фиксированный процент для стоп-лосса
        atr_stop = atr * 2.0 if atr > 0 else entry * 0.03  # 3% если ATR не доступен

        # ПОВЫШАЕМ ПОРОГ ДЛЯ СИГНАЛОВ
        if long_score >= 5:  # 5 из 7 условий
            stop = entry - atr_stop
            risk = entry - stop
            tp1 = entry + risk * 1.0
            tp2 = entry + risk * 1.5
            tp3 = entry + risk * 2.0
            reason = f"STRONG LONG: Multi-TF confirmation, RSI {rsi:.1f}, Trend strength: {trend_strength:.1f}"
            return Signal('LONG', reason, entry, stop, tp1, tp2, tp3, confidence)

        elif short_score >= 5:  # 5 из 7 условий
            stop = entry + atr_stop
            risk = stop - entry
            tp1 = entry - risk * 1.0
            tp2 = entry - risk * 1.5
            tp3 = entry - risk * 2.0
            reason = f"STRONG SHORT: Multi-TF confirmation, RSI {rsi:.1f}, Trend strength: {trend_strength:.1f}"
            return Signal('SHORT', reason, entry, stop, tp1, tp2, tp3, confidence)

        return Signal('NONE',
                      f'No strong confluence (LONG: {long_score}/7, SHORT: {short_score}/7, confidence: {confidence:.1%})',
                      entry, entry, entry, entry, entry, confidence)

    except Exception as e:
        logger.error(f"Error generating signal: {e}")
        return Signal('NONE', f'Error: {str(e)}', 0, 0, 0, 0, 0, 0)