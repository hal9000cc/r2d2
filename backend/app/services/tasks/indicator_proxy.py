"""
Technical analysis indicator proxy classes.
Handles calculation and caching of technical indicators.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Callable, List, Tuple, Union, Any
import inspect
import re
import numpy as np
import talib
from pydantic import BaseModel, ConfigDict
from app.core.logger import get_logger
from app.core.utils import generate_random_color

logger = get_logger(__name__)

# Line style mapping: string -> lightweight-charts number
LINE_STYLE_MAP = {
    'solid': 0,
    'dotted': 1,
    'dashed': 2,
    'large-dashed': 3,
    'sparse-dotted': 4
}

# Default line settings
DEFAULT_LINE_WIDTH = 2
DEFAULT_LINE_STYLE = 'solid'  # Maps to 0


def parse_lines_config(lines_str: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse lines configuration string into list of line settings.
    
    Format: "#color;width;style|#color;width;style|..."
    - Color: hex string (e.g., '#FF5733')
    - Width: number 1-10 (default: 2)
    - Style: solid|dotted|dashed|large-dashed|sparse-dotted (default: solid)
    
    Parameters can be omitted (from right to left):
    - "#FF5733" - only color, width=2, style=solid
    - "#FF5733;3" - color and width, style=solid
    - "#FF5733;3;dashed" - all parameters
    
    Args:
        lines_str: Lines configuration string
        
    Returns:
        Tuple of (line_settings, errors):
        - line_settings: List of line settings: [{'color': str, 'lineWidth': int, 'lineStyle': int}, ...]
          Always returns valid settings (uses defaults on parse error)
        - errors: List of error messages (empty if no errors)
    """
    errors = []
    
    if not lines_str or not isinstance(lines_str, str):
        error_msg = f"Invalid lines config: empty or invalid input"
        logger.error(error_msg)
        errors.append(error_msg)
        return [{'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]}], errors
    
    result = []
    lines = lines_str.split('|')
    
    for line_config in lines:
        line_config = line_config.strip()
        if not line_config:
            continue
        
        parts = [p.strip() for p in line_config.split(';')]
        
        # Parse color (required, first part)
        if not parts or not parts[0]:
            error_msg = f"Invalid lines config: missing color in '{line_config}'"
            logger.error(error_msg)
            errors.append(error_msg)
            result.append({'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]})
            continue
        
        color = parts[0]
        # Validate hex color format
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            error_msg = f"Invalid lines config: invalid color format '{color}' in '{line_config}'"
            logger.error(error_msg)
            errors.append(error_msg)
            result.append({'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]})
            continue
        
        # Parse width (optional, second part)
        line_width = DEFAULT_LINE_WIDTH
        if len(parts) >= 2 and parts[1]:
            try:
                width = int(parts[1])
                if 1 <= width <= 10:
                    line_width = width
                else:
                    error_msg = f"Invalid lines config: width must be 1-10, got '{parts[1]}' in '{line_config}'"
                    logger.error(error_msg)
                    errors.append(error_msg)
            except ValueError:
                error_msg = f"Invalid lines config: invalid width '{parts[1]}' in '{line_config}'"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # Parse style (optional, third part)
        line_style = LINE_STYLE_MAP[DEFAULT_LINE_STYLE]
        if len(parts) >= 3 and parts[2]:
            style_str = parts[2].lower()
            if style_str in LINE_STYLE_MAP:
                line_style = LINE_STYLE_MAP[style_str]
            else:
                error_msg = f"Invalid lines config: invalid style '{parts[2]}' in '{line_config}', valid: {list(LINE_STYLE_MAP.keys())}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        result.append({
            'color': color,
            'lineWidth': line_width,
            'lineStyle': line_style
        })
    
    # If no valid lines parsed, return default
    if not result:
        error_msg = f"Failed to parse lines config: '{lines_str}', using defaults"
        logger.error(error_msg)
        errors.append(error_msg)
        return [{'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]}], errors
    
    return result, errors


class IndicatorDescription(BaseModel):
    """
    Description of technical analysis indicator.
    """
    values: List[str]  # List of positional parameter names (open, high, low, close, volume) in order


class UsedIndicatorDescription(BaseModel):
    """
    Description of a used indicator with its cached values and visibility flag.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    values: Union[np.ndarray, Tuple[np.ndarray, ...]]  # Cached indicator values (series or tuple of series)
    visible: bool = True  # Visibility flag for frontend display
    series_info: List[Dict[str, Any]]  # List of series descriptions: [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int}, ...]


class ta_proxy(ABC):
    """
    Abstract base class for technical analysis indicator proxy.
    Different implementations for different TA libraries (talib, ta, etc.)
    """
    
    def __init__(self, broker, quotes_data: dict):
        """
        Initialize TA proxy.
        
        Args:
            broker: Reference to broker instance
            quotes_data: Dictionary with quotes data (time, open, high, low, close, volume)
        """
        self.broker = broker
        self.quotes_data = quotes_data
        self.cache = {}
    
    @abstractmethod
    def calc_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Calculate indicator values for entire dataset.
        Must be implemented in subclasses for specific TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values for entire dataset
        """
        pass
    
    def get_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Get indicator values with caching and slicing to current bar.
        Common implementation for all TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters (may include 'lines' for line styling)
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values sliced to current bar
        """
        # Extract lines config from kwargs (if present)
        lines_config = kwargs.pop('lines', None)
        
        # Create cache key from name and sorted parameters (without lines, as it doesn't affect values)
        cache_key = (name, tuple(sorted(kwargs.items())))
        
        # Check cache
        if cache_key not in self.cache:
            # Calculate indicator for entire dataset
            indicator_values = self.calc_indicator(name, **kwargs)
            
            # Determine series info (names, is_price flags, and line settings)
            is_tuple = isinstance(indicator_values, tuple)
            tuple_length = len(indicator_values) if is_tuple else 1
            series_info = []
            if isinstance(self, ta_proxy_talib):
                series_info = self._get_series_info(name, is_tuple, tuple_length, lines_config)
            else:
                # For non-talib proxies, use generic logic with parsed lines or defaults
                if lines_config:
                    lines_settings, parse_errors = parse_lines_config(lines_config)
                    # Send parse errors to frontend if broker is available
                    if parse_errors and self.broker:
                        for error_msg in parse_errors:
                            self.broker.logging(f"Indicator '{name}': {error_msg}", 'error')
                else:
                    lines_settings = [{'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]}]
                
                series_info = self._create_series_info_list(lines_settings, is_tuple, tuple_length, name, is_price=True)
            
            # Store in cache as UsedIndicatorDescription
            self.cache[cache_key] = UsedIndicatorDescription(
                values=indicator_values,
                visible=True,
                series_info=series_info
            )
        
        # Get cached indicator description
        indicator_desc = self.cache[cache_key]
        full_data = indicator_desc.values
        
        # Check if result is a tuple (multiple return values)
        if isinstance(full_data, tuple):
            # Return tuple of slices
            return tuple(arr[:self.broker.i_time + 1] for arr in full_data)
        else:
            # Return single array slice
            return full_data[:self.broker.i_time + 1]
    
    def __getattr__(self, indicator_name: str):
        """
        Intercept indicator name access (e.g., self.talib.SMA).
        Returns a callable that will call get_indicator.
        
        Args:
            indicator_name: Name of the indicator (e.g., 'SMA', 'EMA')
            
        Returns:
            Callable that accepts **kwargs and returns indicator values
        """
        # Don't intercept private/special attributes
        if indicator_name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{indicator_name}'")
        
        def indicator_caller(**kwargs):
            return self.get_indicator(indicator_name, **kwargs)
        
        return indicator_caller


class ta_proxy_talib(ta_proxy):
    """
    Technical analysis proxy for TA-Lib library.
    """
    
    # Valid positional parameter names
    VALID_POSITIONAL_PARAMS = {'open', 'high', 'low', 'close', 'volume', 'real', 'real0', 'real1', 'periods'}
    
    # Dictionary of indicator descriptions with series names, price chart displayability, and line settings
    # Format: {'is_price': bool, 'lines': Optional[str], 'series': Optional[List[Dict]]}
    # If 'series' is provided, uses those names. If not, generates generic names (series0, series1, ...)
    # Each series can override 'is_price' by including it in its dict
    # Lines priority: kwargs.lines > indicator.lines > defaults
    # Lines format: "#color;width;style|#color;width;style|..."
    #   - Color: hex string (e.g., '#FF5733')
    #   - Width: number 1-10 (default: 2)
    #   - Style: solid|dotted|dashed|large-dashed|sparse-dotted (default: solid)
    #   - Parameters can be omitted from right: "#FF5733" or "#FF5733;3" or "#FF5733;3;dashed"
    #   - Multiple lines separated by '|', applied cyclically to series
    # Names are taken from TA-Lib documentation (Outputs section)
    INDICATOR_SERIES_NAMES = {
        # Multi-series indicators
        'MACD': {
            'is_price': False,
            'series': [{'name': 'macd'}, {'name': 'macdsignal'}, {'name': 'macdhist'}],
        },
        'BBANDS': {
            'is_price': True,
            'lines': '#006666;2;solid|#B0B0B0;2;solid|#006666;2;solid',
            'series': [{'name': 'upperband'}, {'name': 'middleband'}, {'name': 'lowerband'}],
        },
        'STOCH': {
            'is_price': False,
            'series': [{'name': 'slowk'}, {'name': 'slowd'}],
        },
        'STOCHF': {
            'is_price': False,
            'series': [{'name': 'fastk'}, {'name': 'fastd'}],
        },
        'STOCHRSI': {
            'is_price': False,
            'series': [{'name': 'fastk'}, {'name': 'fastd'}],
        },
        'AROON': {
            'is_price': False,
            'series': [{'name': 'aroondown'}, {'name': 'aroonup'}],
        },
        # Single-series non-price indicators
        'ATR': {'is_price': False},
        'NATR': {'is_price': False},
        'TRANGE': {'is_price': False},
        'ADX': {'is_price': False},
        'ADXR': {'is_price': False},
        'APO': {'is_price': False},
        'AROONOSC': {'is_price': False},
        'BOP': {'is_price': False},
        'CCI': {'is_price': False},
        'CMO': {'is_price': False},
        'DX': {'is_price': False},
        'MOM': {'is_price': False},
        'PLUS_DI': {'is_price': False},
        'PLUS_DM': {'is_price': False},
        'MINUS_DI': {'is_price': False},
        'MINUS_DM': {'is_price': False},
        'PPO': {'is_price': False},
        'ROC': {'is_price': False},
        'ROCP': {'is_price': False},
        'ROCR': {'is_price': False},
        'ROCR100': {'is_price': False},
        'RSI': {'is_price': False},
        'ULTOSC': {'is_price': False},
        'WILLR': {'is_price': False},
        'HT_DCPERIOD': {'is_price': False},
        'HT_DCPHASE': {'is_price': False},
        'HT_TRENDMODE': {'is_price': False},
        'LINEARREG': {'is_price': False},
        'LINEARREG_ANGLE': {'is_price': False},
        'LINEARREG_INTERCEPT': {'is_price': False},
        'LINEARREG_SLOPE': {'is_price': False},
        'STDDEV': {'is_price': False},
        'VAR': {'is_price': False},
        'TSF': {'is_price': False},
        'MAX': {'is_price': False},
        'MAXINDEX': {'is_price': False},
        'MIN': {'is_price': False},
        'MININDEX': {'is_price': False},
        'SUM': {'is_price': False},
    }

    def __init__(self, broker, quotes_data: dict):
        """
        Initialize TA-Lib proxy.
        Analyzes talib functions and builds indicator descriptions.
        
        Args:
            broker: Reference to broker instance
            quotes_data: Dictionary with quotes data (time, open, high, low, close, volume)
        """
        super().__init__(broker, quotes_data)
        
        # Dictionary to store indicator descriptions
        self._indicator_descriptions: Dict[str, IndicatorDescription] = {}
        
        # Analyze talib functions
        self._analyze_talib_functions()
    
    def _create_series_info_list(
        self,
        lines_settings: List[Dict[str, Any]],
        is_tuple: bool,
        tuple_length: int,
        base_name: str,
        is_price: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Create list of series info dictionaries from line settings.
        
        Args:
            lines_settings: List of line settings (color, lineWidth, lineStyle)
            is_tuple: Whether indicator returns tuple of arrays
            tuple_length: Length of tuple (number of series), or 1 for single array
            base_name: Base name for series (used as-is for single, or with index for tuple)
            is_price: is_price flag for all series
            
        Returns:
            List of series info dictionaries
        """
        if is_tuple:
            return [{
                'name': f'series{i}',
                'is_price': is_price,
                'color': lines_settings[i % len(lines_settings)]['color'],
                'lineWidth': lines_settings[i % len(lines_settings)]['lineWidth'],
                'lineStyle': lines_settings[i % len(lines_settings)]['lineStyle']
            } for i in range(tuple_length)]
        else:
            line_setting = lines_settings[0]
            return [{
                'name': base_name,
                'is_price': is_price,
                'color': line_setting['color'],
                'lineWidth': line_setting['lineWidth'],
                'lineStyle': line_setting['lineStyle']
            }]
    
    def _get_series_info(self, indicator_name: str, is_tuple: bool, tuple_length: int, lines_config: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get series info (names, is_price flags, and line settings) for indicator.
        
        Args:
            indicator_name: Name of the indicator (e.g., 'MACD', 'BBANDS')
            is_tuple: Whether indicator returns tuple of arrays
            tuple_length: Length of tuple (number of series), or 1 for single array
            lines_config: Optional lines configuration string from kwargs (has priority)
            
        Returns:
            List of series info dictionaries: [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int}, ...]
            Line settings are always present (from lines_config, indicator description, or defaults)
        """
        # Priority: lines_config (from kwargs) > indicator description > defaults
        lines_settings = None
        all_parse_errors = []
        
        if lines_config:
            # Parse lines from kwargs
            lines_settings, parse_errors = parse_lines_config(lines_config)
            all_parse_errors.extend(parse_errors)
        elif indicator_name in self.INDICATOR_SERIES_NAMES:
            # Try to get lines from indicator description
            indicator_desc = self.INDICATOR_SERIES_NAMES[indicator_name]
            desc_lines = indicator_desc.get('lines')
            if desc_lines:
                lines_settings, parse_errors = parse_lines_config(desc_lines)
                all_parse_errors.extend(parse_errors)
        
        # If no lines settings, use defaults
        if not lines_settings:
            default_line = {'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]}
            lines_settings = [default_line]
        
        # Send parse errors to frontend if broker is available
        if all_parse_errors and self.broker:
            for error_msg in all_parse_errors:
                self.broker.logging(f"Indicator '{indicator_name}': {error_msg}", 'error')
        
        # Check if indicator has description in dictionary
        if indicator_name in self.INDICATOR_SERIES_NAMES:
            indicator_desc = self.INDICATOR_SERIES_NAMES[indicator_name]
            default_is_price = indicator_desc.get('is_price', True)
            series_list = indicator_desc.get('series')
            
            if series_list:
                # Use provided series names
                result = []
                for i, series_desc in enumerate(series_list):
                    series_name = series_desc.get('name', f'series{i}')
                    # Use is_price from series if provided, otherwise use default
                    series_is_price = series_desc.get('is_price', default_is_price)
                    # Get line settings cyclically
                    line_setting = lines_settings[i % len(lines_settings)]
                    result.append({
                        'name': series_name,
                        'is_price': series_is_price,
                        'color': line_setting['color'],
                        'lineWidth': line_setting['lineWidth'],
                        'lineStyle': line_setting['lineStyle']
                    })
                
                # Validate length matches
                if len(result) != tuple_length:
                    logger.warning(
                        f"Indicator '{indicator_name}' description has {len(result)} series, "
                        f"but actual result has {tuple_length} series. Using actual count."
                    )
                    # Adjust to actual length
                    if len(result) > tuple_length:
                        result = result[:tuple_length]
                    else:
                        # Add generic names for missing series
                        for i in range(len(result), tuple_length):
                            line_setting = lines_settings[i % len(lines_settings)]
                            result.append({
                                'name': f'series{i}',
                                'is_price': default_is_price,
                                'color': line_setting['color'],
                                'lineWidth': line_setting['lineWidth'],
                                'lineStyle': line_setting['lineStyle']
                            })
                
                return result
            else:
                # No series list provided, generate generic names with default is_price
                return self._create_series_info_list(lines_settings, is_tuple, tuple_length, indicator_name, is_price=default_is_price)
        else:
            # Indicator not in dictionary
            return self._create_series_info_list(lines_settings, is_tuple, tuple_length, indicator_name, is_price=True)
    
    def _analyze_talib_functions(self):
        """
        Analyze talib functions and build indicator descriptions.
        Only includes functions with valid positional parameters (open, high, low, close, volume).
        """
        for name in dir(talib):
            # Skip private/special attributes
            if name.startswith('_'):
                continue
            
            # Get attribute from talib
            attr = getattr(talib, name)
            
            # Check if it's callable
            if not callable(attr):
                continue
            
            try:
                # Get function signature
                sig = inspect.signature(attr)
                
                # Extract positional parameter names that are in VALID_POSITIONAL_PARAMS
                positional_params = []
                skip_function = False
                
                for param_name, param in sig.parameters.items():
                    # Check if parameter has default value (then it's in kwargs, not positional)
                    if param.default != inspect.Parameter.empty:
                        # This parameter will be in kwargs, skip it
                        continue
                    
                    # This is a positional parameter (no default value)
                    if param_name in self.VALID_POSITIONAL_PARAMS:
                        positional_params.append(param_name)
                    else:
                        # Invalid positional parameter - skip this function
                        logger.warning(
                            f"TA-Lib function '{name}' has invalid positional parameter '{param_name}'. "
                            f"Only {self.VALID_POSITIONAL_PARAMS} are allowed. Skipping."
                        )
                        skip_function = True
                        break
                
                if not skip_function and positional_params:
                    # All positional params are valid - save indicator description
                    self._indicator_descriptions[name] = IndicatorDescription(values=positional_params)
            except Exception as e:
                # Skip functions that can't be analyzed
                logger.debug(f"Could not analyze function '{name}': {e}")
                continue
    
    def calc_indicator(self, name: str, **kwargs) -> Union[np.ndarray, Tuple[np.ndarray, ...]]:
        """
        Calculate indicator values using TA-Lib.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters (non-positional)
            
        Returns:
            Numpy array or tuple of numpy arrays with indicator values for entire dataset
            
        Raises:
            ValueError: If indicator name is not found in descriptions
        """
        # Get indicator description
        if name not in self._indicator_descriptions:
            raise ValueError(f"TA-Lib indicator '{name}' is not available or has invalid parameters")
        
        description = self._indicator_descriptions[name]
        
        # Get function from talib
        talib_function = getattr(talib, name)
        
        # Build positional arguments from quotes_data
        args = []
        # Create a copy of kwargs to modify it (remove 'value' if used)
        call_kwargs = kwargs.copy()
        
        for param_name in description.values:
            if param_name == 'real':
                # For 'real' parameter, get series name from kwargs['value']
                if 'value' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real' (series name), "
                        f"but 'value' parameter is not provided in kwargs"
                    )
                # Get series name from value parameter
                series_name = kwargs['value']
                # Remove 'value' from kwargs as it's not a talib parameter
                call_kwargs.pop('value', None)
                # Get data from quotes_data using series name
                if series_name not in self.quotes_data:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value' parameter, but it's not available in quotes_data"
                    )
                args.append(self.quotes_data[series_name])
            elif param_name == 'real0':
                # For 'real0' parameter, get series name from kwargs['value0']
                if 'value0' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real0' (series name), "
                        f"but 'value0' parameter is not provided in kwargs"
                    )
                # Get series name from value0 parameter
                series_name = kwargs['value0']
                # Remove 'value0' from kwargs as it's not a talib parameter
                call_kwargs.pop('value0', None)
                # Get data from quotes_data using series name
                if series_name not in self.quotes_data:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value0' parameter, but it's not available in quotes_data"
                    )
                args.append(self.quotes_data[series_name])
            elif param_name == 'real1':
                # For 'real1' parameter, get series name from kwargs['value1']
                if 'value1' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real1' (series name), "
                        f"but 'value1' parameter is not provided in kwargs"
                    )
                # Get series name from value1 parameter
                series_name = kwargs['value1']
                # Remove 'value1' from kwargs as it's not a talib parameter
                call_kwargs.pop('value1', None)
                # Get data from quotes_data using series name
                if series_name not in self.quotes_data:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value1' parameter, but it's not available in quotes_data"
                    )
                args.append(self.quotes_data[series_name])
            elif param_name == 'periods':
                # For 'periods' parameter, get value from kwargs['periods']
                if 'periods' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'periods', "
                        f"but 'periods' parameter is not provided in kwargs"
                    )
                # Get periods value from kwargs
                periods_value = kwargs['periods']
                # Remove 'periods' from kwargs as it's passed as positional argument
                call_kwargs.pop('periods', None)
                # Add periods value as positional argument
                args.append(periods_value)
            else:
                # Regular parameter - get directly from quotes_data
                args.append(self.quotes_data[param_name])
        
        try:
            # Call talib function with *args and **kwargs (without 'value')
            result = talib_function(*args, **call_kwargs)
            return result
        except Exception as e:
            # Re-raise with more context
            raise RuntimeError(f"Error calling talib.{name}(*args, **kwargs): {e}") from e

