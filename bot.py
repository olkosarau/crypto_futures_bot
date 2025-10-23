import os, asyncio, logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from data import fetch_klines
from strategies import generate_signal_from_dfs
from exchange import place_market_order, close_position_order  # Добавляем close_position_order
from db import init_db, log_trade, log_signal, open_position, close_position, get_open_positions, get_portfolio_summary  # Добавляем новые функции
from reports import generate_weekly_report
from market_scanner import scanner
from portfolio_manager import update_portfolio_prices  # Этот импорт теперь должен работать
from fastapi import FastAPI, Request
import uvicorn
import threading
import httpx
from dotenv import load_dotenv
from web_interface import web_app, notify_websocket_clients

load_dotenv()
app = web_app
web_app_url = "https://olkosarau.github.io/crypto_futures_bot/"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
SIGNAL_INTERVAL = int(os.getenv('SIGNAL_CHECK_INTERVAL_SEC', '300'))
SUBSCRIBE_SYMBOLS = os.getenv('SUBSCRIBE_SYMBOLS', 'BTCUSDT,ETHUSDT').split(',')

if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN not found in environment variables")
    exit(1)

if not CHAT_ID:
    logger.error("TELEGRAM_CHAT_ID not found in environment variables")
    exit(1)

logger.info(f"Bot initialized for chat: {CHAT_ID}")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()


keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌐 Открыть WEB", web_app=WebAppInfo(url=web_app_url))]
    ],
    resize_keyboard=True
)

def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="🔍 Сканировать рынок")],
            [KeyboardButton(text="📈 Отчет"), KeyboardButton(text="💼 Торговля")],
            [KeyboardButton(text="✅ Вкл сигналы"), KeyboardButton(text="❌ Выкл сигналы")],
            [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="❓ Помощь")],
            [KeyboardButton(
                text="🌐 Дашборд WEB",
                web_app=WebAppInfo(url=web_app_url)
            )]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )
    return keyboard


def get_trading_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📈 LONG"), KeyboardButton(text="📉 SHORT")],
            [KeyboardButton(text="🔒 CLOSE"), KeyboardButton(text="📊 Портфель")],
            [KeyboardButton(text="🔙 Назад в меню")]
        ],
        resize_keyboard=True
    )
    return keyboard


