# ============================================================
# scanner.py — Главный файл сканера криптовалют
# Объединяет все модули и запускает сканирование
# ============================================================

import asyncio
import time
import logging
from datetime import datetime

import config
import analyzer
import database
import telegram_bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================================================
# Загрузка приоритетных монет из файла
# ============================================================
def load_priority_coins() -> list:
    """Загружает список приоритетных монет из файла priority_coins.txt."""
    try:
        with open('priority_coins.txt', 'r', encoding='utf-8') as f:
            coins = [line.strip().upper() for line in f if line.strip() and '/' in line]
            logger.info(f"Загружено {len(coins)} приоритетных монет: {coins}")
            return coins
    except FileNotFoundError:
        logger.info("Файл priority_coins.txt не найден. Приоритетные монеты не загружены.")
        return []
    except Exception as e:
        logger.error(f"Ошибка при загрузке приоритетных монет: {e}")
        return []


# ============================================================
# Логирование с временем
# ============================================================
def log(message: str):
    """Выводит сообщение в консоль с текущим временем."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")


# ============================================================
# Запуск Telegram бота в фоне
# ============================================================
async def run_telegram_bot_async(application: Application):
    """Запускает Telegram бота асинхронно в отдельной задаче."""
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        
        log("✅ Telegram бот запущен в фоновом режиме")
        
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Ошибка при запуске Telegram бота: {e}")


# ============================================================
# Обработка сигнала (памп или дамп)
# ============================================================
async def process_signal(application: Application, symbol: str, signal_type: str, 
                         result: dict, exchange_name: str = ''):
    """Обрабатывает найденный сигнал: проверяет кулдаун, отправляет алерт, сохраняет в БД."""
    try:
        cooldown_key = f"{exchange_name}:{symbol}" if exchange_name else symbol
        
        last_alert = await database.get_last_alert(cooldown_key)
        current_time = time.time()
        
        if last_alert is not None and (current_time - last_alert) <= config.COOLDOWN_SECONDS:
            log(f"⏸️  [{exchange_name}] {symbol} ({signal_type}): кулдаун ещё не прошёл "
                f"(осталось {int(config.COOLDOWN_SECONDS - (current_time - last_alert))} сек)")
            return
        
        price_change = result['price_change']
        volume_ratio = result['volume_ratio']
        current_price = result['current_price']
        ema = result['ema']
        has_divergence = result.get('has_divergence', False)
        
        bot = application.bot
        
        class FakeContext:
            def __init__(self, bot):
                self.bot = bot
        
        context = FakeContext(bot)
        
        log(f"📤 Отправка алерта в Telegram: {symbol} ({signal_type}) с биржи {exchange_name}")
        await telegram_bot.send_alert(
            context=context,
            exchange_name=exchange_name,
            symbol=symbol,
            signal_type=signal_type,
            price_change=price_change,
            volume_ratio=volume_ratio,
            current_price=current_price,
            ema=ema,
            has_divergence=has_divergence
        )
        
        await database.save_signal(
            symbol=f"[{exchange_name}] {symbol}" if exchange_name else symbol,
            signal_type=signal_type,
            price=current_price,
            volume=result['volume_5min'],
            price_change=price_change
        )
        
        await database.update_cooldown(cooldown_key)
        
        log(f"✅ [{exchange_name}] {symbol} ({signal_type}): сигнал отправлен | "
            f"Цена: {current_price} | Изменение: {price_change}% | Объём: {volume_ratio}x")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сигнала [{exchange_name}] {symbol} ({signal_type}): {e}")


# ============================================================
# Сканирование одной биржи
# ============================================================
async def scan_exchange(exchange, exchange_name: str, application, priority_coins: list):
    """Сканирует одну биржу: получает топ монет и проверяет каждую."""
    try:
        top_symbols = analyzer.get_top_symbols(
            exchange, 
            config.TOP_COINS_COUNT, 
            config.STOP_COINS
        )
        
        if not top_symbols:
            log(f"⚠️  [{exchange_name}] Не удалось получить топ монет.")
            return 0
        
        log(f"📈 [{exchange_name}] Получено {len(top_symbols)} монет")
        
        all_symbols = list(set(top_symbols + priority_coins))
        log(f"📋 [{exchange_name}] Всего монет для проверки: {len(all_symbols)}")
        
        for i, symbol in enumerate(all_symbols, 1):
            try:
                pump_result = analyzer.check_pump(symbol, exchange)
                if pump_result['is_pump']:
                    await process_signal(application, symbol, 'pump', pump_result, exchange_name)
                
                dump_result = analyzer.check_dump(symbol, exchange)
                if dump_result['is_dump']:
                    await process_signal(application, symbol, 'dump', dump_result, exchange_name)
                
                await asyncio.sleep(0.5)
                
                if i % 10 == 0:
                    log(f"⏳ [{exchange_name}] Проверено {i}/{len(all_symbols)} монет...")
                    
            except Exception as e:
                logger.error(f"[{exchange_name}] Ошибка при проверке {symbol}: {e}")
                continue
        
        return len(all_symbols)
        
    except Exception as e:
        logger.error(f"[{exchange_name}] Ошибка при сканировании биржи: {e}")
        return 0


# ============================================================
# Главный цикл сканирования
# ============================================================
async def scan_loop():
    """Главный асинхронный цикл сканирования."""
    log("🚀 Запуск Crypto Scanner Bot...")
    
    try:
        # 1. Инициализация БД
        log("🗄️  Инициализация базы данных...")
        await database.init_db()
        log("✅ База данных инициализирована")
        
        # 2. Инициализация бирж (мульти-режим)
        exchanges_to_scan = getattr(config, 'EXCHANGES_TO_SCAN', [config.ACTIVE_EXCHANGE])
        exchanges = {}
        
        for exchange_name in exchanges_to_scan:
            try:
                log(f"📡 Инициализация биржи: {exchange_name}")
                exchange = analyzer.get_exchange(exchange_name)
                exchanges[exchange_name] = exchange
                log(f"✅ Биржа {exchange_name} инициализирована")
            except Exception as e:
                logger.error(f"❌ Не удалось инициализировать биржу {exchange_name}: {e}")
                log(f"❌ Не удалось инициализировать биржу {exchange_name}: {e}")
        
        if not exchanges:
            log("❌ Ни одна биржа не инициализирована. Завершение.")
            return
        
        log(f"📡 Активные биржи: {list(exchanges.keys())}")
        
        # 3. Создание Application для Telegram бота
        log("🤖 Создание Telegram Application...")
        application = Application.builder().token(config.BOT_TOKEN).build()
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", telegram_bot.start))
        application.add_handler(CommandHandler("cancel", telegram_bot.cancel))
        application.add_handler(CommandHandler("add_coin", telegram_bot.add_coin_command))
        application.add_handler(CommandHandler("remove_coin", telegram_bot.remove_coin_command))
        application.add_handler(CommandHandler("list_coins", telegram_bot.list_coins_command))
        application.add_handler(CommandHandler("status", telegram_bot.status_command))
        application.add_handler(CommandHandler("help", telegram_bot.help_command))
        
        # Обработчик кнопок меню
        application.add_handler(CallbackQueryHandler(telegram_bot.menu_callback, pattern='^menu_'))
        
        # Обработчик текстового ввода (для диалогов)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, telegram_bot.handle_text_input
        ))
        
        # 4. Запуск Telegram бота в фоне
        log("🚀 Запуск Telegram бота в фоновом режиме...")
        asyncio.create_task(run_telegram_bot_async(application))
        
        await asyncio.sleep(2)
        
        # 5. Загрузка приоритетных монет
        priority_coins = load_priority_coins()
        
        # 6. Главный цикл сканирования
        log("🔄 Запуск цикла сканирования...")
        log(f"📊 Топ монет: {config.TOP_COINS_COUNT} | Интервал: {config.SCAN_INTERVAL_SECONDS} сек")
        log(f"📡 Биржи для сканирования: {list(exchanges.keys())}")
        
        while True:
            try:
                log("🔍 Начало цикла сканирования...")
                
                tasks = []
                for exchange_name, exchange in exchanges.items():
                    task = scan_exchange(exchange, exchange_name, application, priority_coins)
                    tasks.append(task)
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                total_checked = 0
                for exchange_name, result in zip(exchanges.keys(), results):
                    if isinstance(result, Exception):
                        logger.error(f"[{exchange_name}] Ошибка: {result}")
                        log(f"❌ [{exchange_name}] Ошибка сканирования: {result}")
                    else:
                        total_checked += result
                        log(f"✅ [{exchange_name}] Проверено {result} монет")
                
                log(f"✅ Цикл сканирования завершён. Всего проверено: {total_checked} монет. "
                    f"Пауза {config.SCAN_INTERVAL_SECONDS} сек...")
                
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)
                
            except Exception as e:
                logger.error(f"Ошибка в цикле сканирования: {e}")
                log(f"❌ Ошибка в цикле сканирования: {e}")
                log("⏳ Пауза 10 секунд перед повторной попыткой...")
                await asyncio.sleep(10)
                
    except KeyboardInterrupt:
        log("🛑 Остановка бота по команде пользователя (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        log(f"❌ Критическая ошибка: {e}")
        raise


# ============================================================
# Точка входа
# ============================================================
if __name__ == "__main__":
    try:
        exchanges_to_scan = getattr(config, 'EXCHANGES_TO_SCAN', [config.ACTIVE_EXCHANGE])
        
        log("=" * 60)
        log("🚀 Crypto Scanner Bot")
        log("=" * 60)
        log(f"📡 Биржи: {', '.join(exchanges_to_scan)}")
        log(f"📊 Топ монет на биржу: {config.TOP_COINS_COUNT}")
        log(f"⏱️  Интервал сканирования: {config.SCAN_INTERVAL_SECONDS} сек")
        log(f"🚀 Порог пампа: >{config.PUMP_PRICE_CHANGE_PERCENT}% за {config.PUMP_TIMEFRAME_MINUTES} мин")
        log(f"📉 Порог дампа: >{config.DUMP_PRICE_CHANGE_PERCENT}% за {config.DUMP_TIMEFRAME_MINUTES} мин")
        log(f"⏸️  Кулдаун: {config.COOLDOWN_SECONDS} сек ({config.COOLDOWN_SECONDS // 60} мин)")
        log(f"🔄 Режим: мульти-сканирование ({len(exchanges_to_scan)} бирж)")
        log("=" * 60)
        
        asyncio.run(scan_loop())
        
    except KeyboardInterrupt:
        log("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        log(f"❌ Критическая ошибка: {e}")