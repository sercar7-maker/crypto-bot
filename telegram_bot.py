# ============================================================
# telegram_bot.py — Асинхронный Telegram-бот для уведомлений
# Использует python-telegram-bot версии 20.x
# ============================================================

import logging
import os
import re
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
from telegram.constants import ParseMode

import config
import database

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Файл для хранения приоритетных монет
PRIORITY_FILE = 'priority_coins.txt'


# ============================================================
# Работа с файлом приоритетных монет
# ============================================================
def load_priority_coins() -> list:
    """Загружает список приоритетных монет из файла."""
    try:
        if os.path.exists(PRIORITY_FILE):
            with open(PRIORITY_FILE, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        logger.error(f"Ошибка загрузки приоритетных монет: {e}")
    return []


def save_priority_coins(coins: list):
    """Сохраняет список приоритетных монет в файл атомарно."""
    try:
        dir_name = os.path.dirname(os.path.abspath(PRIORITY_FILE))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                for coin in coins:
                    f.write(f"{coin}\n")
            os.replace(tmp_path, PRIORITY_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Ошибка сохранения приоритетных монет: {e}")


# ============================================================
# Экранирование для MarkdownV2
# ============================================================
def escape_md(text: str) -> str:
    """Экранирует специальные символы для MarkdownV2."""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def get_trade_url(exchange_name: str, symbol: str) -> str:
    """Генерирует URL торговой пары для конкретной биржи."""
    try:
        base, quote = symbol.split('/')
        exchange_lower = exchange_name.lower().strip()

        if exchange_lower == 'binance':
            return f"https://www.binance.com/en/trade/{base}_{quote}"
        elif exchange_lower == 'bybit':
            return f"https://www.bybit.com/trade/spot/{base}/{quote}"
        else:
            return ""
    except Exception as e:
        logger.error(f"Ошибка при генерации URL для {symbol} на {exchange_name}: {e}")
        return ""


# ============================================================
# Отправка сигналов
# ============================================================
async def send_alert(context, exchange_name: str, symbol: str, signal_type: str,
                     price_change: float, volume_ratio: float, current_price: float,
                     ema: float, has_divergence: bool = False):
    """Формирует и отправляет красивое сообщение о сигнале в Telegram."""
    try:
        logger.info(f"[send_alert] Сигнал: {symbol}, биржа: {exchange_name}, тип: {signal_type}")

        exchange_display = exchange_name.capitalize() if exchange_name.lower() in ['binance', 'bybit'] else exchange_name
        exchange_label = f"*Биржа:* {escape_md(exchange_display)}\n"

        if signal_type == 'pump':
            message = (
                f"🚀 *{escape_md('ПАМП!')}* 🚀\n\n"
                f"{exchange_label}"
                f"*Символ:* `{symbol}`\n"
                f"*Рост:* \\+{price_change}%\n"
                f"*Объём:* {volume_ratio}x среднего\n"
                f"*Цена:* `{current_price}`\n"
                f"*EMA20:* `{ema}`"
            )
        elif signal_type == 'dump':
            message = (
                f"📉 *{escape_md('ДАМП!')}* 📉\n\n"
                f"{exchange_label}"
                f"*Символ:* `{symbol}`\n"
                f"*Падение:* {price_change}%\n"
                f"*Объём:* {volume_ratio}x среднего\n"
                f"*Цена:* `{current_price}`\n"
                f"*EMA20:* `{ema}`"
            )
            if has_divergence:
                message += "\n*Дивергенция:* ✅ Обнаружена"
        else:
            logger.warning(f"Неизвестный тип сигнала: {signal_type}")
            return

        # Генерируем URL и создаём кнопку
        reply_markup = None
        if exchange_name:
            trade_url = get_trade_url(exchange_name, symbol)
            if trade_url:
                if exchange_name.lower() == 'binance':
                    button_text = "🟡 Открыть на Binance"
                elif exchange_name.lower() == 'bybit':
                    button_text = "🟠 Открыть на Bybit"
                else:
                    button_text = f"🔗 Открыть на {exchange_name}"

                keyboard = [[InlineKeyboardButton(button_text, url=trade_url)]]
                reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=config.CHAT_ID,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=reply_markup
        )
        logger.info(f"✅ Алерт отправлен: {symbol} ({signal_type}) на бирже {exchange_name}")

    except Exception as e:
        logger.error(f"❌ Ошибка при отправке алерта для {symbol}: {type(e).__name__}: {e}", exc_info=True)


# ============================================================
# Главное меню
# ============================================================
def get_main_menu_keyboard():
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить монету", callback_data="menu_add_coin")],
        [InlineKeyboardButton("➖ Удалить монету", callback_data="menu_remove_coin")],
        [InlineKeyboardButton("📋 Список монет", callback_data="menu_list_coins")],
        [InlineKeyboardButton("📊 Статус", callback_data="menu_status")],
        [InlineKeyboardButton("🆘 Помощь", callback_data="menu_help")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_main_menu(target, text: str = None):
    """Отправляет или редактирует сообщение с главным меню."""
    if text is None:
        text = (
            "👋 *Добро пожаловать в Crypto Scanner Bot*\n\n"
            "Этот бот сканирует криптовалюты и отправляет уведомления о пампах и дампах\\.\n\n"
            "*Выберите действие:*"
        )
    reply_markup = get_main_menu_keyboard()

    if isinstance(target, Update):
        await target.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup
        )
    else:
        await target.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup
        )


