# ============================================================
# analyzer.py — Анализ криптовалют (памп / дамп)
# Поддержка бирж: Binance, Bybit (через ccxt)
# ============================================================

import ccxt
import pandas as pd
import numpy as np
from config import (
    ACTIVE_EXCHANGE,
    BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_SANDBOX,
    BYBIT_API_KEY, BYBIT_SECRET_KEY, BYBIT_SANDBOX,
    PUMP_PRICE_CHANGE_PERCENT, PUMP_TIMEFRAME_MINUTES, PUMP_VOLUME_MULTIPLIER,
    DUMP_PRICE_CHANGE_PERCENT, DUMP_TIMEFRAME_MINUTES, DUMP_VOLUME_MULTIPLIER,
    TOP_COINS_COUNT, STOP_COINS,
)


# ============================================================
# 1. Создание объекта биржи
# ============================================================
def get_exchange(exchange_name: str = None):
    """
    Создаёт и возвращает объект биржи через ccxt.

    Parameters
    ----------
    exchange_name : str, optional
        'binance' или 'bybit'. Если None — берётся ACTIVE_EXCHANGE из config.

    Returns
    -------
    ccxt.Exchange
        Настроенный объект биржи.
    """
    if exchange_name is None:
        exchange_name = ACTIVE_EXCHANGE

    exchange_name = exchange_name.lower().strip()

    # Общие параметры для обеих бирж
    common_params = {
        'enableRateLimit': True,
        'timeout': 10000,          # Таймаут запроса — 10 секунд
        'options': {
            'defaultType': 'spot', # Работаем только со спотовым рынком
        },
    }

    if exchange_name == 'binance':
        # Подставляем API-ключи напрямую из config (импортированы через from config import *)
        if BINANCE_API_KEY:
            common_params['apiKey'] = BINANCE_API_KEY
        if BINANCE_SECRET_KEY:
            common_params['secret'] = BINANCE_SECRET_KEY

        exchange = ccxt.binance(common_params)

        # Тестовая среда
        if BINANCE_SANDBOX:
            exchange.set_sandbox_mode(True)

    elif exchange_name == 'bybit':
        if BYBIT_API_KEY:
            common_params['apiKey'] = BYBIT_API_KEY
        if BYBIT_SECRET_KEY:
            common_params['secret'] = BYBIT_SECRET_KEY

        exchange = ccxt.bybit(common_params)

        if BYBIT_SANDBOX:
            exchange.set_sandbox_mode(True)

    else:
        raise ValueError(f"Неподдерживаемая биржа: '{exchange_name}'. "
                         f"Доступные: 'binance', 'bybit'.")

    return exchange


# ============================================================
# 2. Получение топ-монет по объёму
# ============================================================
def get_top_symbols(exchange, limit: int = None, stop_coins: list = None) -> list:
    """
    Возвращает список символов, отсортированных по 24h объёму (убывание).

    Использует exchange.fetch_tickers() для получения актуальных данных
    об объёмах торгов (quoteVolume).

    Parameters
    ----------
    exchange : ccxt.Exchange
        Объект биржи.
    limit : int, optional
        Сколько монет вернуть. По умолчанию — TOP_COINS_COUNT из config.
    stop_coins : list, optional
        Пары, которые нужно исключить. По умолчанию — STOP_COINS из config.

    Returns
    -------
    list[str]
        Список символов, например ['BTC/USDT', 'ETH/USDT', ...].
    """
    if limit is None:
        limit = TOP_COINS_COUNT
    if stop_coins is None:
        stop_coins = STOP_COINS

    try:
        # Используем fetch_tickers() — именно там находится quoteVolume
        tickers = exchange.fetch_tickers()
    except ccxt.BaseError as e:
        print(f"[get_top_symbols] CCXT-ошибка при загрузке тикеров: {e}")
        return []
    except Exception as e:
        print(f"[get_top_symbols] Неожиданная ошибка при загрузке тикеров: {type(e).__name__}: {e}")
        return []

    # Фильтруем: только USDT-пары, исключаем стоп-лист
    filtered = []
    for symbol, ticker in tickers.items():
        # Только пары к USDT
        if not symbol.endswith('/USDT'):
            continue

        # Исключаем стоп-монеты
        if symbol in stop_coins:
            continue

        # quoteVolume — объём в котируемой валюте (USDT)
        # Bybit может возвращать 'quoteVolume' или 'volume' — проверяем оба
        quote_volume = ticker.get('quoteVolume')
        if quote_volume is None:
            quote_volume = ticker.get('volume', 0)

        if quote_volume is None or quote_volume <= 0:
            continue

        filtered.append((symbol, float(quote_volume)))

    # Сортируем по объёму (убывание)
    filtered.sort(key=lambda x: x[1], reverse=True)

    # Берём топ-N
    top_symbols = [item[0] for item in filtered[:limit]]
    return top_symbols


