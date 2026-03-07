# R2D2 Conventions

## Язык

- **Комментарии в коде** — только на английском
- **Общение с пользователем** — на русском языке
- **Очевидные комментарии** — не добавлять
- **В начале каждого ответа** — указывать используемую модель AI и сообщать об использовании правил проекта

## Структура стратегии

```python
from app.services.tasks.strategy import Strategy
import numpy as np
from typing import Dict, Tuple, Any

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__()

    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        return {
            'period': (20, 'Indicator period'),
        }

    def on_start(self):
        self.period = self.parameters['period']

    def on_bar(self):
        if len(self.close) < self.period:
            return
        sma = self.talib.SMA(value='close', timeperiod=self.period)
        if np.isnan(sma[-1]):
            return
        # strategy logic here

    def on_finish(self):
        pass
```

## Соглашения по коду

### Именование
- Классы: `PascalCase`
- Функции и методы: `snake_case`
- Константы: `UPPER_SNAKE_CASE`
- Приватные методы: `_leading_underscore`

### Модели данных
- Pydantic BaseModel для всех моделей данных (Order, Deal, Trade, Task)
- ABC для абстрактных классов (Broker, Strategy, QuotesProvider, ta_proxy)

### Типизация
- Использовать type hints везде
- Специальные типы: `PRICE_TYPE`, `VOLUME_TYPE` из `broker.py`
- `Optional[X]` вместо `X | None` для совместимости

### Индикаторы в стратегии
- `self.talib.INDICATOR(value='close', timeperiod=N)` — TA-Lib
- `self.ta.indicator(period=N, value='close')` — pyita
- Всегда проверять `np.isnan()` перед использованием
- Параметры визуализации задаются только при первом вызове

### Ордера
- Всегда проверять `result.error` после размещения ордера
- Использовать `self.format_volume()` / `self.format_price()` при необходимости
- Торговые методы округляют автоматически, дополнительное округление опционально

## Паттерны проекта

### Objects2Redis
```python
class MyList(Objects2RedisList[MyModel]):
    def list_key(self) -> str:
        return "my:list"
    def object_class(self) -> Type[MyModel]:
        return MyModel
```

### API эндпоинты
- Все в `backend/app/api/v1/`
- Роутеры подключаются в `main.py`
- Использовать `async def` для эндпоинтов

### Конфигурация
- Все настройки читаются из `backend/app/core/config.py`
- ENV переменные из `~/.config/r2d2/.env`

## Тестирование

### Группы тестов (по test_strategy_plan.md)
- **A** — базовое размещение ордеров
- **B** — простые случаи исполнения
- **C** — сложные: входы + стопы одновременно
- **D** — сложные: входы + тейки одновременно
- **E** — наисложнейшие: входы + стопы + тейки одновременно
- **F** — валидация и ошибки
- **G** — граничные случаи
- **H** — перемежающиеся входы и выходы
- **I** — тесты modify_deal
- **J** — дополнительные сценарии

### Принципы тестов стратегий
- Тесты создают искусственные бары с заданными OHLCV
- Между триггерными барами можно вставлять "нейтральные" бары
- Проверяется: OrderOperationResult, статусы ордеров, объёмы, цены, трейды, сделки
