import os

# --- Telegram ---
# Токен бота (берётся из переменных окружения)
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Chat ID для отправки уведомлений (берётся из переменных окружения)
CHAT_ID = os.getenv('CHAT_ID', '')

# --- Выбор биржи ---
ACTIVE_EXCHANGE = 'binance'

# --- Мульти-сканирование ---
EXCHANGES_TO_SCAN = ['binance', 'bybit']

# --- Binance ---
BINANCE_API_KEY = ''
BINANCE_SECRET_KEY = ''
BINANCE_SANDBOX = False

# --- Bybit ---
BYBIT_API_KEY = ''
BYBIT_SECRET_KEY = ''
BYBIT_SANDBOX = False

# --- Пороги пампа ---
PUMP_PRICE_CHANGE_PERCENT = 8
PUMP_TIMEFRAME_MINUTES = 5
PUMP_VOLUME_MULTIPLIER = 5

# --- Пороги дампа ---
DUMP_PRICE_CHANGE_PERCENT = 5
DUMP_TIMEFRAME_MINUTES = 5
DUMP_VOLUME_MULTIPLIER = 4

# --- Кулдаун ---
COOLDOWN_SECONDS = 1800

# --- Параметры сканирования ---
TOP_COINS_COUNT = 50
SCAN_INTERVAL_SECONDS = 60

# --- Стоп-лист монет ---
STOP_COINS = ['USDC/USDT', 'BUSD/USDT', 'FDUSD/USDT']