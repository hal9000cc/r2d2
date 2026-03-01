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
import pyita as ta
from pydantic import BaseModel, ConfigDict
from app.core.logger import get_logger
from app.core.utils import generate_random_color
from app.services.tasks.exceptions import R2D2IndicatorNotFoundError
from app.services.tasks.quotes_provider import QuotesProvider
from app.services.quotes.timeframe import Timeframe

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


def parse_lines_dict(lines_dict: Dict[str, Dict[str, Any]], valid_line_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Parse lines configuration dictionary into validated line settings.
    
    Format: {'line_name': {'visible': bool, 'color': str, 'lineWidth': int, 'lineStyle': str}, ...}
    - visible: bool (default: True if not specified)
    - color: hex string (e.g., '#FF5733') - optional, uses generate_random_color() if not specified
    - lineWidth: int 1-10 (default: 2) - optional
    - lineStyle: str - solid|dotted|dashed|large-dashed|sparse-dotted (default: 'solid') - optional
    
    Args:
        lines_dict: Lines configuration dictionary
        valid_line_names: List of valid line names for this indicator (from IndicatorResult)
        
    Returns:
        Dictionary of validated line settings: {'line_name': {'visible': bool, 'color': str, 'lineWidth': int, 'lineStyle': int}, ...}
        
    Raises:
        ValueError: If unknown line name is specified
    """
    if not isinstance(lines_dict, dict):
        raise ValueError(f"lines must be a dictionary, got {type(lines_dict).__name__}")
    
    valid_names_set = set(valid_line_names)
    result = {}
    
    for line_name, line_settings in lines_dict.items():
        if not isinstance(line_settings, dict):
            raise ValueError(f"Line settings for '{line_name}' must be a dictionary, got {type(line_settings).__name__}")
        
        if line_name not in valid_names_set:
            raise ValueError(
                f"Unknown line name '{line_name}' for indicator. "
                f"Valid names: {', '.join(valid_line_names)}"
            )
        
        # Validate and apply defaults
        visible = line_settings.get('visible', True)
        if not isinstance(visible, bool):
            raise ValueError(f"Line 'visible' for '{line_name}' must be a boolean, got {type(visible).__name__}")
        
        color = line_settings.get('color')
        if color is not None:
            if not isinstance(color, str) or not re.match(r'^#[0-9A-Fa-f]{6}$', color):
                raise ValueError(f"Line 'color' for '{line_name}' must be a hex color string (e.g., '#FF5733'), got {color}")
        else:
            color = generate_random_color()
        
        line_width = line_settings.get('lineWidth', DEFAULT_LINE_WIDTH)
        if not isinstance(line_width, int) or not (1 <= line_width <= 10):
            raise ValueError(f"Line 'lineWidth' for '{line_name}' must be an integer 1-10, got {line_width}")
        
        line_style_str = line_settings.get('lineStyle', DEFAULT_LINE_STYLE)
        if not isinstance(line_style_str, str) or line_style_str.lower() not in LINE_STYLE_MAP:
            raise ValueError(
                f"Line 'lineStyle' for '{line_name}' must be one of {list(LINE_STYLE_MAP.keys())}, got {line_style_str}"
            )
        line_style = LINE_STYLE_MAP[line_style_str.lower()]
        
        result[line_name] = {
            'visible': visible,
            'color': color,
            'lineWidth': line_width,
            'lineStyle': line_style
        }
    
    return result




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
    
    values: ta.IndicatorResult  # Cached indicator values (IndicatorResult object)
    visible: bool = True  # Visibility flag for frontend display
    series_info: List[Dict[str, Any]]  # List of series descriptions: [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int, 'displayType': str, 'color_up': str|None, 'color_down': str|None}, ...]
    paneTitle: str  # Formatted title for pane display (e.g., "MACD(period_short=12,period_long=26,period_signal=9)")


class ta_proxy(ABC):
    """
    Abstract base class for technical analysis indicator proxy.
    Different implementations for different TA libraries (talib, ta, etc.)
    """
    
    def __init__(self, broker):
        """
        Initialize TA proxy.
        
        Args:
            broker: Reference to broker instance
        """
        self.broker = broker
        self.quotes_provider: Optional[QuotesProvider] = None
        self.cache = {}
        self._indicator_metadata = self._load_indicator_metadata()
    
    def set_quotes(self, quotes_provider: QuotesProvider) -> None:
        """
        Set or update quotes provider.
        
        Args:
            quotes_provider: QuotesProvider instance for accessing quotes data
        """
        self.quotes_provider = quotes_provider
        self.cache = {}
    
    @abstractmethod
    def _load_indicator_metadata(self) -> Dict[str, Any]:
        """
        Load indicator metadata from library.
        Must be implemented in subclasses.
        
        Returns:
            Dictionary of indicator metadata
        """
        pass
    
    def _get_output_series(self, name: str) -> List[Dict[str, str]]:
        """
        Get list of output series information for indicator.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'MACD')
            
        Returns:
            List of series dictionaries with 'name' and 'type' keys.
            Type can be: 'price', 'as source', or None/empty (value-based series).
            For backward compatibility, if series is a string, it's converted to dict with type='price'.
            
        Raises:
            R2D2IndicatorNotFoundError: If indicator is not found in metadata
        """
        if name not in self._indicator_metadata:
            raise R2D2IndicatorNotFoundError(f"Indicator '{name}' not found in metadata")
        
        indicator_info = self._indicator_metadata[name]
        
        # Check if 'output_series' exists in metadata (pyita format)
        if 'output_series' in indicator_info:
            output_series = indicator_info['output_series']
            # Convert to list of dicts if needed (handle both old and new formats)
            result = []
            for series in output_series:
                if isinstance(series, str):
                    # Old format: just string name, default to 'price'
                    result.append({'name': series, 'type': 'price'})
                elif isinstance(series, dict):
                    # New format: dict with 'name' and 'type'
                    # Type can be 'price', 'as source', or None/empty
                    result.append(series)
                else:
                    # Fallback
                    result.append({'name': str(series), 'type': 'price'})
            return result
        
        # Check if 'series' exists (talib format)
        if 'series' in indicator_info:
            series_list = indicator_info['series']
            result = []
            for s in series_list:
                if isinstance(s, str):
                    result.append({'name': s, 'type': 'price'})
                elif isinstance(s, dict):
                    # Convert 'is_price' to 'type'
                    is_price = s.get('is_price', True)
                    series_type = 'price' if is_price else None
                    entry = {'name': s.get('name', str(s)), 'type': series_type}
                    # Pass through display properties if present
                    if 'displayType' in s:
                        entry['displayType'] = s['displayType']
                    if 'color_up' in s:
                        entry['color_up'] = s['color_up']
                    if 'color_down' in s:
                        entry['color_down'] = s['color_down']
                    result.append(entry)
                else:
                    result.append({'name': str(s), 'type': 'price'})
            return result
        
        # Fallback: return indicator name as single series
        return [{'name': name, 'type': 'price'}]
    
    def _determine_is_price_for_series(
        self, 
        series_type: Optional[str], 
        indicator_name: str, 
        kwargs: dict
    ) -> bool:
        """
        Determine if series should be displayed on price chart.
        Default implementation. Override in subclasses if needed.
        
        Args:
            series_type: Type from metadata ('price', 'as_source', 'none', or None)
            indicator_name: Name of the indicator
            kwargs: Indicator parameters (may contain 'value' and other params)
            
        Returns:
            True if series should be on price chart, False otherwise
        """
        if series_type == 'price' or series_type == 'as_source':
            return True
        return False
    
    def _build_series_info(self, name: str, lines_config: Optional[Dict[str, Dict[str, Any]]] = None, kwargs: dict = None) -> List[Dict[str, Any]]:
        """
        Build series info from indicator metadata and lines configuration.
        
        Args:
            name: Indicator name
            lines_config: Optional lines configuration dictionary from kwargs (has priority)
                Format: {'line_name': {'visible': bool, 'color': str, 'lineWidth': int, 'lineStyle': str}, ...}
            kwargs: Indicator parameters (used to determine series type for 'as_source')
            
        Returns:
            List of series info dictionaries:
            [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int,
              'displayType': str, 'color_up': str|None, 'color_down': str|None}, ...]
            Only includes series with visible=True (or not specified in lines_config)
        """
        # Get output series information (list of dicts with 'name' and 'type')
        try:
            output_series = self._get_output_series(name)
        except R2D2IndicatorNotFoundError:
            # Indicator not found, use generic name
            output_series = [{'name': name, 'type': 'price'}]
        
        # Get valid line names from output_series
        valid_line_names = [s.get('name', f'series{i}') for i, s in enumerate(output_series)]
        
        # Parse lines configuration dictionary
        lines_settings = {}
        if lines_config:
            try:
                lines_settings = parse_lines_dict(lines_config, valid_line_names)
            except ValueError as e:
                error_msg = f"Invalid lines configuration for indicator '{name}': {e}"
                if self.broker:
                    self.broker.logging(error_msg, 'error')
                else:
                    logger.error(error_msg)
                # Continue with empty lines_settings (will use defaults)
        
        # Build series info list
        result = []
        for i, series_info in enumerate(output_series):
            # Extract name and type from series info
            series_name = series_info.get('name', f'series{i}')
            series_type = series_info.get('type')
            
            # Check if this series should be visible
            if series_name in lines_settings:
                if not lines_settings[series_name]['visible']:
                    # Skip this series if visible=False
                    continue
                line_setting = lines_settings[series_name]
            else:
                # Series not in lines_config - use defaults and visible=True
                # Check for hardcoded color in series_info, otherwise use generate_random_color()
                default_color = series_info.get('color')
                if not default_color:
                    default_color = generate_random_color()
                
                line_setting = {
                    'color': default_color,
                    'lineWidth': DEFAULT_LINE_WIDTH,
                    'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]
                }
            
            # Determine is_price using overridable method
            series_is_price = self._determine_is_price_for_series(series_type, name, kwargs or {})
            
            # Determine displayType from series metadata (default: 'line')
            display_type = series_info.get('displayType', 'line')
            
            entry = {
                'name': series_name,
                'is_price': series_is_price,
                'color': line_setting['color'],
                'lineWidth': line_setting['lineWidth'],
                'lineStyle': line_setting['lineStyle'],
                'displayType': display_type,
            }
            
            # Add histogram-specific color properties if present
            if 'color_up' in series_info:
                entry['color_up'] = series_info['color_up']
            if 'color_down' in series_info:
                entry['color_down'] = series_info['color_down']
            
            result.append(entry)
        
        return result
    
    def _format_pane_title(self, indicator_name: str, parameters: dict) -> str:
        """
        Format pane title for indicator display.
        
        Args:
            indicator_name: Indicator name (e.g., 'MACD', 'SMA')
            parameters: Indicator parameters dictionary
            
        Returns:
            Formatted title string (e.g., "MACD(period_short=12,period_long=26,period_signal=9)")
        """
        if not parameters:
            return indicator_name
        
        # Sort parameters by key for consistency
        sorted_params = sorted(parameters.items())
        
        # Format each parameter
        formatted_parts = []
        for key, value in sorted_params:
            if isinstance(value, str):
                formatted_parts.append(f"{key}='{value}'")
            elif isinstance(value, bool):
                formatted_parts.append(f"{key}={value}")
            elif value is None:
                formatted_parts.append(f"{key}=None")
            else:
                # Numbers and other types
                formatted_parts.append(f"{key}={value}")
        
        params_str = ",".join(formatted_parts)
        return f"{indicator_name}({params_str})"
    
    def _format_indicator_args(
        self, 
        name: str, 
        args: Optional[List[Any]] = None, 
        args_names: Optional[List[str]] = None,
        kwargs: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format indicator arguments for error messages.
        
        Args:
            name: Indicator name
            args: Positional arguments (for TA-Lib)
            args_names: Names for positional arguments (for TA-Lib, e.g., ['close', 'period'])
            kwargs: Keyword arguments
            
        Returns:
            Formatted string like "indicator_name(arg1, arg2, param1=value1, param2=value2)"
        """
        parts = []
        
        # Format positional arguments
        if args and args_names:
            # Use provided names for args
            for arg_name in args_names:
                parts.append(arg_name)
        elif args:
            # Fallback: format args directly
            for arg in args:
                parts.append(self._format_value(arg))
        
        # Format keyword arguments
        if kwargs:
            for key, value in sorted(kwargs.items()):
                # Skip internal parameters that are not part of the actual function call
                if key in ('lines',):
                    continue
                formatted_value = self._format_value(value)
                parts.append(f"{key}={formatted_value}")
        
        return f"{name}({', '.join(parts)})"
    
    def _format_value(self, value: Any, max_length: int = 50) -> str:
        """
        Format a single value for display in error messages.
        
        Args:
            value: Value to format
            max_length: Maximum length for string values
            
        Returns:
            Formatted string representation
        """
        if value is None:
            return "None"
        elif isinstance(value, bool):
            return str(value)
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            # Add quotes and truncate if too long
            if len(value) > max_length:
                return f"'{value[:max_length-3]}...'"
            return f"'{value}'"
        elif isinstance(value, (list, tuple)):
            # Format collections
            if len(value) == 0:
                return "[]" if isinstance(value, list) else "()"
            # For short collections, show elements
            if len(value) <= 3:
                items = [self._format_value(item, max_length) for item in value]
                if isinstance(value, tuple):
                    return f"({', '.join(items)})"
                return f"[{', '.join(items)}]"
            else:
                # For long collections, show first and last
                first = self._format_value(value[0], max_length)
                last = self._format_value(value[-1], max_length)
                return f"[{first}, ..., {last}]"
        elif isinstance(value, np.ndarray):
            # Format numpy arrays
            return f"array(shape={value.shape}, dtype={value.dtype})"
        elif hasattr(value, '__class__'):
            # For other objects, show class name
            class_name = value.__class__.__name__
            # Special handling for Quotes objects
            if class_name == 'Quotes':
                return "quotes_data"
            return f"{class_name}()"
        else:
            # Fallback: convert to string and truncate
            str_value = str(value)
            if len(str_value) > max_length:
                return f"{str_value[:max_length-3]}..."
            return str_value
    
    @abstractmethod
    def calc_indicator(self, name: str, quotes: ta.Quotes, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values for entire dataset.
        Must be implemented in subclasses for specific TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            quotes: Quotes data to calculate indicator on
            **kwargs: Indicator parameters
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
        """
        pass
    
    def get_indicator(self, name: str, **kwargs) -> ta.IndicatorResult:
        """
        Get indicator values with caching and slicing to current bar.
        Common implementation for all TA libraries.
        
        Supports optional 'symbol' and 'timeframe' kwargs to calculate
        indicator on a different symbol/timeframe than the primary one.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters. Special keys:
                - symbol: Trading symbol (e.g., 'ETH/USDT:USDT'). Default: primary symbol.
                - timeframe: Timeframe string (e.g., '1h', '15m'). Default: primary timeframe.
                    Must be >= primary timeframe.
                - lines: Line styling config (only for primary symbol/timeframe indicators).
                - visible: bool - If False, indicator will not be displayed on chart (default: True for primary indicators, False for cross-timeframe/cross-symbol).
            
        Returns:
            IndicatorResult object with indicator values sliced to current bar
        """
        lines_config = kwargs.pop('lines', None)
        req_symbol = kwargs.pop('symbol', None)
        req_timeframe = kwargs.pop('timeframe', None)
        visible_override = kwargs.pop('visible', None)
        
        is_custom = req_symbol is not None or req_timeframe is not None
        
        if is_custom:
            actual_symbol = req_symbol or self.broker.symbol
            actual_tf = Timeframe.cast(req_timeframe) if req_timeframe else self.quotes_provider.primary_timeframe
            
            if actual_tf < self.quotes_provider.primary_timeframe:
                raise ValueError(
                    f"Requested timeframe '{req_timeframe}' is lower than "
                    f"primary timeframe '{self.quotes_provider.primary_timeframe}'. "
                    f"Only higher or equal timeframes are supported."
                )
            
            quotes_for_calc = self.quotes_provider.get_quotes(actual_symbol, actual_tf)
        else:
            actual_symbol = self.broker.symbol
            actual_tf = self.quotes_provider.primary_timeframe
            quotes_for_calc = self.quotes_provider.primary
        
        cache_key = (name, actual_symbol, actual_tf, tuple(sorted(kwargs.items())))
        
        if cache_key not in self.cache:
            indicator_result = self.calc_indicator(name, quotes_for_calc, **kwargs)
            
            if is_custom:
                series_info = []
                pane_title = ''
            else:
                series_info = self._build_series_info(name, lines_config, kwargs)
                pane_title = self._format_pane_title(name, kwargs)
            
            # Determine visibility: use explicit override if provided, otherwise use default logic
            if visible_override is not None:
                indicator_visible = visible_override
            else:
                indicator_visible = not is_custom
            
            self.cache[cache_key] = UsedIndicatorDescription(
                values=indicator_result,
                visible=indicator_visible,
                series_info=series_info,
                paneTitle=pane_title
            )
        
        indicator_desc = self.cache[cache_key]
        full_result = indicator_desc.values
        
        if is_custom:
            slice_size = self.quotes_provider.get_slice_size(
                quotes_for_calc, actual_tf, self.broker.current_time
            )
            sliced_result = full_result[:slice_size]
        else:
            sliced_result = full_result[:self.broker.i_time + 1]
        
        return sliced_result
    
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
    # Format: {'is_price': bool, 'series': Optional[List[Dict]]}
    # If 'series' is provided, uses those names. If not, generates generic names (series0, series1, ...)
    # Each series can override 'is_price' by including it in its dict
    # Lines configuration is passed via kwargs['lines'] with format:
    #   {'line_name': {'visible': bool, 'color': str, 'lineWidth': int, 'lineStyle': str}, ...}
    #   - visible: bool (default: True if not specified)
    #   - color: hex string (e.g., '#FF5733') - optional, uses generate_random_color() if not specified
    #   - lineWidth: int 1-10 (default: 2) - optional
    #   - lineStyle: str - solid|dotted|dashed|large-dashed|sparse-dotted (default: 'solid') - optional
    # Line names must match those in IndicatorResult (e.g., 'macd', 'macdsignal', 'macdhist' for MACD)
    # Names are taken from TA-Lib documentation (Outputs section)
    INDICATOR_SERIES_NAMES = {
        # Multi-series indicators
        'MACD': {
            'is_price': False,
            'series': [
                {'name': 'macd'},
                {'name': 'macdsignal'},
                {'name': 'macdhist', 'displayType': 'histogram', 'color_up': '#26a69a', 'color_down': '#ef5350'},
            ],
        },
        'BBANDS': {
            'is_price': True,
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

    def __init__(self, broker):
        """
        Initialize TA-Lib proxy.
        Analyzes talib functions and builds indicator descriptions.
        
        Args:
            broker: Reference to broker instance
        """
        super().__init__(broker)
        
        # Dictionary to store indicator descriptions
        self._indicator_descriptions: Dict[str, IndicatorDescription] = {}
        
        # Analyze talib functions
        self._analyze_talib_functions()
    
    def _load_indicator_metadata(self) -> Dict[str, Any]:
        """
        Load indicator metadata from INDICATOR_SERIES_NAMES.
        
        Returns:
            Dictionary of indicator metadata
        """
        # Return a copy of INDICATOR_SERIES_NAMES
        return dict(self.INDICATOR_SERIES_NAMES)
    
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
    
    def calc_indicator(self, name: str, quotes: ta.Quotes, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values using TA-Lib.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            quotes: Quotes data to calculate indicator on
            **kwargs: Indicator parameters (non-positional)
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
            
        Raises:
            R2D2IndicatorNotFoundError: If indicator name is not found in descriptions
        """
        if name not in self._indicator_descriptions:
            raise R2D2IndicatorNotFoundError(f"TA-Lib indicator '{name}' is not available or has invalid parameters")
        
        description = self._indicator_descriptions[name]
        
        talib_function = getattr(talib, name)
        
        args = []
        args_names = []
        call_kwargs = kwargs.copy()
        
        for param_name in description.values:
            if param_name == 'real':
                if 'value' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real' (series name), "
                        f"but 'value' parameter is not provided in kwargs"
                    )
                series_name = kwargs['value']
                call_kwargs.pop('value', None)
                try:
                    args.append(quotes[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value' parameter, but it's not available in quotes data"
                    )
            elif param_name == 'real0':
                if 'value0' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real0' (series name), "
                        f"but 'value0' parameter is not provided in kwargs"
                    )
                series_name = kwargs['value0']
                call_kwargs.pop('value0', None)
                try:
                    args.append(quotes[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value0' parameter, but it's not available in quotes data"
                    )
            elif param_name == 'real1':
                if 'value1' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'real1' (series name), "
                        f"but 'value1' parameter is not provided in kwargs"
                    )
                series_name = kwargs['value1']
                call_kwargs.pop('value1', None)
                try:
                    args.append(quotes[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value1' parameter, but it's not available in quotes data"
                    )
            elif param_name == 'periods':
                if 'periods' not in kwargs:
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter 'periods', "
                        f"but 'periods' parameter is not provided in kwargs"
                    )
                periods_value = kwargs['periods']
                call_kwargs.pop('periods', None)
                args.append(periods_value)
                args_names.append(str(periods_value))
            else:
                try:
                    args.append(quotes[param_name])
                    args_names.append(param_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter '{param_name}', "
                        f"but it's not available in quotes data"
                    )
        
        try:
            # Call talib function with *args and **kwargs (without 'value')
            talib_result = talib_function(*args, **call_kwargs)
        except Exception as e:
            # Re-raise with more context
            formatted_args = self._format_indicator_args(name, args=args, args_names=args_names, kwargs=call_kwargs)
            raise RuntimeError(f"Error calling talib.{formatted_args}: {e}") from e
        
        # Get output series information
        try:
            output_series_info = self._get_output_series(name)
        except R2D2IndicatorNotFoundError:
            # Fallback to generic names
            if isinstance(talib_result, tuple):
                output_series_info = [{'name': f'series{i}', 'type': 'price'} for i in range(len(talib_result))]
            else:
                output_series_info = [{'name': name, 'type': 'price'}]
        
        # Extract series names from output_series_info
        output_series_names = [s['name'] for s in output_series_info]
        
        # Wrap result in IndicatorResult
        result_dict = {}
        if isinstance(talib_result, tuple):
            # Multiple series
            for i, (series_name, series_data) in enumerate(zip(output_series_names, talib_result)):
                result_dict[series_name] = series_data
        else:
            # Single series
            result_dict[output_series_names[0]] = talib_result
        
        # Create and return IndicatorResult
        return ta.IndicatorResult(result_dict)