# ============================================================
# 3. Расчёт EMA (Exponential Moving Average)
# ============================================================
def calculate_ema(data, period: int = 20) -> float:
    """
    Рассчитывает EMA (экспоненциальную скользящую среднюю).

    Parameters
    ----------
    data : list | pd.Series
        Список цен.
    period : int
        Период EMA.

    Returns
    -------
    float
        Последнее значение EMA, округлённое до 2 знаков.
    """
    if data is None or len(data) < period:
        return 0.0

    series = pd.Series(data) if not isinstance(data, pd.Series) else data
    ema = series.ewm(span=period, adjust=False).mean()
    return round(float(ema.iloc[-1]), 2)


# ============================================================
# Вспомогательная: загрузка свечей OHLCV
# ============================================================
def _fetch_ohlcv(exchange, symbol: str, timeframe: str = '1m', limit: int = 25):
    """
    Загружает свечи OHLCV с обработкой ошибок.

    Returns
    -------
    pd.DataFrame | None
        DataFrame с колонками ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        или None в случае ошибки.
    """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

        if not ohlcv or len(ohlcv) < limit:
            # Для Bybit данные могут приходить с задержкой —
            # продолжаем, если хотя бы 10 свечей
            if ohlcv is None or len(ohlcv) < 10:
                print(f"[_fetch_ohlcv] {symbol}: недостаточно данных "
                      f"(получено {len(ohlcv) if ohlcv else 0} свечей, нужно {limit})")
                return None

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    except ccxt.NetworkError as e:
        print(f"[_fetch_ohlcv] Сетевая ошибка для {symbol}: {e}")
        return None
    except ccxt.ExchangeError as e:
        print(f"[_fetch_ohlcv] Ошибка биржи для {symbol}: {e}")
        return None
    except ccxt.BaseError as e:
        print(f"[_fetch_ohlcv] CCXT-ошибка для {symbol}: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        print(f"[_fetch_ohlcv] Неожиданная ошибка для {symbol}: {type(e).__name__}: {e}")
        return None


# ============================================================
# 4. Проверка на памп
# ============================================================
def check_pump(symbol: str, exchange) -> dict:
    """
    Проверяет монету на памп.

    Условия пампа:
      - Рост цены за PUMP_TIMEFRAME_MINUTES > PUMP_PRICE_CHANGE_PERCENT
      - Объём за последние 5 мин > среднего за предыдущие 20 мин × PUMP_VOLUME_MULTIPLIER
      - Цена выше EMA20 (бычий тренд)

    Parameters
    ----------
    symbol : str
        Торговая пара, например 'BTC/USDT'.
    exchange : ccxt.Exchange
        Объект биржи.

    Returns
    -------
    dict
        {
            'is_pump': bool,
            'price_change': float,   # % изменения цены
            'volume_ratio': float,   # отношение объёма к среднему
            'ema': float,            # EMA20
            'current_price': float,  # текущая цена закрытия
            'volume_5min': float     # суммарный объём за 5 мин
        }
    """
    # Дефолтный результат при ошибке
    default_result = {
        'is_pump': False,
        'price_change': 0.0,
        'volume_ratio': 0.0,
        'ema': 0.0,
        'current_price': 0.0,
        'volume_5min': 0.0,
    }

    timeframe_min = PUMP_TIMEFRAME_MINUTES  # 5
    df = _fetch_ohlcv(exchange, symbol, timeframe='1m', limit=25)

    if df is None:
        return default_result

    try:
        # Текущая цена (последняя свеча)
        current_price = float(df['close'].iloc[-1])

        # Цена N минут назад (индекс -6 = 5 свечей назад)
        if len(df) < timeframe_min + 1:
            print(f"[check_pump] {symbol}: недостаточно свечей "
                  f"(нужно {timeframe_min + 1}, получено {len(df)})")
            return default_result

        price_n_ago = float(df['close'].iloc[-(timeframe_min + 1)])

        # Изменение цены в %
        if price_n_ago == 0:
            print(f"[check_pump] {symbol}: цена 5 мин назад = 0, деление на ноль")
            return default_result
        price_change = round((current_price - price_n_ago) / price_n_ago * 100, 2)

        # Объём за последние 5 минут (сумма)
        volume_5min = round(float(df['volume'].iloc[-timeframe_min:].sum()), 2)

        # Средний объём за предыдущие 20 минут (свечи с -25 по -5, исключая последние 5)
        # iloc[-25:-5] берёт элементы с индекса -25 до -5 (не включая -5)
        avg_volume = float(df['volume'].iloc[-25:-5].mean())

        # Отношение объёма к среднему
        volume_ratio = round(volume_5min / avg_volume, 2) if avg_volume > 0 else 0.0

        # EMA20 по ценам закрытия
        ema = calculate_ema(df['close'].tolist(), period=20)

        # Проверка условий пампа
        is_pump = (
            price_change > PUMP_PRICE_CHANGE_PERCENT
            and volume_ratio > PUMP_VOLUME_MULTIPLIER
            and current_price > ema  # Цена выше EMA — бычий тренд
        )

        return {
            'is_pump': is_pump,
            'price_change': price_change,
            'volume_ratio': volume_ratio,
            'ema': ema,
            'current_price': round(current_price, 2),
            'volume_5min': volume_5min,
        }

    except ZeroDivisionError as e:
        print(f"[check_pump] {symbol}: деление на ноль — {e}")
        return default_result
    except IndexError as e:
        print(f"[check_pump] {symbol}: ошибка индекса (недостаточно данных) — {e}")
        return default_result
    except Exception as e:
        print(f"[check_pump] {symbol}: неожиданная ошибка — {type(e).__name__}: {e}")
        return default_result


# ============================================================
# 5. Проверка на дамп
# ============================================================
def check_dump(symbol: str, exchange) -> dict:
    """
    Проверяет монету на дамп.

    Условия дампа:
      - Падение цены за DUMP_TIMEFRAME_MINUTES > DUMP_PRICE_CHANGE_PERCENT
      - Объём за последние 5 мин > среднего за предыдущие 20 мин × DUMP_VOLUME_MULTIPLIER
      - Цена ниже EMA20 (медвежий тренд)
      + Дивергенция: сравнивает направление изменения цены и объёма

    Parameters
    ----------
    symbol : str
        Торговая пара, например 'BTC/USDT'.
    exchange : ccxt.Exchange
        Объект биржи.

    Returns
    -------
    dict
        {
            'is_dump': bool,
            'price_change': float,
            'volume_ratio': float,
            'ema': float,
            'current_price': float,
            'volume_5min': float,
            'has_divergence': bool
        }
    """
    default_result = {
        'is_dump': False,
        'price_change': 0.0,
        'volume_ratio': 0.0,
        'ema': 0.0,
        'current_price': 0.0,
        'volume_5min': 0.0,
        'has_divergence': False,
    }

    timeframe_min = DUMP_TIMEFRAME_MINUTES  # 5
    df = _fetch_ohlcv(exchange, symbol, timeframe='1m', limit=25)

    if df is None:
        return default_result

    try:
        # Текущая цена
        current_price = float(df['close'].iloc[-1])

        # Цена N минут назад
        if len(df) < timeframe_min + 1:
            print(f"[check_dump] {symbol}: недостаточно свечей "
                  f"(нужно {timeframe_min + 1}, получено {len(df)})")
            return default_result

        price_n_ago = float(df['close'].iloc[-(timeframe_min + 1)])

        # Изменение цены в %
        if price_n_ago == 0:
            print(f"[check_dump] {symbol}: цена 5 мин назад = 0, деление на ноль")
            return default_result
        price_change = round((current_price - price_n_ago) / price_n_ago * 100, 2)

        # Объём за последние 5 минут
        volume_5min = round(float(df['volume'].iloc[-timeframe_min:].sum()), 2)

        # Средний объём за предыдущие 20 минут (свечи с -25 по -5)
        avg_volume = float(df['volume'].iloc[-25:-5].mean())

        volume_ratio = round(volume_5min / avg_volume, 2) if avg_volume > 0 else 0.0

        # EMA20
        ema = calculate_ema(df['close'].tolist(), period=20)

        # --- Дивергенция ---
        # Сравниваем направление изменения цены и объёма:
        # если цена падает, а объём растёт — это медвежья дивергенция
        # (подтверждение дампа)
        price_direction = np.sign(price_change)          # -1 если падает, +1 если растёт
        volume_direction = np.sign(volume_ratio - 1.0)   # +1 если объём выше среднего

        # Дивергенция: цена падает (отриц.), объём растёт (положит.)
        has_divergence = bool(price_direction < 0 and volume_direction > 0)

        # Проверка условий дампа
        is_dump = (
            price_change < -DUMP_PRICE_CHANGE_PERCENT    # падение > порога (отрицательное)
            and volume_ratio > DUMP_VOLUME_MULTIPLIER    # объём выше порога
            and current_price < ema                      # цена ниже EMA20 (медвежий тренд)
        )

        return {
            'is_dump': is_dump,
            'price_change': price_change,
            'volume_ratio': volume_ratio,
            'ema': ema,
            'current_price': round(current_price, 2),
            'volume_5min': volume_5min,
            'has_divergence': has_divergence,
        }

    except ZeroDivisionError as e:
        print(f"[check_dump] {symbol}: деление на ноль — {e}")
        return default_result
    except IndexError as e:
        print(f"[check_dump] {symbol}: ошибка индекса (недостаточно данных) — {e}")
        return default_result
    except Exception as e:
        print(f"[check_dump] {symbol}: неожиданная ошибка — {type(e).__name__}: {e}")
        return default_result