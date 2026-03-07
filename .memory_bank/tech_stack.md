# R2D2 Tech Stack

## Backend

| Технология | Версия | Роль |
|---|---|---|
| Python | 3.10+ | Основной язык |
| FastAPI | 0.104.1 | Web framework, REST API |
| uvicorn | 0.24.0 | ASGI сервер |
| Redis | 5.0.1 (py) | Хранение состояния, очереди, результаты |
| ClickHouse | clickhouse-connect 0.6+ | Хранение котировок |
| numpy | 1.24+ | Массивы данных (OHLCV, индикаторы) |
| ccxt | 4.0+ | Подключение к биржам |
| TA-Lib | 0.6.8+ | Технические индикаторы |
| pyita | 1.0.12+ | Расширенный набор индикаторов |
| msgpack | 1.0+ | Бинарная сериализация |
| psutil | 5.9+ | Мониторинг процессов |
| httpx | <0.28.0 | HTTP клиент |
| debugpy | 1.8+ | Отладка |

## Frontend

| Технология | Версия | Роль |
|---|---|---|
| Vue.js | 3.3+ | UI framework |
| Vite | 5.0+ | Сборщик |
| Vue Router | 4.2+ | Маршрутизация |
| Axios | 1.13+ | HTTP запросы |
| lightweight-charts | 5.1+ | Торговые графики (TradingView) |
| CodeMirror | 6.x | Редактор Python кода |
| @msgpack/msgpack | 3.0+ | Бинарная десериализация данных |
| @heroicons/vue | 2.2+ | Иконки |

## Инфраструктура

| Сервис | Порт | Назначение |
|---|---|---|
| Backend API | 8202 | FastAPI |
| Frontend Dev | 3000 | Vite dev server |
| Redis | 6379 | Хранилище состояния |
| ClickHouse | 8123 | База котировок |

## Типы данных (backend)

```python
PRICE_TYPE = float    # Цены
VOLUME_TYPE = float   # Объёмы
TIME_TYPE = np.datetime64  # Время (dtype: datetime64[ms])
```

## Ключевые паттерны

### Objects2Redis
Базовый класс для хранения Pydantic-моделей в Redis:
- `Objects2Redis` — одиночный объект
- `Objects2RedisList[T]` — список объектов с CRUD операциями

### ABC классы
- `Broker` (ABC) → `BrokerBacktesting` (бэктестинг), `BrokerTrading` (live)
- `Strategy` (ABC) → пользовательские стратегии
- `QuotesProvider` (ABC) → `BacktestingQuotesProvider`
- `ta_proxy` (ABC) → `ta_proxy_talib`, `ta_proxy_pyita`

### Индикаторы
- Доступны через `self.talib` (TA-Lib) и `self.ta` (pyita) в стратегии
- Кэшируются по параметрам вызова
- Поддерживают `timeframe` и `symbol` параметры для кросс-таймфрейм расчётов
- Параметры визуализации (`lines`, `visible`) применяются только при первом вызове

## Тестирование

- pytest с конфигурацией в `backend/pytest.ini`
- Тесты в `backend/tests/`
- Группы тестов: A-J (по сценариям из `test_strategy_plan.md`)
- `conftest.py` — общие фикстуры