class ta_proxy_pyita(ta_proxy):
    """
    Technical analysis proxy for pyita library.
    """
    
    def _determine_is_price_for_series(
        self, 
        series_type: Optional[str], 
        indicator_name: str, 
        kwargs: dict
    ) -> bool:
        """
        Determine if series should be displayed on price chart for pyita indicators.
        For 'as_source' type, analyzes the 'value' parameter.
        """
        if series_type == 'price':
            return True
        elif series_type == 'as_source':
            # Check value parameter to determine if it's price-based
            value = kwargs.get('value', 'close')
            if isinstance(value, str):
                return value.lower() in ['open', 'high', 'low', 'close']
            return True  # Default to price if value is not a string
        return False
    
    def _load_indicator_metadata(self) -> Dict[str, Any]:
        """
        Load indicator metadata from pyita library.
        
        Returns:
            Dictionary of indicator metadata from pyita.metadata()
        """
        metadata = ta.metadata()
        
        # Merge with our custom metadata (for backwards compatibility)
        for indicator_name, custom_info in self.INDICATOR_SERIES_NAMES.items():
            if indicator_name in metadata:
                # Merge custom info into metadata
                metadata[indicator_name].update(custom_info)
            else:
                # Add custom info as-is
                metadata[indicator_name] = custom_info
        
        return metadata
    
    # Dictionary with custom visualization settings for pyita indicators
    # Only contains indicators that need custom line styling (colors, widths, styles)
    # All other metadata (names, types) is retrieved from pyita.metadata()
    # Lines configuration is passed via kwargs['lines'] with format:
    #   {'line_name': {'visible': bool, 'color': str, 'lineWidth': int, 'lineStyle': str}, ...}
    INDICATOR_SERIES_NAMES = {
        # MACD - histogram for hist series
        'macd': {
            'output_series': [
                {'name': 'macd', 'type': 'none'},
                {'name': 'signal', 'type': 'none'},
                {'name': 'hist', 'type': 'none', 'displayType': 'histogram', 'color_up': '#26a69a', 'color_down': '#ef5350'},
            ]
        },
    }
    
    def __init__(self, broker):
        """
        Initialize pyita proxy.
        
        Args:
            broker: Reference to broker instance
        """
        super().__init__(broker)
    
    def calc_indicator(self, name: str, quotes: ta.Quotes, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values using pyita.
        
        Args:
            name: Indicator name (e.g., 'sma', 'ema', 'rsi')
            quotes: Quotes data to calculate indicator on
            **kwargs: Indicator parameters
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
            
        Raises:
            R2D2IndicatorNotFoundError: If indicator name is not found
        """
        if name.lower() not in self._indicator_metadata:
            raise R2D2IndicatorNotFoundError(f"pyita indicator '{name}' is not available")
        
        try:
            indicator_func = getattr(ta, name.lower())
        except AttributeError:
            raise R2D2IndicatorNotFoundError(f"pyita indicator '{name}' is not available")
        
        try:
            result = indicator_func(quotes, **kwargs)
        except Exception as e:
            formatted_args = self._format_indicator_args(name, kwargs=kwargs)
            raise RuntimeError(f"Error calling pyita.{formatted_args}: {e}") from e
        
        return result


class QuotesProxy:
    """
    Proxy that provides access to quotes for different symbols and timeframes.
    Used as self.quotes in strategies.
    
    Usage:
        self.quotes()                                    # primary quotes
        self.quotes(timeframe='1h')                      # higher TF, same symbol
        self.quotes(symbol='ETH/USDT:USDT')              # different symbol, same TF
        self.quotes(symbol='ETH/USDT:USDT', timeframe='1h')  # different symbol and TF
    """
    
    def __init__(self, broker):
        self.broker = broker
        self.quotes_provider: Optional[QuotesProvider] = None
    
    def set_quotes(self, quotes_provider: QuotesProvider):
        self.quotes_provider = quotes_provider
    
    def __call__(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> ta.Quotes:
        """
        Return sliced quotes for the requested symbol/timeframe.
        
        Args:
            symbol: Trading symbol (e.g., 'ETH/USDT:USDT'). Default: primary symbol.
            timeframe: Timeframe string (e.g., '1h', '1d'). Must be >= primary TF.
            
        Returns:
            ta.Quotes sliced to current bar (closed bars only for higher TFs)
        """
        if symbol is None and timeframe is None:
            return self.quotes_provider.primary[:self.broker.i_time]
        
        actual_symbol = symbol or self.broker.symbol
        actual_tf = Timeframe.cast(timeframe) if timeframe else self.quotes_provider.primary_timeframe
        
        if actual_tf < self.quotes_provider.primary_timeframe:
            raise ValueError(
                f"Requested timeframe '{timeframe}' is lower than "
                f"primary timeframe '{self.quotes_provider.primary_timeframe}'. "
                f"Only higher or equal timeframes are supported."
            )
        
        quotes = self.quotes_provider.get_quotes(actual_symbol, actual_tf)
        slice_size = self.quotes_provider.get_slice_size(
            quotes, actual_tf, self.broker.current_time
        )
        return quotes[:slice_size]

