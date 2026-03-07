# R2D2 Architecture

## Общая схема

```
Frontend (Vue.js :3000)
        |
        | HTTP REST + WebSocket
        v
Backend (FastAPI :8202)
        |
    +---+---+
    |       |
  Redis   ClickHouse
(state)  (quotes)
```

## Backend

### Точка входа
- `backend/app/main.py` — FastAPI приложение, порт 8202
- Запуск: `uvicorn app.main:app --reload --host 0.0.0.0 --port 8202`
- Скрипт запуска: `start.sh`

### API (backend/app/api/v1/)
- `strategy_endpoints.py` — управление файлами стратегий (list, load, save, new)
- `backtesting_endpoints.py` — задачи бэктестинга (CRUD, запуск/остановка, результаты, WebSocket)
- `trading_endpoints.py` — задачи live-торговли (list, delete, clone from backtesting)
- `common.py` — общие эндпоинты (таймфреймы, биржи, символы, котировки)

### Core (backend/app/core/)
- `config.py` — конфигурация из `~/.config/r2d2/.env`
- `objects2redis.py` — базовые классы для хранения объектов в Redis (Objects2Redis, Objects2RedisList)
- `logger.py` — настройка логирования
- `startup.py` — инициализация при старте (Redis, QuoteService)
- `exceptions.py` — базовые исключения

### Services

#### Quotes (backend/app/services/quotes/)
- Клиент-серверная архитектура через Redis
- `server.py` — сервер котировок (загрузка из ClickHouse, кэширование)
- `client.py` — клиент для запроса котировок
- `timeframe.py` — класс Timeframe для работы с таймфреймами

#### Tasks (backend/app/services/tasks/)
- `broker.py` — абстрактный класс `Broker` + модели `Trade`, `Order`, `Deal`
- `broker_backtesting.py` — `BrokerBacktesting` — реализация брокера для бэктестинга
- `strategy.py` — абстрактный класс `Strategy` + `OrderOperationResult`
- `indicator_proxy.py` — прокси для TA-Lib (`ta_proxy_talib`) и pyita (`ta_proxy_pyita`), `QuotesProxy`
- `quotes_provider.py` — `QuotesProvider` (ABC) + `BacktestingQuotesProvider`
- `tasks.py` — модели `Task`, `BacktestingTaskList`, `TradingTaskList`
- `task_results.py` — `TaskResults` — сохранение/загрузка результатов бэктестинга в Redis
- `trading_stats.py` — `TradingStats` — статистика торговли
- `enums.py` — перечисления: `OrderSide`, `OrderType`, `OrderStatus`, `OrderGroup`, `DealType`, `BarStatus`

#### Strategies (backend/app/services/strategies/)
- `strategy_template.py` — шаблон новой стратегии

## Frontend

### Технологии
- Vue.js 3 + Vite (порт 3000)
- Vue Router для навигации
- Axios для HTTP запросов
- lightweight-charts для торговых графиков
- CodeMirror 6 для редактора Python кода
- msgpack для бинарной сериализации данных

### Структура (frontend/src/)
- `views/` — страницы: `BacktestingView.vue`, `TradingView.vue`
- `components/` — компоненты UI
- `composables/` — Vue composables (useBacktesting, useBacktestingResults, useAlert, useTimeframes, useInitialData)
- `services/` — API клиенты (backtestingApi, strategiesApi, tradingApi)
- `router/` — маршрутизация

## Хранилище

### Redis
- Состояние задач (Task объекты)
- Очереди сообщений (WebSocket)
- Результаты бэктестинга (котировки, индикаторы, сделки, ордера, трейды, статистика)
- Запросы/ответы сервиса котировок

### ClickHouse
- База данных `quotes`
- Хранение исторических OHLCV данных

## Конфигурация и пути

- Конфиг: `~/.config/r2d2/.env`
- Данные: `~/.local/share/r2d2/`
  - Стратегии: `~/.local/share/r2d2/strategies/`
  - Состояние: `~/.local/share/r2d2/state/`
- Логи: `~/.local/state/r2d2/`

## Жизненный цикл бэктестинга

1. Пользователь создаёт задачу через API
2. `start_backtesting` запускает воркер в отдельном процессе
3. Воркер создаёт `BrokerBacktesting` + загружает стратегию
4. Брокер загружает котировки через `BacktestingQuotesProvider`
5. На каждом баре вызывается `strategy.on_bar()`
6. Результаты сохраняются в Redis через `TaskResults`
7. Frontend получает обновления через WebSocket
