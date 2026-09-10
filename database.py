# ============================================================
# database.py — Асинхронное хранилище сигналов и кулдаунов
# Использует aiosqlite для работы с SQLite
# ============================================================

import aiosqlite
import time

# Путь к файлу базы данных
DB_PATH = 'signals.db'


# ============================================================
# 1. Инициализация базы данных
# ============================================================
async def init_db():
    """
    Создаёт таблицы signals и cooldown, если их ещё нет.
    
    Таблица signals:
        - id: INTEGER PRIMARY KEY (автоинкремент)
        - symbol: TEXT (торговая пара, например 'BTC/USDT')
        - signal_type: TEXT ('pump' или 'dump')
        - price: REAL (текущая цена)
        - volume: REAL (объём за 5 минут)
        - price_change: REAL (изменение цены в %)
        - timestamp: INTEGER (UNIX timestamp)
    
    Таблица cooldown:
        - symbol: TEXT PRIMARY KEY (торговая пара)
        - last_alert_time: INTEGER (UNIX timestamp последнего сигнала)
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Таблица для хранения истории сигналов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL NOT NULL,
                    price_change REAL NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            
            # Таблица для отслеживания кулдаунов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS cooldown (
                    symbol TEXT PRIMARY KEY,
                    last_alert_time INTEGER NOT NULL
                )
            ''')
            
            await db.commit()
            print("[init_db] База данных инициализирована успешно")
            
    except aiosqlite.Error as e:
        print(f"[init_db] Ошибка SQLite: {e}")
        raise
    except Exception as e:
        print(f"[init_db] Неожиданная ошибка: {type(e).__name__}: {e}")
        raise


# ============================================================
# 2. Сохранение сигнала
# ============================================================
async def save_signal(symbol: str, signal_type: str, price: float, volume: float, price_change: float):
    """
    Сохраняет новый сигнал в таблицу signals.
    
    Parameters
    ----------
    symbol : str
        Торговая пара (например, 'BTC/USDT').
    signal_type : str
        Тип сигнала: 'pump' или 'dump'.
    price : float
        Текущая цена.
    volume : float
        Объём за последние 5 минут.
    price_change : float
        Изменение цены в процентах.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            timestamp = int(time.time())
            await db.execute('''
                INSERT INTO signals (symbol, signal_type, price, volume, price_change, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (symbol, signal_type, price, volume, price_change, timestamp))
            await db.commit()
            print(f"[save_signal] Сигнал сохранён: {symbol} ({signal_type})")
            
    except aiosqlite.Error as e:
        print(f"[save_signal] Ошибка SQLite при сохранении {symbol}: {e}")
    except Exception as e:
        print(f"[save_signal] Неожиданная ошибка при сохранении {symbol}: {type(e).__name__}: {e}")


# ============================================================
# 3. Получение времени последнего сигнала
# ============================================================
async def get_last_alert(symbol: str) -> int | None:
    """
    Возвращает UNIX timestamp последнего сигнала для указанной монеты.
    
    Parameters
    ----------
    symbol : str
        Торговая пара.
    
    Returns
    -------
    int | None
        UNIX timestamp последнего сигнала или None, если сигнала не было.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Убеждаемся, что таблица существует
            await db.execute('''
                CREATE TABLE IF NOT EXISTS cooldown (
                    symbol TEXT PRIMARY KEY,
                    last_alert_time INTEGER NOT NULL
                )
            ''')
            await db.commit()
            
            async with db.execute('''
                SELECT last_alert_time FROM cooldown WHERE symbol = ?
            ''', (symbol,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]
                return None
                
    except aiosqlite.Error as e:
        print(f"[get_last_alert] Ошибка SQLite для {symbol}: {e}")
        return None
    except Exception as e:
        print(f"[get_last_alert] Неожиданная ошибка для {symbol}: {type(e).__name__}: {e}")
        return None


# ============================================================
# 4. Обновление кулдауна
# ============================================================
async def update_cooldown(symbol: str):
    """
    Обновляет время последнего сигнала для монеты (INSERT OR REPLACE).
    Используется для реализации кулдауна.
    
    Parameters
    ----------
    symbol : str
        Торговая пара.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            timestamp = int(time.time())
            await db.execute('''
                INSERT OR REPLACE INTO cooldown (symbol, last_alert_time)
                VALUES (?, ?)
            ''', (symbol, timestamp))
            await db.commit()
            print(f"[update_cooldown] Кулдаун обновлён для {symbol}")
            
    except aiosqlite.Error as e:
        print(f"[update_cooldown] Ошибка SQLite для {symbol}: {e}")
    except Exception as e:
        print(f"[update_cooldown] Неожиданная ошибка для {symbol}: {type(e).__name__}: {e}")


# ============================================================
# 5. Статистика сигналов
# ============================================================
async def get_stats() -> dict:
    """
    Возвращает статистику сигналов за последние 24 часа.
    
    Returns
    -------
    dict
        {
            'total': int,   # Всего сигналов за 24 часа
            'pumps': int,   # Количество пампов
            'dumps': int    # Количество дампов
        }
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Убеждаемся, что таблицы существуют
            await db.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL NOT NULL,
                    price_change REAL NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS cooldown (
                    symbol TEXT PRIMARY KEY,
                    last_alert_time INTEGER NOT NULL
                )
            ''')
            await db.commit()
            
            # Время 24 часа назад
            time_24h_ago = int(time.time()) - (24 * 60 * 60)
            
            # Общее количество сигналов за 24 часа
            async with db.execute('''
                SELECT COUNT(*) FROM signals WHERE timestamp > ?
            ''', (time_24h_ago,)) as cursor:
                total_row = await cursor.fetchone()
                total = total_row[0] if total_row else 0
            
            # Количество пампов за 24 часа
            async with db.execute('''
                SELECT COUNT(*) FROM signals 
                WHERE timestamp > ? AND signal_type = 'pump'
            ''', (time_24h_ago,)) as cursor:
                pumps_row = await cursor.fetchone()
                pumps = pumps_row[0] if pumps_row else 0
            
            # Количество дампов за 24 часа
            async with db.execute('''
                SELECT COUNT(*) FROM signals 
                WHERE timestamp > ? AND signal_type = 'dump'
            ''', (time_24h_ago,)) as cursor:
                dumps_row = await cursor.fetchone()
                dumps = dumps_row[0] if dumps_row else 0
            
            return {
                'total': total,
                'pumps': pumps,
                'dumps': dumps
            }
            
    except aiosqlite.Error as e:
        print(f"[get_stats] Ошибка SQLite: {e}")
        return {'total': 0, 'pumps': 0, 'dumps': 0}
    except Exception as e:
        print(f"[get_stats] Неожиданная ошибка: {type(e).__name__}: {e}")
        return {'total': 0, 'pumps': 0, 'dumps': 0}
async def get_recent_signals(limit=10):
    """
    Возвращает последние N сигналов из базы.
    Каждая запись — кортеж: (symbol, signal_type, price, price_change, timestamp)
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'SELECT symbol, signal_type, price, price_change, timestamp '
                'FROM signals ORDER BY timestamp DESC LIMIT ?',
                (limit,)
            )
            rows = await cursor.fetchall()
            return rows
    except Exception as e:
        print(f"Ошибка при получении последних сигналов: {e}")
        return []