@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    inline_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть WEB", web_app=WebAppInfo(url=web_app_url))]
        ]
    )
    await message.answer(
        "🤖 <b>Торговый Бот активирован</b>\n\n"
        "Я помогу вам анализировать рынок и получать торговые сигналы.\n\n"
        "<b>Основные команды:</b>\n"
        "• /start - показать это сообщение\n"
        "• /help - помощь\n"
        "• /status - статус бота\n"
        "• /signals - проверить сигналы\n"
        "• /scan - полное сканирование рынка\n"
        "• /report - недельный отчет\n"
        "• /long SYMBOL QTY - открыть лонг\n"
        "• /short SYMBOL QTY - открыть шорт\n"
        "• /close SYMBOL - закрыть позицию",
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    await message.answer(
        "🆘 <b>Помощь по командам и функциям</b>\n\n"

        "<b>🤖 Автоматическая торговля:</b>\n"
        "• Бот автоматически сканирует рынок и ищет сигналы\n"
        "• Сигналы приходят каждые 5 минут\n"
        "• Используйте кнопки 'Вкл/Выкл сигналы' для управления\n\n"

        "<b>💼 Ручная торговля:</b>\n"
        "• Нажмите 'Торговля' для доступа к ручным операциям\n"
        "• <code>/long SYMBOL QTY</code> - открыть лонг позицию\n"
        "• <code>/short SYMBOL QTY</code> - открыть шорт позицию\n"
        "• <code>/close SYMBOL</code> - закрыть позицию\n\n"

        "<b>📊 Аналитика и отчеты:</b>\n"
        "• <code>/signals</code> - проверить сигналы сейчас\n"
        "• <code>/scan</code> - полное сканирование рынка\n"
        "• <code>/report</code> - сгенерировать недельный отчет\n"
        "• <code>/status</code> - статус бота\n\n"

        "<b>⚙️ Управление:</b>\n"
        "• <code>/signals_on</code> - включить автоматические сигналы\n"
        "• <code>/signals_off</code> - выключить автоматические сигналы\n\n"

        "<i>Примеры команд смотрите в разделе 'Торговля'</i>",
        parse_mode='HTML'
    )


@dp.message(Command('status'))
async def cmd_status(message: types.Message):
    status_text = (
        "📊 <b>Статус бота:</b>\n\n"
        f"• <b>Мониторинг:</b> {', '.join(SUBSCRIBE_SYMBOLS)}\n"
        f"• <b>Интервал проверки:</b> {SIGNAL_INTERVAL} сек\n"
        f"• <b>Авто-сигналы:</b> {'✅ ВКЛ' if scheduler.running else '❌ ВЫКЛ'}\n"
        f"• <b>Режим:</b> {'🟢 РЕАЛЬНЫЙ' if not os.getenv('DRY_RUN', 'true').lower() == 'true' else '🟡 ТЕСТОВЫЙ'}\n"
        f"• <b>База данных:</b> {'✅ Активна' if os.path.exists('data/bot.db') else '❌ Неактивна'}\n\n"
        "<i>Используйте кнопки ниже для управления</i>"
    )
    await message.answer(status_text, parse_mode='HTML')


@dp.message(Command('signals'))
async def cmd_signals_now(message: types.Message):
    await message.answer("🔍 Запускаю проверку сигналов...")
    await check_signals(notify_user=message.chat.id)


@dp.message(Command('scan'))
async def cmd_scan(message: types.Message):
    """Сканировать весь рынок на сигналы"""
    await message.answer("🔍 Запускаю полное сканирование рынка...")
    await check_signals(notify_user=message.chat.id)


@dp.message(Command('weekly_report'))
async def cmd_weekly(message: types.Message):
    try:
        await message.answer("📊 Генерирую недельный отчет... Это может занять несколько секунд.")

        # Показываем что бот работает
        await bot.send_chat_action(message.chat.id, "typing")

        path = generate_weekly_report()

        if path and os.path.exists(path):
            file_size = os.path.getsize(path) / 1024  # Размер в KB
            logger.info(f"Report file size: {file_size:.1f} KB")

            if file_size > 0:
                await bot.send_document(
                    message.chat.id,
                    types.FSInputFile(path),
                    caption="📈 Ваш недельный торговый отчет"
                )
                await message.answer("✅ Отчет успешно сгенерирован и отправлен!")

                # Удаляем временный файл после отправки
                try:
                    os.remove(path)
                except:
                    pass
            else:
                await message.answer("❌ Отчет создан, но файл пустой")
        else:
            await message.answer("❌ Не удалось создать отчет. Проверьте логи для подробностей.")

    except Exception as e:
        logger.error(f"Report generation error: {e}")
        await message.answer(f"❌ Ошибка при генерации отчета: {str(e)}")


@dp.message(Command('signals_on'))
async def cmd_signals_on(message: types.Message):
    if not scheduler.running:
        scheduler.start()
    scheduler.resume()
    await message.answer("✅ Автоматические сигналы включены")


@dp.message(Command('signals_off'))
async def cmd_signals_off(message: types.Message):
    scheduler.pause()
    await message.answer("❌ Автоматические сигналы выключены")


@dp.message(Command('long', 'short'))
async def manual_trade(message: types.Message):
    try:
        parts = message.text.split()
        cmd = parts[0].lstrip('/').lower()

        if len(parts) < 3:
            await message.answer(
                f"❌ <b>Неверный формат команды</b>\n\n"
                f"Использование: <code>/{cmd} SYMBOL QTY</code>\n"
                f"Пример: <code>/{cmd} BTCUSDT 0.01</code>\n\n"
                f"<i>Доступные символы: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, LINKUSDT, MATICUSDT</i>",
                parse_mode='HTML'
            )
            return

        symbol = parts[1].upper()
        valid_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'AVAXUSDT', 'DOTUSDT', 'LINKUSDT',
                         'MATICUSDT']

        if symbol not in valid_symbols:
            await message.answer(
                f"❌ <b>Неверный символ</b>\n\n"
                f"Символ <code>{symbol}</code> не поддерживается.\n"
                f"Доступные символы: {', '.join(valid_symbols)}",
                parse_mode='HTML'
            )
            return

        try:
            amt = float(parts[2])
            if amt <= 0:
                await message.answer("❌ Количество должно быть больше 0")
                return
        except ValueError:
            await message.answer("❌ Неверное количество. Используйте числовое значение (например: 0.01)")
            return

        side = 'BUY' if cmd == 'long' else 'SELL'
        action = 'LONG' if cmd == 'long' else 'SHORT'
        emoji = "📈" if cmd == 'long' else "📉"

        await message.answer(f"{emoji} Размещаю ордер {action} для {symbol}...")

        # Показываем что бот работает
        await bot.send_chat_action(message.chat.id, "typing")

        # Получаем текущую цену для записи в позицию
        from data import fetch_klines
        try:
            df = await fetch_klines(symbol, '1m', limit=1)
            current_price = float(df.iloc[-1]['close']) if not df.empty else 0
        except:
            current_price = 0

        res = await place_market_order(symbol, side, amt)

        if res.success:
            # Логируем сделку и открываем позицию
            log_trade(symbol, side, amt, current_price)
            open_position(symbol, side, amt, current_price)

            await message.answer(
                f"✅ <b>Ордер размещен!</b>\n\n"
                f"• <b>Символ:</b> {symbol}\n"
                f"• <b>Направление:</b> {action}\n"
                f"• <b>Количество:</b> {amt}\n"
                f"• <b>Цена входа:</b> {current_price:.4f}\n"
                f"• <b>Тип:</b> MARKET\n"
                f"• <b>Режим:</b> {'🟡 ТЕСТОВЫЙ' if os.getenv('DRY_RUN', 'true').lower() == 'true' else '🟢 РЕАЛЬНЫЙ'}\n\n"
                f"<i>Используйте /close {symbol} для закрытия позиции</i>",
                parse_mode='HTML'
            )

            logger.info(f"Manual {action} order: {symbol} {amt} at {current_price}")

        else:
            error_msg = res.info.get('error', 'Unknown error')
            await message.answer(
                f"❌ <b>Ошибка ордера</b>\n\n"
                f"• <b>Символ:</b> {symbol}\n"
                f"• <b>Направление:</b> {action}\n"
                f"• <b>Ошибка:</b> {error_msg}\n\n"
                f"<i>Попробуйте снова или проверьте параметры</i>",
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f"Trade error: {e}")
        await message.answer(
            f"❌ <b>Ошибка при размещении ордера</b>\n\n"
            f"<i>Детали: {str(e)}</i>\n\n"
            f"Проверьте:\n"
            f"• Формат команды\n"
            f"• Корректность символа\n"
            f"• Числовое значение количества",
            parse_mode='HTML'
        )


