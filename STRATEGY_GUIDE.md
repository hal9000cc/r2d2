# Strategy Development Guide

This guide describes the API for developing trading strategies in the backtesting system.

## Table of Contents

1. [Strategy Structure](#strategy-structure)
2. [Strategy Events](#strategy-events)
3. [Access to Quotes](#access-to-quotes)
4. [Access to Indicators](#access-to-indicators)
5. [Strategy Parameters](#strategy-parameters)
6. [Position Tracking](#position-tracking)
7. [Precision and Rounding](#precision-and-rounding)
8. [Order Placement](#order-placement)
9. [Order Management](#order-management)
10. [Logging](#logging)

---

## Strategy Structure

Each strategy must inherit from the `Strategy` class and implement the `on_bar()` method:

```python
from app.services.tasks.strategy import Strategy

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__()
        # Initialize strategy variables
    
    def on_bar(self):
        # Strategy logic on each bar
        pass
```

---

## Strategy Events

The strategy has three main events that are called during backtesting:

### `on_start()`

Called once before the backtesting loop starts. Used to initialize strategy-specific variables.

```python
def on_start(self):
    # Initialize variables
    self.position = None
    self.ma_fast_period = self.parameters['ma_fast']
    self.ma_slow_period = self.parameters['ma_slow']
```

**Important:** At the time `on_start()` is called, the following are already available:
- `self.parameters` - strategy parameters
- `self.talib` - object for working with indicators

### `on_bar()`

Called on each new bar of data. This is the main method where strategy logic is implemented.

```python
def on_bar(self):
    # Get current price
    current_price = self.close[-1]
    
    # Calculate indicators
    ma_fast = self.talib.SMA(value='close', timeperiod=20)
    ma_slow = self.talib.SMA(value='close', timeperiod=50)
    
    # Strategy logic
    if ma_fast[-1] > ma_slow[-1]:
        self.buy(quantity=0.1)
```

**Important:** At the time `on_bar()` is called, the following are available:
- All quote arrays (`self.close`, `self.open`, `self.high`, `self.low`, `self.volume`)
- Current position (`self.equity_symbol`, `self.equity_usd`)
- Indicators via `self.talib`

### `on_finish()`

Called once after the backtesting loop completes. Used for final calculations and cleanup.

```python
def on_finish(self):
    # Final calculations
    # Calculate total capital in USD
    if len(self.close) > 0:
        current_price = self.close[-1]
        total_capital = self.equity_usd + self.equity_symbol * current_price
        self.logging(f"Total capital: {total_capital} USD")
```

---

## Access to Quotes

The strategy has access to quote arrays through the following attributes:

- `self.time` - time array (numpy array, dtype: datetime64[ms])
- `self.open` - open price array (numpy array, dtype: PRICE_TYPE)
- `self.high` - high price array (numpy array, dtype: PRICE_TYPE)
- `self.low` - low price array (numpy array, dtype: PRICE_TYPE)
- `self.close` - close price array (numpy array, dtype: PRICE_TYPE)
- `self.volume` - volume array (numpy array, dtype: VOLUME_TYPE)

### Array Features

1. **Arrays contain historical data** - on each bar, arrays contain all data from the beginning to the current bar inclusive.

2. **Indexing** - the last element of the array (`[-1]`) corresponds to the current bar:
   ```python
   current_price = self.close[-1]  # Close price of current bar
   previous_price = self.close[-2]  # Close price of previous bar
   ```

3. **Array length** - array length increases with each bar:
   ```python
   if len(self.close) < 20:
       return  # Not enough data for indicator calculation
   ```

4. **All arrays have the same length** - `len(self.close) == len(self.open) == len(self.high) == ...`

### Usage Examples

```python
def on_bar(self):
    # Get current close price
    current_price = self.close[-1]
    
    # Get open price of current bar
    open_price = self.open[-1]
    
    # Get high and low of current bar
    high_price = self.high[-1]
    low_price = self.low[-1]
    
    # Get volume of current bar
    volume = self.volume[-1]
    
    # Get last 10 close prices
    last_10_closes = self.close[-10:]
    
    # Check if enough data
    if len(self.close) < 50:
        return  # Not enough data
```

---

## Access to Indicators

Access to technical indicators is through the `self.talib` object. This is a proxy for the TA-Lib library.

### Using Indicators

Indicators are called as methods of the `self.talib` object:

```python
# Simple moving average
sma = self.talib.SMA(value='close', timeperiod=20)

# Exponential moving average
ema = self.talib.EMA(value='close', timeperiod=12)

# RSI
rsi = self.talib.RSI(value='close', timeperiod=14)

# MACD (returns tuple of 3 arrays)
macd, signal, histogram = self.talib.MACD(value='close', fastperiod=12, slowperiod=26, signalperiod=9)
```

### Indicator Parameters

- `value` - name of data array: `'close'`, `'open'`, `'high'`, `'low'`, `'volume'`
- `timeperiod` - indicator period (for most indicators)
- Other parameters depend on the specific indicator (see TA-Lib documentation)

### Return Values

- **Single indicator** returns a numpy array of the same length as input data
- **Multiple indicator** (e.g., MACD) returns a tuple of arrays

### Features

1. **Indicators return data only up to current bar** - indicator array has length `self.broker.i_time + 1`

2. **Caching** - indicators are cached, repeated calls with the same parameters return cached values

3. **NaN values** - at the beginning of the indicator array there may be NaN values until enough data is available:
   ```python
   sma = self.talib.SMA(value='close', timeperiod=20)
   # First 19 elements may be NaN
   if not np.isnan(sma[-1]):
       # Use indicator value
       pass
   ```

### Usage Examples

```python
def on_bar(self):
    # Check if enough data
    if len(self.close) < 50:
        return
    
    # Calculate indicators
    sma_fast = self.talib.SMA(value='close', timeperiod=20)
    sma_slow = self.talib.SMA(value='close', timeperiod=50)
    
    # Check if indicators are calculated
    if np.isnan(sma_fast[-1]) or np.isnan(sma_slow[-1]):
        return
    
    # Strategy logic
    if sma_fast[-1] > sma_slow[-1]:
        self.buy(quantity=0.1)
```

---

## Strategy Parameters

A strategy can have parameters that are configured by the user before starting backtesting.

### Defining Parameters

Parameters are defined through the static method `get_parameters_description()`:

```python
@staticmethod
def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
    """
    Returns strategy parameters description.
    
    Returns:
        Dictionary where keys are parameter names (str),
        values are tuples (default_value, description).
        Parameter type is determined automatically from default value.
    """
    return {
        'ma_fast': (20, 'Fast moving average period'),
        'ma_slow': (50, 'Slow moving average period'),
        'stop_loss_percent': (2.0, 'Stop loss percentage'),
        'take_profit_percent': (5.0, 'Take profit percentage')
    }
```

### Accessing Parameters

Parameters are available through `self.parameters` (dictionary) after `on_start()` is called:

```python
def on_start(self):
    # Parameters are already loaded in self.parameters
    self.ma_fast_period = self.parameters['ma_fast']
    self.ma_slow_period = self.parameters['ma_slow']
    self.stop_loss = self.parameters['stop_loss_percent']
    self.take_profit = self.parameters['take_profit_percent']

def on_bar(self):
    # Use parameters
    sma_fast = self.talib.SMA(value='close', timeperiod=self.ma_fast_period)
    sma_slow = self.talib.SMA(value='close', timeperiod=self.ma_slow_period)
```

### Parameter Types

Parameter type is determined automatically from the default value:
- `int` - integer
- `float` - floating point number
- `str` - string
- `bool` - boolean value
- `list` - list
- `dict` - dictionary

### Examples

```python
@staticmethod
def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
    return {
        # Numeric parameters
        'period': (20, 'Indicator period'),
        'threshold': (0.5, 'Threshold value'),
        
        # String parameters
        'symbol': ('BTC/USDT', 'Trading symbol'),
        
        # Boolean parameters
        'use_stop_loss': (True, 'Use stop loss'),
        
        # Lists
        'levels': ([100, 200, 300], 'Support/resistance levels'),
    }
```

---

## Position Tracking

The strategy has access to the current position through two attributes:

- `self.equity_symbol` - coin volume in position (VOLUME_TYPE)
- `self.equity_usd` - account balance in USD (PRICE_TYPE)

### Features

1. **Updated on each bar** - values are updated after each bar taking into account all executed orders

2. **Values can be negative**:
   - `equity_symbol > 0` - long position (bought more than sold)
   - `equity_symbol < 0` - short position (sold more than bought)
   - `equity_symbol == 0` - no position

3. **equity_usd** - this is the account balance in USD. When buying coins, `equity_usd` decreases and `equity_symbol` increases. When selling - vice versa. Accounts for fees and slippage.

4. **Total capital in USD** - to get the total capital amount in USD, you need to add the account balance and position value:
   ```python
   total_capital_usd = self.equity_usd + self.equity_symbol * current_price
   ```
   where `current_price` is the current price (e.g., `self.close[-1]`)

### Usage Examples

```python
def on_bar(self):
    # Check if there is a position
    if self.equity_symbol > 0:
        # Long position
        self.logging(f"Long position: {self.equity_symbol}")
    elif self.equity_symbol < 0:
        # Short position
        self.logging(f"Short position: {abs(self.equity_symbol)}")
    else:
        # No position
        pass
    
    # Use for risk management
    if abs(self.equity_symbol) > 10.0:
        # Position too large, close part
        if self.equity_symbol > 0:
            self.sell(quantity=self.equity_symbol * 0.5)
        else:
            self.buy(quantity=abs(self.equity_symbol) * 0.5)
    
    # Calculate total capital in USD
    current_price = self.close[-1]
    total_capital = self.equity_usd + self.equity_symbol * current_price
    self.logging(f"Total capital: {total_capital} USD")
```

---

## Precision and Rounding

The strategy has access to precision values for amount and price, which are used to ensure all trading values conform to exchange requirements.

### Precision Attributes

- `self.precision_amount` - minimum step size for amount/base currency (e.g., 0.1, 0.001)
- `self.precision_price` - minimum step size for price/quote currency (e.g., 0.1, 0.001)

These values are automatically set from the broker after the broker is assigned. They are available in all strategy methods.

### Rounding Methods

The strategy provides two methods for rounding values to precision:

#### `round_to_precision(value: float, precision: float) -> float`

Rounds value to the nearest multiple of precision.

```python
# Round price to nearest precision
price = 100.123
rounded_price = self.round_to_precision(price, self.precision_price)
# If precision_price = 0.01, result is 100.12
```

#### `floor_to_precision(value: float, precision: float) -> float`

Rounds value down to the nearest multiple of precision.

```python
# Round volume down to precision
volume = 1.234
rounded_volume = self.floor_to_precision(volume, self.precision_amount)
# If precision_amount = 0.01, result is 1.23
```

### Automatic Rounding

All trading methods (`buy()`, `sell()`, `buy_sltp()`, `sell_sltp()`) automatically apply precision rounding:

- **Volume (quantity)** - rounded down using `floor_to_precision()` with `precision_amount`
- **Price** - rounded to nearest using `round_to_precision()` with `precision_price`
- **Trigger price** - rounded to nearest using `round_to_precision()` with `precision_price`

If a value is changed due to rounding, a warning is logged.

### Usage Examples

```python
def on_bar(self):
    # Calculate desired volume
    desired_volume = 1.2345
    
    # Round down manually if needed
    volume = self.floor_to_precision(desired_volume, self.precision_amount)
    
    # Calculate desired price
    desired_price = 100.123
    
    # Round to nearest manually if needed
    price = self.round_to_precision(desired_price, self.precision_price)
    
    # Place order (will also be rounded automatically)
    self.buy(quantity=volume, price=price)
```

---

## Order Placement

The strategy can place orders through the following methods:

### `buy()` and `sell()`

Basic methods for placing orders (market, limit, stop orders).

```python
# Market order
result = self.buy(quantity=1.0)
result = self.sell(quantity=0.5)

# Limit order
result = self.buy(quantity=1.0, price=100.0)
result = self.sell(quantity=0.5, price=105.0)

# Stop order
result = self.buy(quantity=1.0, trigger_price=110.0)
result = self.sell(quantity=0.5, trigger_price=95.0)
```

**Returns:** `OrderOperationResult` with order information.

### `buy_sltp()` and `sell_sltp()`

Methods for placing orders with automatic stop loss and/or take profit management.

#### `enter` Parameter (Entry Order)

Defines how to enter a position.

**1. Market order:**
```python
# Buy 1.0 at market
self.buy_sltp(enter=1.0)
```

**2. Limit order (single order):**
```python
# Buy 1.0 at price 100.0
self.buy_sltp(enter=(1.0, 100.0))
```

**3. Multiple limit orders:**
```python
# Buy 0.5 at price 100.0 and 0.5 at price 99.0
self.buy_sltp(enter=[(0.5, 100.0), (0.5, 99.0)])
```

#### `stop_loss` and `take_profit` Parameters (Exit Orders)

Both parameters have the same format and are optional.

**1. Simple stop loss/take profit (single price):**
```python
# Buy at market with stop loss at 90.0 and take profit at 110.0
self.buy_sltp(enter=1.0, stop_loss=90.0, take_profit=110.0)
```

**2. Multiple stop losses/take profits (equal parts):**
```python
# Buy 1.0, close 50% at stop 90.0 and 50% at stop 88.0
self.buy_sltp(enter=1.0, stop_loss=[90.0, 88.0])
```

**3. Multiple stop losses/take profits (custom fractions):**
```python
# Buy 1.0, close 50% at stop 90.0 and 50% at stop 88.0
self.buy_sltp(enter=1.0, stop_loss=[(0.5, 90.0), (0.5, 88.0)])

# Buy 1.0, close 30% at take profit 110.0, 40% at 112.0 and 30% at 114.0
self.buy_sltp(enter=1.0, take_profit=[(0.3, 110.0), (0.4, 112.0), (0.3, 114.0)])
```

**Important:** 
- When using the format with fractions (tuples), all orders must have an explicit fraction
- The sum of fractions must be equal to 1.0
- On the last stop loss or take profit order the remaining position will always be fully closed, regardless of rounding or partial executions

#### Return Value

Both methods return `OrderOperationResult`, which contains:
- `orders`: list of all created orders (entry + exit)
- `error_messages`: list of error messages (if any)
- `active`: list of active order IDs
- `executed`: list of executed order IDs
- `canceled`: list of canceled order IDs
- `error`: list of error order IDs
- `deal_id`: ID of the deal that groups all orders (entry and exit) created by this operation. For `buy()` and `sell()` methods, the value is 0 (automatic deal creation).
- `volume`: current position volume for the specific deal (`deal.quantity`) at the time of the request. At any given time there can be multiple open deals, so this value refers specifically to the deal `deal_id`.

---

## Order Management

### `cancel_orders(order_ids)`

Cancels orders by their IDs.

```python
# Cancel orders with IDs 1, 2, 3
result = self.cancel_orders([1, 2, 3])

# Check result
if result.error:
    # Some orders were not found
    self.logging(f"Failed to cancel orders: {result.error}", level="error")
```

**Parameters:**
- `order_ids`: list of order IDs to cancel

**Returns:** `OrderOperationResult` with information about canceled orders.

**Features:**
- If an order is not found, it is added to `result.error` and `result.error_messages`
- If an order is already executed or canceled, it is returned in the result without status change
- The `volume` field contains the position volume for the deal to which the canceled orders belong (`deal.quantity`)

### `deal_orders(deal_id)`

Gets all orders associated with the specified deal.

```python
# Get all orders for deal with ID 5
result = self.deal_orders(deal_id=5)

# Check result
if result.error_messages:
    # Deal not found
    self.logging(f"Error: {result.error_messages[0]}", level="error")
else:
    # Process orders
    for order in result.orders:
        self.logging(f"Order {order.order_id}: {order.status}")
```

**Parameters:**
- `deal_id`: deal ID

**Returns:** `OrderOperationResult` with all orders of the specified deal, categorized by status.

**Features:**
- If `deal_id` is not found, returns empty result with error in `error_messages`
- In the result, `deal_id` equals the passed value
- Orders are categorized by status: `active`, `executed`, `canceled`, `error`
- The `volume` field contains the current position volume for the specified deal (`deal.quantity`)

---

## Logging

The strategy can send messages to the message panel through the `logging()` method.

### `logging(message, level)`

Sends a message to the message panel.

```python
# Informational message
self.logging("Strategy started")

# Message with level
self.logging("Buy executed", level="info")
self.logging("Warning: insufficient data", level="warning")
self.logging("Error placing order", level="error")
self.logging("Successful operation", level="success")
self.logging("Debug information", level="debug")
```

**Parameters:**
- `message`: message text (required)
- `level`: message level (optional, default: `"info"`)

**Available levels:**
- `"info"` - informational message
- `"warning"` - warning
- `"error"` - error
- `"success"` - successful operation
- `"debug"` - debug information

**Features:**
- Messages are displayed in the message panel on the frontend
- Messages are also written to the log file
- Method is available only after broker initialization (in `on_start()`, `on_bar()`, `on_finish()`)

### Usage Examples

```python
def on_start(self):
    self.logging("Strategy initialized")
    self.logging(f"Parameters: ma_fast={self.parameters['ma_fast']}, ma_slow={self.parameters['ma_slow']}")

def on_bar(self):
    if len(self.close) < 50:
        self.logging("Insufficient data for calculation", level="warning")
        return
    
    # Place order
    result = self.buy(quantity=0.1)
    if result.error:
        self.logging(f"Error placing order: {result.error_messages[0]}", level="error")
    else:
        self.logging(f"Order placed: {result.executed[0]}", level="success")

def on_finish(self):
    self.logging(f"Backtesting completed. Final position: {self.equity_symbol}")
```

---

## Complete Strategy Example

```python
from app.services.tasks.strategy import Strategy
import numpy as np
from typing import Dict, Tuple, Any

class MovingAverageCrossoverStrategy(Strategy):
    """
    Moving average crossover strategy.
    Buys when fast MA crosses slow MA from below.
    Sells when fast MA crosses slow MA from above.
    """
    
    def __init__(self):
        super().__init__()
        self.ma_fast_period = None
        self.ma_slow_period = None
        self.position = None  # 'long', 'short', or None
    
    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        return {
            'ma_fast': (20, 'Fast moving average period'),
            'ma_slow': (50, 'Slow moving average period')
        }
    
    def on_start(self):
        """Initialize strategy."""
        self.ma_fast_period = self.parameters['ma_fast']
        self.ma_slow_period = self.parameters['ma_slow']
        self.logging(f"Strategy started: MA fast={self.ma_fast_period}, MA slow={self.ma_slow_period}")
    
    def on_bar(self):
        """Strategy logic on each bar."""
        # Check if enough data
        if len(self.close) < self.ma_slow_period:
            return
        
        # Calculate moving averages
        ma_fast = self.talib.SMA(value='close', timeperiod=self.ma_fast_period)
        ma_slow = self.talib.SMA(value='close', timeperiod=self.ma_slow_period)
        
        # Check if indicators are calculated
        if np.isnan(ma_fast[-1]) or np.isnan(ma_slow[-1]):
            return
        
        # Need at least 2 bars to determine crossover
        if len(ma_fast) < 2:
            return
        
        # Get values on previous and current bars
        prev_fast = ma_fast[-2]
        prev_slow = ma_slow[-2]
        curr_fast = ma_fast[-1]
        curr_slow = ma_slow[-1]
        
        # Check crossover from below (bullish)
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if self.position != 'long':
                # Buy
                result = self.buy(quantity=0.1)
                if not result.error:
                    self.position = 'long'
                    self.logging(f"Buy executed at price {self.close[-1]}")
        
        # Check crossover from above (bearish)
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            if self.position == 'long':
                # Sell
                result = self.sell(quantity=self.equity_symbol)
                if not result.error:
                    self.position = None
                    self.logging(f"Sell executed at price {self.close[-1]}")
    
    def on_finish(self):
        """Backtesting completion."""
        # Calculate total capital
        if len(self.close) > 0:
            current_price = self.close[-1]
            total_capital = self.equity_usd + self.equity_symbol * current_price
            self.logging(f"Backtesting completed. Position: {self.equity_symbol}, Balance USD: {self.equity_usd}, Total capital: {total_capital} USD")
        else:
            self.logging(f"Backtesting completed. Position: {self.equity_symbol}, Balance USD: {self.equity_usd}")
```

---

## Additional Information

### Data Types

- `PRICE_TYPE` - type for prices (usually `float`)
- `VOLUME_TYPE` - type for volumes (usually `float`)
- `TIME_TYPE` - type for time (usually `numpy.datetime64[ms]`)

### Error Handling

All order placement methods return `OrderOperationResult`, which contains error information:
- `error_messages` - list of error messages
- `error` - list of error order IDs

Always check for errors after placing orders:

```python
result = self.buy(quantity=1.0)
if result.error:
    self.logging(f"Error: {result.error_messages[0]}", level="error")
```

### Performance

- Indicators are cached automatically
- Quote arrays are updated efficiently
- Avoid creating large temporary arrays in `on_bar()`