# ============================================================
# Команда /start
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие + главное меню в одном сообщении."""
    try:
        context.user_data.pop('action', None)
        await send_main_menu(update)
        logger.info(f"Команда /start от {update.effective_user.username}")
    except Exception as e:
        logger.error(f"Ошибка при обработке /start: {type(e).__name__}: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при обработке команды.")


# ============================================================
# Обработка кнопок меню
# ============================================================
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия кнопок главного меню."""
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data == "menu_add_coin":
            context.user_data['action'] = 'add_coin'
            await query.edit_message_text(
                "📝 *Введите пару монеты*\n"
                "Например: `BTC/USDT`\n\n"
                "Или отправьте /cancel для отмены\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

        elif data == "menu_remove_coin":
            context.user_data['action'] = 'remove_coin'
            await query.edit_message_text(
                "📝 *Введите пару монеты для удаления*\n"
                "Например: `BTC/USDT`\n\n"
                "Или отправьте /cancel для отмены\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

        elif data == "menu_list_coins":
            context.user_data.pop('action', None)
            await _show_list_coins(query)

        elif data == "menu_status":
            context.user_data.pop('action', None)
            await _show_status(query)

        elif data == "menu_help":
            context.user_data.pop('action', None)
            await _show_help(query)

        elif data == "menu_back":
            context.user_data.pop('action', None)
            await send_main_menu(query)

        else:
            await query.edit_message_text("⚠️ Неизвестная команда")

    except Exception as e:
        logger.error(f"Ошибка в menu_callback: {type(e).__name__}: {e}", exc_info=True)
        try:
            await query.edit_message_text(f"❌ Ошибка: {type(e).__name__}")
        except Exception:
            pass


# ============================================================
# Обработка текстового ввода
# ============================================================
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текстовый ввод пользователя во время диалога."""
    action = context.user_data.get('action')

    if not action:
        return

    text = update.message.text.strip()
    symbol = text.upper()

    if not re.match(r'^[A-Z]+/[A-Z]+$', symbol):
        await update.message.reply_text(
            "❌ Неверный формат\\. Введите пару как `BTC/USDT`\n"
            "Или /cancel для отмены\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    priority_coins = load_priority_coins()

    if action == 'add_coin':
        if symbol in priority_coins:
            await update.message.reply_text(
                f"ℹ️ Монета `{symbol}` уже в приоритетном списке\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            priority_coins.append(symbol)
            save_priority_coins(priority_coins)
            await update.message.reply_text(
                f"✅ Монета `{symbol}` добавлена в приоритетный список\\!",
                parse_mode=ParseMode.MARKDOWN_V2
            )

    elif action == 'remove_coin':
        if symbol in priority_coins:
            priority_coins.remove(symbol)
            save_priority_coins(priority_coins)
            await update.message.reply_text(
                f"🗑️ Монета `{symbol}` удалена из приоритетного списка\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            await update.message.reply_text(
                f"ℹ️ Монета `{symbol}` не найдена в приоритетном списке\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )

    context.user_data.pop('action', None)


# ============================================================
# Отмена
# ============================================================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет текущее действие и возвращает в главное меню."""
    context.user_data.pop('action', None)
    await update.message.reply_text(
        "❌ Действие отменено\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    await send_main_menu(update)


# ============================================================
# Вспомогательные функции
# ============================================================
async def _show_list_coins(query):
    """Показывает список приоритетных монет."""
    priority_coins = load_priority_coins()
    if priority_coins:
        text = "*📋 Приоритетные монеты:*\n\n"
        for i, coin in enumerate(priority_coins, 1):
            text += f"{i}\\. `{coin}`\n"
        text += f"\n*Всего:* `{len(priority_coins)}` монет"
    else:
        text = "ℹ️ Приоритетных монет пока нет\\."

    keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)


async def _show_status(query):
    """Показывает статус бота и статистику."""
    try:
        exchanges_to_scan = getattr(config, 'EXCHANGES_TO_SCAN', [config.ACTIVE_EXCHANGE])
        exchanges_display = ', '.join([e.capitalize() for e in exchanges_to_scan])

        scan_count = config.TOP_COINS_COUNT
        priority_coins = load_priority_coins()

        try:
            await database.init_db()
        except Exception as e:
            logger.warning(f"Не удалось инициализировать БД: {e}")

        stats = await database.get_stats()

        status_text = (
            f"📊 *Статус бота*\n\n"
            f"*Биржи:* `{exchanges_display}`\n"
            f"*Монет в скане:* `{scan_count}`\n"
            f"*Приоритетных монет:* `{len(priority_coins)}`\n"
            f"*Интервал:* `{config.SCAN_INTERVAL_SECONDS}` сек\n\n"
            f"*Статистика за 24 часа:*\n"
            f"• Всего сигналов: `{stats['total']}`\n"
            f"• Пампов: `{stats['pumps']}`\n"
            f"• Дампов: `{stats['dumps']}`"
        )

        recent = await database.get_recent_signals(limit=10)
        if recent:
            status_text += "\n\n*📋 Последние сигналы:*\n"
            for i, (symbol, signal_type, price, price_change, ts) in enumerate(recent, 1):
                emoji = "🚀" if signal_type == 'pump' else "📉"
                sign = "+" if signal_type == 'pump' else ""
                safe_symbol = symbol.replace('_', '\\_').replace('-', '\\-')
                status_text += f"{i}\\. {emoji} `{safe_symbol}` {sign}{price_change}%\n"

        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(status_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Ошибка в _show_status: {type(e).__name__}: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ Ошибка: `{type(e).__name__}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def _show_help(query):
    """Показывает справку."""
    help_text = (
        "*📖 Список команд:*\n\n"
        "/start \\- главное меню\n"
        "/add\\_coin \\[SYMBOL\\] \\- добавить монету\n"
        "/remove\\_coin \\[SYMBOL\\] \\- удалить монету\n"
        "/list\\_coins \\- показать список приоритетных\n"
        "/status \\- статус и статистика\n"
        "/help \\- эта справка\n"
        "/cancel \\- отменить текущее действие\n\n"
        "*Пороги обнаружения:*\n"
        f"• Памп: рост \\> `{config.PUMP_PRICE_CHANGE_PERCENT}`% за "
        f"`{config.PUMP_TIMEFRAME_MINUTES}` мин, "
        f"объём \\> `{config.PUMP_VOLUME_MULTIPLIER}`x\n"
        f"• Дамп: падение \\> `{config.DUMP_PRICE_CHANGE_PERCENT}`% за "
        f"`{config.DUMP_TIMEFRAME_MINUTES}` мин, "
        f"объём \\> `{config.DUMP_VOLUME_MULTIPLIER}`x"
    )

    keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)


# ============================================================
# Команды с аргументами или без
# ============================================================
async def add_coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /add_coin."""
    if context.args:
        symbol = context.args[0].upper()
        if re.match(r'^[A-Z]+/[A-Z]+$', symbol):
            priority_coins = load_priority_coins()
            if symbol in priority_coins:
                await update.message.reply_text(
                    f"ℹ️ Монета `{symbol}` уже в списке\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                priority_coins.append(symbol)
                save_priority_coins(priority_coins)
                await update.message.reply_text(
                    f"✅ Монета `{symbol}` добавлена\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await update.message.reply_text(
                "❌ Неверный формат\\. Пример: `/add_coin ADA/USDT`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    else:
        context.user_data['action'] = 'add_coin'
        await update.message.reply_text(
            "📝 *Введите пару монеты*\n"
            "Например: `BTC/USDT`\n\n"
            "Или /cancel для отмены\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def remove_coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /remove_coin."""
    if context.args:
        symbol = context.args[0].upper()
        if re.match(r'^[A-Z]+/[A-Z]+$', symbol):
            priority_coins = load_priority_coins()
            if symbol in priority_coins:
                priority_coins.remove(symbol)
                save_priority_coins(priority_coins)
                await update.message.reply_text(
                    f"🗑️ Монета `{symbol}` удалена\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ Монета `{symbol}` не найдена\\.",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
        else:
            await update.message.reply_text(
                "❌ Неверный формат\\. Пример: `/remove_coin ADA/USDT`",
                parse_mode=ParseMode.MARKDOWN_V2
            )
    else:
        context.user_data['action'] = 'remove_coin'
        await update.message.reply_text(
            "📝 *Введите пару монеты для удаления*\n"
            "Например: `BTC/USDT`\n\n"
            "Или /cancel для отмены\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def list_coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список приоритетных монет (команда)."""
    priority_coins = load_priority_coins()
    if priority_coins:
        text = "*📋 Приоритетные монеты:*\n\n"
        for i, coin in enumerate(priority_coins, 1):
            text += f"{i}\\. `{coin}`\n"
        text += f"\n*Всего:* `{len(priority_coins)}` монет"
    else:
        text = "ℹ️ Приоритетных монет пока нет\\."
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус бота (команда /status) со списком последних сигналов."""
    try:
        exchanges_to_scan = getattr(config, 'EXCHANGES_TO_SCAN', [config.ACTIVE_EXCHANGE])
        exchanges_display = ', '.join([e.capitalize() for e in exchanges_to_scan])

        scan_count = config.TOP_COINS_COUNT
        priority_coins = load_priority_coins()

        try:
            await database.init_db()
        except Exception as e:
            logger.warning(f"Не удалось инициализировать БД: {e}")

        stats = await database.get_stats()

        status_text = (
            f"📊 *Статус бота*\n\n"
            f"*Биржи:* `{exchanges_display}`\n"
            f"*Монет в скане:* `{scan_count}`\n"
            f"*Приоритетных монет:* `{len(priority_coins)}`\n"
            f"*Интервал:* `{config.SCAN_INTERVAL_SECONDS}` сек\n\n"
            f"*Статистика за 24 часа:*\n"
            f"• Всего сигналов: `{stats['total']}`\n"
            f"• Пампов: `{stats['pumps']}`\n"
            f"• Дампов: `{stats['dumps']}`"
        )

        # Добавляем последние сигналы
        recent = await database.get_recent_signals(limit=10)
        if recent:
            status_text += "\n\n*📋 Последние сигналы:*\n"
            for i, (symbol, signal_type, price, price_change, ts) in enumerate(recent, 1):
                emoji = "🚀" if signal_type == 'pump' else "📉"
                sign = "+" if signal_type == 'pump' else ""
                safe_symbol = symbol.replace('_', '\\_').replace('-', '\\-')
                status_text += f"{i}\\. {emoji} `{safe_symbol}` {sign}{price_change}%\n"

        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)

    except Exception as e:
        logger.error(f"Ошибка в status_command: {type(e).__name__}: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Ошибка: `{type(e).__name__}`",
            parse_mode=ParseMode.MARKDOWN_V2
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает справку (команда)."""
    help_text = (
        "*📖 Список команд:*\n\n"
        "/start \\- главное меню\n"
        "/add\\_coin \\[SYMBOL\\] \\- добавить монету\n"
        "/remove\\_coin \\[SYMBOL\\] \\- удалить монету\n"
        "/list\\_coins \\- показать список приоритетных\n"
        "/status \\- статус и статистика\n"
        "/help \\- эта справка\n"
        "/cancel \\- отменить текущее действие\n\n"
        "*Пороги обнаружения:*\n"
        f"• Памп: рост \\> `{config.PUMP_PRICE_CHANGE_PERCENT}`% за "
        f"`{config.PUMP_TIMEFRAME_MINUTES}` мин, "
        f"объём \\> `{config.PUMP_VOLUME_MULTIPLIER}`x\n"
        f"• Дамп: падение \\> `{config.DUMP_PRICE_CHANGE_PERCENT}`% за "
        f"`{config.DUMP_TIMEFRAME_MINUTES}` мин, "
        f"объём \\> `{config.DUMP_VOLUME_MULTIPLIER}`x"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)


# ============================================================
# Запуск бота
# ============================================================
def run_bot():
    """Создаёт Application и запускает бота."""
    try:
        application = Application.builder().token(config.BOT_TOKEN).build()

        application.add_handler(CallbackQueryHandler(menu_callback, pattern='^menu_'))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('cancel', cancel))
        application.add_handler(CommandHandler('add_coin', add_coin_command))
        application.add_handler(CommandHandler('remove_coin', remove_coin_command))
        application.add_handler(CommandHandler('list_coins', list_coins_command))
        application.add_handler(CommandHandler('status', status_command))
        application.add_handler(CommandHandler('help', help_command))

        logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {type(e).__name__}: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    run_bot()