@dp.message(Command('close'))
async def cmd_close(message: types.Message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ <b>Неверный формат команды</b>\n\n"
                "Использование: <code>/close SYMBOL</code>\n"
                "Пример: <code>/close BTCUSDT</code>",
                parse_mode='HTML'
            )
            return

        symbol = parts[1].upper()

        # Проверяем есть ли открытая позиция
        open_positions = get_open_positions()
        position_exists = any(pos['symbol'] == symbol for pos in open_positions)

        if not position_exists:
            await message.answer(
                f"❌ <b>Позиция не найдена</b>\n\n"
                f"Открытой позиции для <code>{symbol}</code> не найдено.\n\n"
                f"<i>Используйте /long или /short чтобы открыть позицию</i>",
                parse_mode='HTML'
            )
            return

        await message.answer(f"🔒 Закрываю позицию {symbol}...")

        # Показываем что бот работает
        await bot.send_chat_action(message.chat.id, "typing")

        # Закрываем позицию
        res = await close_position_order(symbol)

        if res.success:
            # Закрываем позицию в базе данных
            close_position(symbol)

            await message.answer(
                f"✅ <b>Позиция закрыта!</b>\n\n"
                f"• <b>Символ:</b> {symbol}\n"
                f"• <b>Статус:</b> ЗАКРЫТО\n"
                f"• <b>Режим:</b> {'🟡 ТЕСТОВЫЙ' if os.getenv('DRY_RUN', 'true').lower() == 'true' else '🟢 РЕАЛЬНЫЙ'}\n\n"
                f"<i>Позиция успешно закрыта</i>",
                parse_mode='HTML'
            )

            logger.info(f"Closed position: {symbol}")

        else:
            error_msg = res.info.get('error', 'Unknown error')
            await message.answer(
                f"❌ <b>Ошибка при закрытии позиции</b>\n\n"
                f"• <b>Символ:</b> {symbol}\n"
                f"• <b>Ошибка:</b> {error_msg}",
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f"Close position error: {e}")
        await message.answer(
            f"❌ <b>Ошибка при закрытии позиции</b>\n\n"
            f"<i>Детали: {str(e)}</i>",
            parse_mode='HTML'
        )


