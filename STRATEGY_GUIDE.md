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
    
    # Access strategy file path if needed
    # self.strategy_file contains absolute path, e.g.:
    # /home/user/.local/share/r2d2/strategies/example_strategy/example_strategy.py
    if self.strategy_file:
        self.logging(f"Strategy file: {self.strategy_file}")
```

**Important:** At the time `on_start()` is called, the following are already available:
- `self.parameters` - strategy parameters
- `self.talib` - object for working with indicators
- `self.strategy_file` - absolute path to the strategy file (e.g., `/home/user/.local/share/r2d2/strategies/example_strategy/example_strategy.py`)

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
- `self.strategy_file` - absolute path to the strategy file

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

### Accessing Quotes for Other Symbols and Timeframes

The `self.quotes` proxy allows accessing raw OHLCV quotes for different symbols and timeframes directly:

```python
# Get primary quotes (same as self.close, self.open, etc. but as a Quotes object)
q = self.quotes()

# Get quotes on a higher timeframe
q_1h = self.quotes(timeframe='1h')

# Get quotes for a different symbol
q_eth = self.quotes(symbol='ETH/USDT:USDT')

# Both different symbol and timeframe
q_eth_1d = self.quotes(symbol='ETH/USDT:USDT', timeframe='1d')
```

The returned object is a `Quotes` object with the following arrays:
- `q.time` - time array
- `q.open` - open price array
- `q.high` - high price array
- `q.low` - low price array
- `q.close` - close price array
- `q.volume` - volume array

**Important restrictions:**
- **Timeframe must be >= primary timeframe** - only higher or equal timeframes are supported
- **Look-ahead bias prevention** - for higher timeframes, only **closed bars** are returned (the forming bar is excluded)
- Quotes for different symbols/timeframes are loaded automatically and cached

**Example:**

```python
def on_bar(self):
    # Get 1h quotes from 5m strategy
    q_1h = self.quotes(timeframe='1h')
    
    if len(q_1h.close) > 0:
        # Use 1h OHLCV data directly
        last_1h_close = q_1h.close[-1]
        last_1h_high = q_1h.high[-1]
        
        # Calculate custom metric on 1h data
        avg_range = np.mean(q_1h.high[-10:] - q_1h.low[-10:])
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

### Cross-Timeframe and Cross-Symbol Indicators

You can calculate indicators on different timeframes and symbols than the primary strategy timeframe/symbol by specifying `timeframe` and `symbol` parameters:

```python
# Calculate SMA on 1h timeframe (strategy is on 5m)
sma_1h = self.talib.SMA(value='close', timeperiod=20, timeframe='1h')

# Calculate RSI on different symbol
rsi_eth = self.talib.RSI(value='close', timeperiod=14, symbol='ETH/USDT:USDT')

# Both different timeframe and symbol
bb = self.talib.BBANDS(
    value='close', 
    timeperiod=20, 
    nbdevup=2, 
    nbdevdn=2,
    symbol='ETH/USDT:USDT',
    timeframe='15m'
)
```

**Important restrictions:**
- **Timeframe must be >= primary timeframe** - only higher or equal timeframes are supported (e.g., if strategy is on 5m, you can use 15m, 1h, 4h, 1d, but not 1m)
- **Look-ahead bias prevention** - indicators on higher timeframes use only **closed bars** (the forming bar is excluded)
- **No chart display** - indicators calculated on different symbols/timeframes are not displayed on the frontend chart (they are for internal calculations only)

