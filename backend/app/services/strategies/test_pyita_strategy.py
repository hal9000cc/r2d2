from app.services.tasks.strategy import Strategy
from typing import Dict, Tuple, Any
import numpy as np


class TestPyitaStrategy(Strategy):
    """
    Test strategy for pyita library integration.
    
    This strategy tests various pyita indicators:
    - Single-output indicators (SMA, EMA, RSI)
    - Multi-output indicators (MACD, Bollinger Bands)
    - Moving average types
    - Caching and slicing functionality
    """
    
    def __init__(self):
        super().__init__()
        self.position_opened = False
    
    @staticmethod
    def get_parameters_description() -> Dict[str, Tuple[Any, str]]:
        """
        Get parameters description of the strategy.
        
        Returns:
            Dictionary with strategy parameters
        """
        return {
            'sma_fast': (20, 'Fast SMA period'),
            'sma_slow': (50, 'Slow SMA period'),
            'rsi_period': (14, 'RSI period'),
            'rsi_overbought': (70, 'RSI overbought level'),
            'rsi_oversold': (30, 'RSI oversold level'),
            'macd_fast': (12, 'MACD fast period'),
            'macd_slow': (26, 'MACD slow period'),
            'macd_signal': (9, 'MACD signal period'),
            'bb_period': (20, 'Bollinger Bands period'),
            'bb_deviation': (2.0, 'Bollinger Bands deviation'),
        }
    
    def on_start(self, state=None):
        """
        Called before the start of trading.
        Initialize strategy variables and log start.
        """
        # Store parameters in instance variables
        self.sma_fast_period = self.parameters['sma_fast']
        self.sma_slow_period = self.parameters['sma_slow']
        self.rsi_period = self.parameters['rsi_period']
        self.rsi_overbought = self.parameters['rsi_overbought']
        self.rsi_oversold = self.parameters['rsi_oversold']
        self.macd_fast = self.parameters['macd_fast']
        self.macd_slow = self.parameters['macd_slow']
        self.macd_signal = self.parameters['macd_signal']
        self.bb_period = self.parameters['bb_period']
        self.bb_deviation = self.parameters['bb_deviation']
        
        self.logging("TestPyitaStrategy started - testing pyita library")
        self.logging(f"SMA periods: {self.sma_fast_period}/{self.sma_slow_period}")
        self.logging(f"RSI period: {self.rsi_period}")
    
    def on_bar(self):
        """
        Called when a new bar is received.
        Test various pyita indicators and implement simple trading logic.
        """
        # Wait for enough data
        if len(self.close) < max(self.sma_slow_period, self.rsi_period, self.macd_slow):
            return
        
        # === Test 1: Single-output indicators ===
        
        # Simple Moving Average
        sma_fast = self.ta.sma(period=self.sma_fast_period, value='close')
        sma_slow = self.ta.sma(period=self.sma_slow_period, value='close')
        
        # Exponential Moving Average
        ema = self.ta.ema(period=self.sma_fast_period, value='close')
        
        # RSI (value='close' by default)
        rsi = self.ta.rsi(period=self.rsi_period)
        
        # Check if indicators are calculated (no NaN)
        if (np.isnan(sma_fast[-1]) or np.isnan(sma_slow[-1]) or 
            np.isnan(ema[-1]) or np.isnan(rsi[-1])):
            return
        
        # === Test 2: Multi-output indicators ===
        
        # MACD
        macd, signal, histogram = self.ta.macd(
            period_fast=self.macd_fast,
            period_slow=self.macd_slow,
            period_signal=self.macd_signal
        )
        
        # Bollinger Bands
        bb_mid, bb_upper, bb_lower, bb_width, bb_z = self.ta.bollinger_bands(
            period=self.bb_period,
            deviation=self.bb_deviation
        )
        
        # Check MACD and BB
        if (np.isnan(macd[-1]) or np.isnan(signal[-1]) or 
            np.isnan(bb_mid[-1]) or np.isnan(bb_upper[-1])):
            return
        
        # === Test 3: Moving average types ===
        
        # Test different MA types
        rsi_ema = self.ta.rsi(period=self.rsi_period, ma_type='ema')
        bb_ema_mid, bb_ema_up, bb_ema_down, _, _ = self.ta.bollinger_bands(
            period=self.bb_period,
            deviation=self.bb_deviation,
            ma_type='ema'
        )
        
        if np.isnan(rsi_ema[-1]) or np.isnan(bb_ema_mid[-1]):
            return
        
        # === Trading Logic ===
        
        current_price = self.close[-1]
        
        # Buy signal: SMA crossover + RSI oversold + MACD bullish
        buy_signal = (
            sma_fast[-1] > sma_slow[-1] and  # Fast SMA above slow SMA
            sma_fast[-2] <= sma_slow[-2] and  # Crossover just happened
            rsi[-1] < self.rsi_overbought and  # RSI not overbought
            macd[-1] > signal[-1]  # MACD above signal
        )
        
        # Sell signal: SMA crossunder + RSI overbought + MACD bearish
        sell_signal = (
            sma_fast[-1] < sma_slow[-1] and  # Fast SMA below slow SMA
            sma_fast[-2] >= sma_slow[-2] and  # Crossunder just happened
            rsi[-1] > self.rsi_oversold and  # RSI not oversold
            macd[-1] < signal[-1]  # MACD below signal
        )
        
        # Additional condition: price near Bollinger Bands
        near_lower_band = current_price < bb_mid[-1] and current_price > bb_lower[-1]
        near_upper_band = current_price > bb_mid[-1] and current_price < bb_upper[-1]
        
        # Execute trades
        if buy_signal and near_lower_band and not self.position_opened:
            self.logging(f"BUY signal: SMA={sma_fast[-1]:.2f}/{sma_slow[-1]:.2f}, RSI={rsi[-1]:.2f}, MACD={macd[-1]:.4f}")
            self.buy(quantity=0.01)
            self.position_opened = True
        
        elif sell_signal and near_upper_band and self.position_opened:
            self.logging(f"SELL signal: SMA={sma_fast[-1]:.2f}/{sma_slow[-1]:.2f}, RSI={rsi[-1]:.2f}, MACD={macd[-1]:.4f}")
            self.sell(quantity=0.01)
            self.position_opened = False
        
        # Log indicator values every 100 bars for debugging
        if len(self.close) % 100 == 0:
            self.logging(
                f"Indicators: SMA_fast={sma_fast[-1]:.2f}, SMA_slow={sma_slow[-1]:.2f}, "
                f"RSI={rsi[-1]:.2f}, MACD={macd[-1]:.4f}, BB_mid={bb_mid[-1]:.2f}"
            )
    
    def on_finish(self):
        """
        Called after the testing loop completes.
        """
        self.logging("TestPyitaStrategy finished - pyita integration test completed")
        
        # Log final statistics
        if hasattr(self, 'equity_usd'):
            self.logging(f"Final equity: ${self.equity_usd:.2f}")