# Обработчики кнопок главного меню
@dp.message(F.text == "📊 Статус")
async def button_status(message: types.Message):
    await cmd_status(message)


@dp.message(F.text == "🔍 Сканировать рынок")
async def button_scan(message: types.Message):
    await cmd_scan(message)


@dp.message(F.text == "📈 Отчет")
async def button_report(message: types.Message):
    await cmd_weekly(message)


@dp.message(F.text == "✅ Вкл сигналы")
async def button_signals_on(message: types.Message):
    await cmd_signals_on(message)


@dp.message(F.text == "❌ Выкл сигналы")
async def button_signals_off(message: types.Message):
    await cmd_signals_off(message)


@dp.message(F.text == "❓ Помощь")
async def button_help(message: types.Message):
    await cmd_help(message)


@dp.message(F.text == "💰 Баланс")
async def button_balance(message: types.Message):
    await message.answer("💼 Функция проверки баланса в разработке")


@dp.message(F.text == "⚙️ Настройки")
async def button_settings(message: types.Message):
    settings_text = (
        "⚙️ <b>Настройки бота:</b>\n\n"
        f"• <b>Символы:</b> {', '.join(SUBSCRIBE_SYMBOLS)}\n"
        f"• <b>Интервал:</b> {SIGNAL_INTERVAL} сек\n"
        f"• <b>Режим:</b> {'РЕАЛЬНЫЙ' if not os.getenv('DRY_RUN', 'true').lower() == 'true' else 'ТЕСТОВЫЙ'}\n\n"
        "Для изменения настроек отредактируйте файл .env"
    )
    await message.answer(settings_text, parse_mode='HTML')


# Обработчики кнопок торговли
@dp.message(F.text == "💼 Торговля")
async def button_trading(message: types.Message):
    await message.answer(
        "💼 <b>Режим ручной торговли</b>\n\n"
        "Выберите действие или используйте команды:\n"
        "• /long SYMBOL QTY - открыть лонг\n"
        "• /short SYMBOL QTY - открыть шорт\n"
        "• /close SYMBOL - закрыть позицию\n\n"
        "<i>Пример: /long BTCUSDT 0.01</i>",
        parse_mode='HTML',
        reply_markup=get_trading_keyboard()
    )


@dp.message(F.text == "📈 LONG")
async def button_long(message: types.Message):
    await message.answer(
        "📈 <b>Открытие LONG позиции</b>\n\n"
        "Для открытия LONG позиции используйте команду:\n"
        "<code>/long SYMBOL QTY</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>/long BTCUSDT 0.01</code>\n"
        "<code>/long ETHUSDT 0.1</code>\n"
        "<code>/long SOLUSDT 1.0</code>\n\n"
        "<i>Режим: 🟡 ТЕСТОВЫЙ (ордера не исполняются на бирже)</i>",
        parse_mode='HTML'
    )


@dp.message(F.text == "📉 SHORT")
async def button_short(message: types.Message):
    await message.answer(
        "📉 <b>Открытие SHORT позиции</b>\n\n"
        "Для открытия SHORT позиции используйте команду:\n"
        "<code>/short SYMBOL QTY</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>/short BTCUSDT 0.01</code>\n"
        "<code>/short ETHUSDT 0.1</code>\n"
        "<code>/short SOLUSDT 1.0</code>\n\n"
        "<i>Режим: 🟡 ТЕСТОВЫЙ (ордера не исполняются на бирже)</i>",
        parse_mode='HTML'
    )


@dp.message(F.text == "🔒 CLOSE")
async def button_close(message: types.Message):
    await message.answer(
        "🔒 <b>Закрытие позиции</b>\n\n"
        "Для закрытия позиции используйте команду:\n"
        "<code>/close SYMBOL</code>\n\n"
        "<b>Примеры:</b>\n"
        "<code>/close BTCUSDT</code>\n"
        "<code>/close ETHUSDT</code>\n"
        "<code>/close SOLUSDT</code>\n\n"
        "<i>Сначала откройте позицию через /long или /short</i>",
        parse_mode='HTML'
    )