**How it works:**
- For the primary timeframe: indicator includes the current bar (it's complete in backtesting)
- For higher timeframes: indicator includes only closed bars up to (but not including) the forming bar at `current_time`
- Quotes for different symbols/timeframes are loaded automatically and cached for the entire backtesting period

**Example:**
```python
def on_bar(self):
    # Strategy is on 5m timeframe
    # Get SMA on 1h timeframe
    sma_1h = self.talib.SMA(value='close', timeperiod=20, timeframe='1h')
    
    # sma_1h contains only closed 1h bars (no look-ahead bias)
    # Length of sma_1h is the number of closed 1h bars up to current 5m bar
    
    if len(sma_1h) > 0 and not np.isnan(sma_1h[-1]):
        # Use 1h SMA value
        current_price = self.close[-1]
        if current_price > sma_1h[-1]:
            # Price is above 1h SMA
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

## pyita Library (self.ta)

In addition to TA-Lib, the **pyita** library is available with an extended set of technical indicators.

### Basic Usage

Indicators are called as methods of the `self.ta` object:

```python
# Simple moving average
sma = self.ta.sma(period=20, value='close')

# Exponential moving average
ema = self.ta.ema(period=12, value='close')

# RSI (value='close' by default)
rsi = self.ta.rsi(period=14)

# MACD (returns tuple of 3 arrays)
macd, signal, histogram = self.ta.macd(period_fast=12, period_slow=26, period_signal=9)

# Bollinger Bands (returns 5 arrays)
mid, upper, lower, width, z_score = self.ta.bollinger_bands(period=20, deviation=2)
```

### Key Differences from TA-Lib

| Parameter | TA-Lib | pyita |
|-----------|--------|-------|
| Period | `timeperiod` | `period` |
| Value | `value` | `value` |
| MA Type | - | `ma_type='sma'/'ema'/'mma'` |

### Available Indicators

**Moving Averages:**
- `sma(period, value='close')` - Simple Moving Average
- `ema(period, value='close')` - Exponential Moving Average
- `tema(period, value='close')` - Triple Exponential Moving Average
- `vwma(period, value='close')` - Volume Weighted Moving Average
- `ma(period, value='close', ma_type='sma')` - Universal Moving Average

**Trend Indicators:**
- `adx(period=14, smooth=14, ma_type='mma')` - Average Directional Index (returns: adx, p_di, m_di)
- `aroon(period=14)` - Aroon Indicator (returns: up, down, oscillator)
- `parabolic_sar(start=0.02, maximum=0.2, increment=0.02)` - Parabolic SAR (returns: sar, signal)
- `supertrend(period=10, multiplier=3, ma_type='mma')` - SuperTrend (returns: supertrend, signal)
- `macd(period_fast=12, period_slow=26, period_signal=9, value='close')` - MACD (returns: macd, signal, histogram)
- `ichimoku(period_short=9, period_mid=26, period_long=52, offset_senkou=26, offset_chikou=26)` - Ichimoku Cloud (returns: tenkan, kijun, senkou_a, senkou_b, chikou)

**Oscillators:**
- `rsi(period=14, ma_type='mma', value='close')` - Relative Strength Index (0-100)
- `stochastic(period=5, period_d=3, smooth=3, ma_type='sma')` - Stochastic Oscillator (returns: value_k, value_d, oscillator)
- `williams_r(period=14)` - Williams %R (-100 to 0)
- `cci(period=20)` - Commodity Channel Index
- `mfi(period=14)` - Money Flow Index
- `roc(period=14, value='close')` - Rate of Change
- `awesome(period_fast=5, period_slow=34, normalized=False)` - Awesome Oscillator
- `trix(period, value='close')` - Triple Exponential Average Oscillator

**Volatility:**
- `bollinger_bands(period=20, deviation=2, ma_type='sma', value='close')` - Bollinger Bands (returns: mid_line, up_line, down_line, width, z_score)
- `atr(smooth=14, ma_type='mma')` - Average True Range (returns: atr, atrp, tr)
- `keltner(period=10, multiplier=1, period_atr=10, ma_type='ema')` - Keltner Channels (returns: mid_line, up_line, down_line, width)
- `chandelier(period=22, multiplier=3, use_close=False)` - Chandelier Exit (returns: exit_long, exit_short)

**Volume Indicators:**
- `obv()` - On-Balance Volume
- `vwap()` - Volume Weighted Average Price
- `volume_osc(period_short=5, period_long=10, ma_type='ema')` - Volume Oscillator
- `adl(ma_period=None, ma_type='sma')` - Accumulation/Distribution Line (returns: adl, adl_ema)

**Other:**
- `zigzag(delta=0.02, depth=1, type='high_low', end_points=False)` - ZigZag (returns: pivots, pivot_types)

### Moving Average Types

Many pyita indicators support selecting the moving average type via the `ma_type` parameter:

- `'sma'` - Simple Moving Average
- `'ema'` - Exponential Moving Average (α = 2 / (period + 1))
- `'mma'` (or `'smma'`, `'rma'`) - Modified/Smoothed Moving Average (α = 1 / period)
- `'ema0'` - EMA with first value initialization
- `'mma0'` - MMA with first value initialization
- `'emaw'` - EMA with dynamic warmup period (TA-Lib compatible)
- `'mmaw'` - MMA with dynamic warmup period (TA-Lib compatible)

**Example:**

```python
# Bollinger Bands with EMA
bb_mid, bb_up, bb_down, bb_width, bb_z = self.ta.bollinger_bands(
    period=20, 
    deviation=2, 
    ma_type='ema'
)

# RSI with EMA smoothing instead of default MMA
rsi = self.ta.rsi(period=14, ma_type='ema')
```

### Usage Features

All pyita indicators work the same way as TA-Lib indicators:

1. **Return data only up to current bar** - arrays have length `self.broker.i_time + 1`
2. **Caching** - indicators are cached, repeated calls return cached values
3. **NaN values** - initial array elements may be NaN until enough data is available

### Cross-Timeframe and Cross-Symbol Indicators (pyita)

pyita indicators also support `timeframe` and `symbol` parameters:

```python
# Calculate SMA on 1h timeframe (strategy is on 5m)
sma_1h = self.ta.sma(period=20, timeframe='1h')

# Calculate RSI on different symbol
rsi_eth = self.ta.rsi(period=14, symbol='ETH/USDT:USDT')

# Both different timeframe and symbol
bb = self.ta.bollinger_bands(
    period=20, 
    deviation=2.0,
    symbol='ETH/USDT:USDT',
    timeframe='15m'
)

# SMA on high values, different timeframe
sma_high_1h = self.ta.sma(period=20, value='high', timeframe='1h')
```

**Same restrictions apply as TA-Lib:**
- **Timeframe must be >= primary timeframe** - only higher or equal timeframes are supported
- **Look-ahead bias prevention** - indicators on higher timeframes use only **closed bars**
- **No chart display** - indicators on different symbols/timeframes are not displayed on the frontend

**Example Strategy with pyita:**

```python
def on_bar(self):
    # Check if enough data
    if len(self.close) < 50:
        return
    
    # Calculate indicators on primary timeframe
    sma_fast = self.ta.sma(period=20, value='close')
    sma_slow = self.ta.sma(period=50, value='close')
    rsi = self.ta.rsi(period=14)
    
    # Calculate indicator on higher timeframe (1h)
    sma_1h = self.ta.sma(period=20, timeframe='1h')
    
    # Check if indicators are calculated
    if np.isnan(sma_fast[-1]) or np.isnan(sma_slow[-1]) or np.isnan(rsi[-1]):
        return
    
    # Check if 1h SMA is available (may be empty if not enough 1h bars closed yet)
    if len(sma_1h) > 0 and not np.isnan(sma_1h[-1]):
        # Use both 5m and 1h indicators
        current_price = self.close[-1]
        trend_1h = current_price > sma_1h[-1]  # Bullish on 1h
        
        if sma_fast[-1] > sma_slow[-1] and rsi[-1] < 70 and trend_1h:
            self.buy(quantity=0.1)
        elif sma_fast[-1] < sma_slow[-1] or rsi[-1] > 80 or not trend_1h:
            self.sell(quantity=0.1)
    else:
        # Fallback to 5m only if 1h not available yet
        if sma_fast[-1] > sma_slow[-1] and rsi[-1] < 70:
            self.buy(quantity=0.1)
        elif sma_fast[-1] < sma_slow[-1] or rsi[-1] > 80:
            self.sell(quantity=0.1)
```

For detailed documentation, see: https://github.com/hal9000cc/pyita

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

The strategy provides two methods for formatting values to precision. These are proxy methods that delegate to broker's internal formatting methods.

#### `format_volume(value: VOLUME_TYPE) -> VOLUME_TYPE`

Formats volume by rounding down to nearest multiple of `precision_amount`. This is a proxy for `broker.format_volume()`.

**Note:** This method uses floor rounding (always rounds down) to ensure volumes conform to exchange precision requirements.

```python
# Round volume down to precision
volume = 1.234
rounded_volume = self.format_volume(volume)
# If precision_amount = 0.1, result is 1.2 (rounded down)

# Example: 1.25 with precision_amount = 0.1 -> 1.2 (not 1.3)
volume2 = 1.25
rounded_volume2 = self.format_volume(volume2)
# Result: 1.2
```

#### `format_price(value: PRICE_TYPE) -> PRICE_TYPE`

Formats price by rounding to nearest multiple of `precision_price`. This is a proxy for `broker.format_price()`.

**Note:** This method rounds to nearest value to ensure prices conform to exchange precision requirements.

```python
# Round price to nearest precision
price = 100.123
rounded_price = self.format_price(price)
# If precision_price = 0.01, result is 100.12

# Example: 100.125 with precision_price = 0.01 -> 100.13 (rounded up)
price2 = 100.125
rounded_price2 = self.format_price(price2)
# Result: 100.13
```

### Automatic Rounding

All trading methods (`buy()`, `sell()`, `buy_sltp()`, `sell_sltp()`) automatically apply precision rounding before placing orders:

- **Volume (quantity)** - rounded down using `broker.format_volume()` (equivalent to `format_volume()`)
- **Price** - rounded to nearest using `broker.format_price()` (equivalent to `format_price()`)
- **Trigger price** - rounded to nearest using `broker.format_price()` (equivalent to `format_price()`)

**Note**: Even if you manually round values using `format_volume()` or `format_price()` before calling trading methods, the values will be rounded again automatically. This ensures all values conform to exchange precision requirements.

If a value is changed due to rounding, a warning is logged.

### Usage Examples

```python
def on_bar(self):
    # Calculate desired volume
    desired_volume = 1.2345
    
    # Round down manually if needed
    volume = self.format_volume(desired_volume)
    
    # Calculate desired price
    desired_price = 100.123
    
    # Round to nearest manually if needed
    price = self.format_price(desired_price)
    
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

#### Volume Calculation Rules for Stop Loss and Take Profit Orders

**IMPORTANT**: The volumes of stop loss and take profit orders are calculated dynamically and recalculated whenever orders execute. The calculation rules are:

1. **Stop Loss Volume Calculation**:
   - **Target volume** = current position volume (`deal.quantity`) + sum of unexecuted entry orders volume
   - Each stop loss order's volume is calculated by applying its fraction to the target volume
   - Volumes are rounded using `format_volume_round()` (rounds to nearest precision)
   - The last (extreme) stop loss order always closes all remaining volume
   - **Note**: Stop loss volumes are NOT reduced by executed take profit orders. They are calculated from current position + pending entries.

2. **Take Profit Volume Calculation**:
   - **Target volume** = current position volume (`deal.quantity`) only
   - Each take profit order's volume is calculated by applying its fraction to the target volume
   - Volumes are rounded using `format_volume_round()` (rounds to nearest precision)
   - The last (extreme) take profit order always closes all remaining volume
   - **Note**: Take profit volumes are NOT reduced by executed stop loss orders. They are calculated from current position only.

3. **Key Points**:
   - Both stop loss and take profit volumes are recalculated dynamically as orders execute
   - Stop loss volumes include unexecuted entry orders (to account for pending entries)
   - Take profit volumes are based only on current position (already executed entries)
   - Volumes are recalculated whenever an order executes, ensuring accurate distribution
   - The last order (extreme stop or extreme take) always closes all remaining volume to ensure the position is fully closed

**Example**:
```python
# Entry: 1.0 volume (market order)
# Stop losses: 0.33, 0.33, 0.34 (fractions)
# Take profits: 0.5, 0.5 (fractions)

# After entry executes on bar 1:
#   - Current position: 1.0
#   - Stop loss target_volume = 1.0 + 0 (no unexecuted entries) = 1.0
#   - Take profit target_volume = 1.0
#   - Stop volumes: 0.33, 0.33, 0.34 (from 1.0)
#   - Take volumes: 0.5, 0.5 (from 1.0)

# After first stop executes (0.33 volume):
#   - Current position: 0.67
#   - Stop loss target_volume = 0.67 + 0 = 0.67 (recalculated)
#   - Take profit target_volume = 0.67 (recalculated)
#   - Remaining stop volumes: 0.33, 0.34 (from 0.67)
#   - Take volumes: 0.5, 0.5 (from 0.67)

# After first take executes (0.5 volume):
#   - Current position: 0.17
#   - Stop loss target_volume = 0.17 + 0 = 0.17 (recalculated)
#   - Take profit target_volume = 0.17 (recalculated)
#   - Remaining stop volumes: 0.33, 0.34 (from 0.17, but will be adjusted)
#   - Remaining take volume: 0.5 (from 0.17, but will be adjusted)
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

### `deal_info(deal_id)`

Gets information about a deal by its ID, including all associated orders and trades.

```python
# Get deal information for deal with ID 5
deal = self.deal_info(deal_id=5)

if deal is None:
    # Deal not found
    self.logging(f"Deal {5} not found", level="error")
else:
    # Access deal information
    self.logging(f"Deal {deal.deal_id}: type={deal.type}, quantity={deal.quantity}")
    self.logging(f"Average buy price: {deal.avg_buy_price}, sell price: {deal.avg_sell_price}")
    self.logging(f"Profit: {deal.profit}, fee: {deal.fee}")
    
    # Access all orders associated with this deal
    for order in deal.orders:
        self.logging(f"Order {order.order_id}: {order.status}, side={order.side}")
    
    # Access all trades in this deal
    for trade in deal.trades:
        self.logging(f"Trade: {trade.quantity} @ {trade.price}")
```

**Parameters:**
- `deal_id`: ID of the deal to get information about

**Returns:** `Deal` object (deep copy) with all deal information, or `None` if deal with specified `deal_id` does not exist.

**Deal object contains:**
- `deal_id` - deal ID
- `type` - deal type (`LONG` or `SHORT`)
- `orders` - list of all orders (entry and exit) associated with this deal
- `trades` - list of all trades in this deal
- `quantity` - current position volume (becomes 0 when fully closed)
- `avg_buy_price` - average buy price across all buy trades
- `avg_sell_price` - average sell price across all sell trades
- `profit` - realized profit for the deal
- `fee` - total fees for the deal
- `is_closed` - whether the deal is closed
- `date_open` - deal open date
- `date_close` - deal close date (if closed)
- `errors` - list of error messages for the deal

**Features:**
- Returns `None` if deal with specified `deal_id` does not exist (no exception is raised)
- Returns a deep copy of the deal, so modifications to the returned object do not affect the original

### `modify_deal(deal_id, enter, stop_loss, take_profit)`

Modifies an existing deal by canceling all active orders and placing new ones. The existing position volume in the market is preserved. The deal direction (long/short) cannot be changed.

```python
# Modify deal: update stop loss and take profit, keep existing position
result = self.modify_deal(
    deal_id=5,
    stop_loss=90.0,  # New stop loss
    take_profit=110.0  # New take profit
)

# Modify deal: add more volume via limit orders, update exits
result = self.modify_deal(
    deal_id=5,
    enter=[(0.5, 99.0), (0.5, 98.0)],  # Add 1.0 more via limit orders
    stop_loss=[(0.5, 90.0), (0.5, 88.0)],  # Multiple stops
    take_profit=110.0
)

# Modify deal: add volume via market order
result = self.modify_deal(
    deal_id=5,
    enter=0.5,  # Add 0.5 more at market
    stop_loss=90.0,
    take_profit=110.0
)

# Modify deal: close part of position via market order
result = self.modify_deal(
    deal_id=5,
    enter=-0.3,  # Close 0.3 at market
    stop_loss=90.0,
    take_profit=110.0
)
```

**Parameters:**
- `deal_id`: ID of the deal to modify (required)
- `enter`: Entry order(s) - same format as `buy_sltp()`/`sell_sltp()`, or `None` to leave entry orders unchanged, or `0` to clear all entry orders, or negative value to close part of position (optional)
- `stop_loss`: Stop loss order(s) - same format as `buy_sltp()`/`sell_sltp()`, or `None` to leave stop loss orders unchanged, or `0` to clear all stop loss orders (optional)
- `take_profit`: Take profit order(s) - same format as `buy_sltp()`/`sell_sltp()`, or `None` to leave take profit orders unchanged, or `0` to clear all take profit orders (optional)

**Returns:** `OrderOperationResult` with all orders (new entry + exit if specified), categorized by status.

**Features:**
- **Selective Order Modification**: Only the order groups whose parameters are provided are modified. If a parameter is not specified or is `None`, the corresponding order group remains unchanged. This allows modifying only specific parts of a deal:
  - If only `enter` is provided → only entry orders are modified
  - If only `stop_loss` is provided → only stop loss orders are modified
  - If only `take_profit` is provided → only take profit orders are modified
  - Any combination of parameters can be provided to modify multiple groups simultaneously
- **Order Group Clearing**: Passing `0` for any parameter clears (removes) all active orders of that group:
  - `enter=0` → clears all entry orders (active entry orders are canceled, no new ones are created)
  - `stop_loss=0` → clears all stop loss orders (active stop loss orders are canceled, no new ones are created)
  - `take_profit=0` → clears all take profit orders (active take profit orders are canceled, no new ones are created)
  - If the specified group has no active orders, clearing has no effect (no error)
- **Deal Direction Preservation**: The deal direction (long/short) cannot be changed. The function will validate that new orders match the existing deal type.
- **Order Cancellation**: For order groups that are being modified (parameter provided and not `None`), all active (ACTIVE/NEW) orders of that group are canceled before placing new ones. Executed orders remain in the deal and are not canceled. Order groups with `None` parameter are not affected.
- **Position Preservation**: The existing position volume (`deal.quantity`) in the market is preserved. New entry orders add to the position, negative values close part of the position.
- **Enter Parameter**:
  - If `enter` is not specified or `enter=None`: entry orders remain unchanged
  - If `enter=0`: all active entry orders are cleared (canceled), no new entry orders are created
  - If `enter` is a positive value, new entry orders are placed according to the same rules as `buy_sltp()`/`sell_sltp()`:
    - Market order: `enter=volume` (single positive value)
    - Limit order: `enter=(volume, price)` (single tuple with positive volume)
    - Multiple limit orders: `enter=[(volume1, price1), (volume2, price2), ...]` (all volumes positive)
  - If `enter` is a negative value, a market order is placed to close part of the position:
    - Market close: `enter=-volume` (single negative value)
    - The absolute value must not exceed the current position volume (`abs(enter) <= abs(deal.quantity)`), otherwise the deal would reverse direction, which is not allowed
    - For LONG deals: negative `enter` creates a SELL market order
    - For SHORT deals: negative `enter` creates a BUY market order
  - For increasing position volume with limit orders:
    - For LONG deals: buy limit orders (price below current price) or buy market orders are allowed
    - For SHORT deals: sell limit orders (price above current price) or sell market orders are allowed
- **Stop Loss and Take Profit**:
  - If `stop_loss`/`take_profit` is not specified or is `None`: corresponding orders remain unchanged
  - If `stop_loss=0`/`take_profit=0`: all active orders of that group are cleared (canceled), no new ones are created
  - If a value is provided, same format as `buy_sltp()`/`sell_sltp()`: single price, list of prices (equal parts), or list of (fraction, price) tuples
  - **Direction Constraints** (automatically enforced based on deal type):
    - For LONG deals:
      - Stop loss orders: SELL STOP orders (trigger_price below current price)
      - Take profit orders: SELL LIMIT orders (price above current price)
    - For SHORT deals:
      - Stop loss orders: BUY STOP orders (trigger_price above current price)
      - Take profit orders: BUY LIMIT orders (price below current price)
- **Volume Calculation**: Stop loss and take profit volumes are calculated from the total entry volume. The total entry volume is calculated as: `current position volume + new positive enter orders - closed volume (from negative enter)`. This follows the same rules as `buy_sltp()`/`sell_sltp()`.
- **Enter Volume Update**: The `deal.enter_volume` field is updated to reflect the new total entry volume: `new_enter_volume = current_position_volume + new_positive_enter - closed_volume`.
- **Error Handling**:
  - If `deal_id` is not found, returns error in `error_messages`
  - If deal is closed (`deal.quantity == 0`), returns error in `error_messages`
  - If deal direction validation fails, returns error in `error_messages`
  - If price validation fails (e.g., wrong direction for stop/take, limit order price in wrong direction), returns error in `error_messages`
  - If negative `enter` value exceeds current position volume, returns error in `error_messages`
- **Return Value**: The `deal_id` field in the result equals the modified deal ID. The `volume` field contains the current position volume for the deal (`deal.quantity`) after modification.

**Restrictions:**
1. **Deal Direction**: The deal direction (long/short) cannot be changed. Attempting to place orders with the wrong direction will result in an error.
2. **Closed Deals**: If the deal is already closed (`deal.quantity == 0`), the function returns an error.
3. **Limit Order Direction**: 
   - For LONG deals: buy limit orders must have price below current price
   - For SHORT deals: sell limit orders must have price above current price
4. **Stop Loss Direction**: 
   - For LONG deals: stop loss must be SELL STOP (trigger_price below current price)
   - For SHORT deals: stop loss must be BUY STOP (trigger_price above current price)
5. **Take Profit Direction**:
   - For LONG deals: take profit must be SELL LIMIT (price above current price)
   - For SHORT deals: take profit must be BUY LIMIT (price below current price)
6. **Negative Enter Constraint**: The absolute value of negative `enter` must not exceed the current position volume. For example, if `deal.quantity = 1.0` for a LONG deal, `enter=-1.5` is not allowed as it would reverse the position.

**Examples:**

```python
# Example 1: Update only stop loss and take profit, no new entry
result = self.modify_deal(
    deal_id=5,
    stop_loss=90.0,
    take_profit=110.0
)

# Example 2: Add more volume via limit orders and update exits
result = self.modify_deal(
    deal_id=5,
    enter=[(0.3, 99.0), (0.2, 98.0)],  # Add 0.5 more via limit orders (below current price for LONG)
    stop_loss=[(0.5, 90.0), (0.5, 88.0)],
    take_profit=[(0.3, 110.0), (0.4, 112.0), (0.3, 114.0)]
)

# Example 3: Add volume via market order
result = self.modify_deal(
    deal_id=5,
    enter=0.5,  # Add 0.5 more at market
    stop_loss=90.0,
    take_profit=110.0
)

# Example 4: Close part of position via market order
result = self.modify_deal(
    deal_id=5,
    enter=-0.3,  # Close 0.3 at market (must not exceed current position volume)
    stop_loss=90.0,
    take_profit=110.0
)

# Example 5: Only update stop loss, clear take profit
result = self.modify_deal(
    deal_id=5,
    stop_loss=92.0,  # New stop loss
    take_profit=0  # Clear all take profit orders
)

# Example 5a: Only update stop loss, leave take profit unchanged
result = self.modify_deal(
    deal_id=5,
    stop_loss=92.0,  # New stop loss
    take_profit=None  # Leave take profit orders unchanged
)

# Example 6: Add volume and update exits in one call
result = self.modify_deal(
    deal_id=5,
    enter=0.2,  # Add 0.2 more at market
    stop_loss=95.0,  # Update stop loss
    take_profit=[(0.5, 110.0), (0.5, 115.0)]  # Update take profit with multiple levels
)

# Example 7: Clear entry orders, update only stop loss
result = self.modify_deal(
    deal_id=5,
    enter=0,  # Clear all entry orders
    stop_loss=90.0  # Update stop loss
)

# Example 8: Clear stop loss and take profit, leave entry orders unchanged
result = self.modify_deal(
    deal_id=5,
    stop_loss=0,  # Clear all stop loss orders
    take_profit=0  # Clear all take profit orders
)

# Example 9: Selective modification - only update take profit
result = self.modify_deal(
    deal_id=5,
    take_profit=115.0  # Only take profit is updated, entry and stop loss remain unchanged
)
```

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

# Message can be any type - will be converted to string automatically
self.logging(123)  # Will be converted to "123"
self.logging(3.14)  # Will be converted to "3.14"
self.logging({"key": "value"})  # Will be converted to string representation
```

**Parameters:**
- `message`: message text (required). Can be any type - will be automatically converted to string if not already a string.
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