@dp.message(F.text == "📊 Портфель")
async def button_portfolio(message: types.Message):
    try:
        portfolio = get_portfolio_summary()

        if portfolio['total_positions'] == 0:
            await message.answer(
                "📊 <b>Портфель</b>\n\n"
                "У вас нет открытых позиций.\n\n"
                "<i>Используйте /long или /short чтобы открыть позиции</i>",
                parse_mode='HTML'
            )
            return

        text = "📊 <b>Ваш портфель</b>\n\n"
        text += f"• <b>Открытых позиций:</b> {portfolio['total_positions']}\n"
        text += f"• <b>Общий PnL:</b> {portfolio['total_pnl']:.2f} USDT\n\n"

        text += "<b>Открытые позиции:</b>\n"
        for pos in portfolio['positions']:
            emoji = "📈" if pos['side'] == 'BUY' else "📉"
            pnl_emoji = "🟢" if pos['pnl'] > 0 else "🔴"
            text += f"\n{emoji} <b>{pos['symbol']}</b> {pos['side']}\n"
            text += f"   Количество: {pos['qty']}\n"
            text += f"   Цена входа: {pos['entry_price']:.4f}\n"
            text += f"   Текущая цена: {pos['current_price']:.4f}\n"
            text += f"   {pnl_emoji} PnL: {pos['pnl']:.2f} USDT\n"
            text += f"   <code>/close {pos['symbol']}</code>\n"

        await message.answer(text, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Portfolio error: {e}")
        await message.answer(
            "❌ <b>Ошибка при получении портфеля</b>\n\n"
            f"<i>Детали: {str(e)}</i>",
            parse_mode='HTML'
        )


@dp.message(F.text == "🔙 Назад в меню")
async def button_back_to_main(message: types.Message):
    await message.answer(
        "🔙 Возвращаюсь в главное меню",
        reply_markup=get_main_keyboard()
    )


# Обработка неизвестных сообщений
@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(
        "🤔 Я не понимаю эту команду.\n\n"
        "Используйте кнопки меню или команду /help для списка доступных команд",
        reply_markup=get_main_keyboard()
    )


async def check_signals(notify_user=None):
    """Проверка торговых сигналов по всем монетам"""
    logger.info("🔍 Scanning market for signals...")

    try:
        # Получаем лучшие сигналы
        best_signals = await scanner.get_best_signals(max_signals=5)

        if not best_signals:
            logger.info("No strong signals found in market scan")
            if notify_user:
                await bot.send_message(notify_user, "📊 Сканирование завершено. Сильных сигналов не найдено.")
            return

        # Отправляем топ сигналы
        for i, signal_data in enumerate(best_signals, 1):
            symbol = signal_data['symbol']
            signal = signal_data['signal']
            strength = signal_data['strength']

            if signal.side != 'NONE':
                # Логируем сигнал
                log_signal(symbol, 'multi', signal.side, signal.entry, signal.stop,
                           signal.tp1, signal.tp2, signal.tp3)

                # Уведомляем веб-интерфейс
                await notify_websocket_clients("new_signal", {
                    "symbol": symbol,
                    "side": signal.side,
                    "entry": signal.entry,
                    "confidence": signal.confidence,
                    "reason": signal.reason
                })

                # Формируем сообщение
                emoji = "🟢" if signal.side == 'LONG' else "🔴"
                strength_emoji = "🔥" * min(strength, 3)

                text = (
                    f"{strength_emoji} <b>СИГНАЛ #{i}</b> {strength_emoji}\n\n"
                    f"• <b>Монета:</b> {symbol}\n"
                    f"• <b>Направление:</b> {emoji} {signal.side}\n"
                    f"• <b>Уверенность:</b> {signal.confidence:.1%}\n"
                    f"• <b>Текущая цена:</b> {signal.entry:.4f}\n\n"
                    f"<b>🎯 Тейк-профиты:</b>\n"
                    f"TP1: {signal.tp1:.4f}\n"
                    f"TP2: {signal.tp2:.4f}\n"
                    f"TP3: {signal.tp3:.4f}\n\n"
                    f"<b>🛑 Стоп-лосс:</b> {signal.stop:.4f}\n\n"
                    f"<i>{signal.reason}</i>"
                )

                # Отправляем владельцу бота
                await bot.send_message(CHAT_ID, text, parse_mode='HTML')
                logger.info(f"Strong signal found: {symbol} {signal.side} (confidence: {signal.confidence:.1%})")

        # Если это ручная проверка, отправляем summary
        if notify_user and len(best_signals) > 0:
            summary = f"📊 Найдено сигналов: {len(best_signals)}"
            await bot.send_message(notify_user, summary)

    except Exception as e:
        logger.error(f"Market scan error: {e}")
        if notify_user:
            await bot.send_message(notify_user, f"❌ Ошибка сканирования рынка: {str(e)}")


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


# Исправляем планировщик - используем асинхронную функцию
@scheduler.scheduled_job('interval', seconds=SIGNAL_INTERVAL)
async def scheduled_check():
    """Планируемая проверка сигналов"""
    try:
        await check_signals()
    except Exception as e:
        logger.error(f"Scheduled check error: {e}")

# ДОБАВЛЯЕМ НОВЫЙ ПЛАНИРОВЩИК ДЛЯ ОБНОВЛЕНИЯ ЦЕН
@scheduler.scheduled_job('interval', seconds=60)  # Обновлять каждую минуту
async def update_prices_job():
    """Планируемое обновление цен в портфеле"""
    try:
        await update_portfolio_prices()
    except Exception as e:
        logger.error(f"Price update job error: {e}")

# FastAPI webhook для TradingView
@app.post('/tradingview')
async def tv_webhook(req: Request):
    try:
        payload = await req.json()
        symbol = payload.get('symbol')
        action = payload.get('action')
        amount = float(payload.get('amount', 0))

        if action in ('LONG', 'SHORT'):
            side = 'BUY' if action == 'LONG' else 'SELL'
            res = await place_market_order(symbol, side, amount)
            if res.success:
                log_trade(symbol, side, amount, 0.0)
                await bot.send_message(CHAT_ID, f'TradingView webhook executed: {action} {symbol} {amount}')
                return {'ok': True, 'info': res.info}
            return {'ok': False, 'error': res.info}
        elif action == 'CLOSE':
            await bot.send_message(CHAT_ID, f'TradingView webhook close requested: {symbol}')
            return {'ok': True, 'info': 'close_requested'}
        return {'ok': False, 'error': 'invalid action'}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {'ok': False, 'error': str(e)}


@app.get('/')
async def root():
    return {'status': 'Bot is running'}

# Добавьте эту задачу в планировщик (после существующей scheduled_check)
@scheduler.scheduled_job('interval', seconds=60)  # Обновлять каждую минуту
async def update_prices_job():
    """Планируемое обновление цен в портфеле"""
    try:
        await update_portfolio_prices()
    except Exception as e:
        logger.error(f"Price update job error: {e}")

# API endpoints для веб-интерфейса
@app.post("/api/scan")
async def api_scan():
    """API для запуска сканирования рынка"""
    try:
        await check_signals()
        return {"status": "scan_started"}
    except Exception as e:
        logger.error(f"API scan error: {e}")
        return {"status": "error", "error": str(e)}

@app.post("/api/report")
async def api_report():
    """API для генерации отчета"""
    try:
        path = generate_weekly_report()
        return {"status": "report_generated", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.post("/api/signals/enable")
async def api_signals_enable():
    """API для включения сигналов"""
    try:
        if not scheduler.running:
            scheduler.start()
        scheduler.resume()
        return {"status": "signals_enabled"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.post("/api/signals/disable")
async def api_signals_disable():
    """API для выключения сигналов"""
    try:
        scheduler.pause()
        return {"status": "signals_disabled"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/api/status")
async def api_status():
    """API статуса бота"""
    try:
        from db import get_portfolio_summary
        portfolio = get_portfolio_summary()
        return {
            "status": "running",
            "open_positions": portfolio['total_positions'],
            "total_pnl": portfolio['total_pnl']
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

def start_uvicorn():
    """Запуск FastAPI сервера"""
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level="info")


async def main():
    """Главная асинхронная функция для запуска бота"""
    try:
        # Инициализация БД
        init_db()
        logger.info("Database initialized")

        # Запуск планировщика
        scheduler.start()
        logger.info("Scheduler started")

        # Запуск FastAPI в отдельном потоке
        t = threading.Thread(target=start_uvicorn, daemon=True)
        t.start()
        logger.info("FastAPI server started on http://0.0.0.0:8000")

        # Уведомление о запуске
        await bot.send_message(
            CHAT_ID,
            "🤖 <b>Бот успешно запущен!</b>\n\n"
            "Все системы работают в нормальном режиме. "
            "Используйте /help для списка команд.",
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )

        logger.info("Bot started successfully!")

        # Запуск бота
        await dp.start_polling(bot)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        # Попытаемся отправить сообщение об ошибке
        try:
            await bot.send_message(CHAT_ID, f"❌ Ошибка запуска бота: {str(e)}")
        except:
            pass
        raise


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")