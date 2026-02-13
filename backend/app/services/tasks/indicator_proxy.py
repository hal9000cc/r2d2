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
    
    values: ta.IndicatorResult  # Cached indicator values (IndicatorResult object)
    visible: bool = True  # Visibility flag for frontend display
    series_info: List[Dict[str, Any]]  # List of series descriptions: [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int}, ...]


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
        self.quotes_data: Optional[ta.Quotes] = None
        self.cache = {}
        self._indicator_metadata = self._load_indicator_metadata()
    
    def set_quotes(self, quotes_data: ta.Quotes) -> None:
        """
        Set or update quotes data.
        
        Args:
            quotes_data: Quotes object with OHLCV data
        """
        self.quotes_data = quotes_data
        # Clear cache when quotes are updated
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
                    result.append({'name': s.get('name', str(s)), 'type': series_type})
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
    
    def _build_series_info(self, name: str, lines_config: Optional[str] = None, kwargs: dict = None) -> List[Dict[str, Any]]:
        """
        Build series info from indicator metadata and lines configuration.
        
        Args:
            name: Indicator name
            lines_config: Optional lines configuration string from kwargs (has priority)
            kwargs: Indicator parameters (used to determine series type for 'as_source')
            
        Returns:
            List of series info dictionaries: [{'name': str, 'is_price': bool, 'color': str, 'lineWidth': int, 'lineStyle': int}, ...]
        """
        # Get output series information (list of dicts with 'name' and 'type')
        try:
            output_series = self._get_output_series(name)
        except R2D2IndicatorNotFoundError:
            # Indicator not found, use generic name
            output_series = [{'name': name, 'type': 'price'}]
        
        # Get metadata for indicator
        indicator_info = self._indicator_metadata.get(name, {})
        
        # Parse lines configuration
        lines_settings = None
        all_parse_errors = []
        
        # Priority: lines_config (from kwargs) > indicator description > defaults
        if lines_config:
            lines_settings, parse_errors = parse_lines_config(lines_config)
            all_parse_errors.extend(parse_errors)
        elif 'lines' in indicator_info:
            lines_settings, parse_errors = parse_lines_config(indicator_info['lines'])
            all_parse_errors.extend(parse_errors)
        
        # If no lines settings, use defaults
        if not lines_settings:
            default_line = {'color': generate_random_color(), 'lineWidth': DEFAULT_LINE_WIDTH, 'lineStyle': LINE_STYLE_MAP[DEFAULT_LINE_STYLE]}
            lines_settings = [default_line]
        
        # Send parse errors to frontend if broker is available
        if all_parse_errors and self.broker:
            for error_msg in all_parse_errors:
                self.broker.logging(f"Indicator '{name}': {error_msg}", 'error')
        
        # Build series info list
        result = []
        for i, series_info in enumerate(output_series):
            # Extract name and type from series info
            series_name = series_info.get('name', f'series{i}')
            series_type = series_info.get('type')
            
            # Determine is_price using overridable method
            series_is_price = self._determine_is_price_for_series(series_type, name, kwargs or {})
            
            # Get line settings cyclically
            line_setting = lines_settings[i % len(lines_settings)]
            
            result.append({
                'name': series_name,
                'is_price': series_is_price,
                'color': line_setting['color'],
                'lineWidth': line_setting['lineWidth'],
                'lineStyle': line_setting['lineStyle']
            })
        
        return result
    
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
    def calc_indicator(self, name: str, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values for entire dataset.
        Must be implemented in subclasses for specific TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
        """
        pass
    
    def get_indicator(self, name: str, **kwargs) -> ta.IndicatorResult:
        """
        Get indicator values with caching and slicing to current bar.
        Common implementation for all TA libraries.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters (may include 'lines' for line styling)
            
        Returns:
            IndicatorResult object with indicator values sliced to current bar
        """
        # Extract lines config from kwargs (if present)
        lines_config = kwargs.pop('lines', None)
        
        # Create cache key from name and sorted parameters (without lines, as it doesn't affect values)
        cache_key = (name, tuple(sorted(kwargs.items())))
        
        # Check cache
        if cache_key not in self.cache:
            # Calculate indicator for entire dataset (returns IndicatorResult)
            indicator_result = self.calc_indicator(name, **kwargs)
            
            # Build series info from metadata (pass kwargs for 'as_source' type determination)
            series_info = self._build_series_info(name, lines_config, kwargs)
            
            # Store in cache as UsedIndicatorDescription
            self.cache[cache_key] = UsedIndicatorDescription(
                values=indicator_result,
                visible=True,
                series_info=series_info
            )
        
        # Get cached indicator description
        indicator_desc = self.cache[cache_key]
        full_result = indicator_desc.values
        
        # Slice IndicatorResult to current bar
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
    
    def calc_indicator(self, name: str, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values using TA-Lib.
        
        Args:
            name: Indicator name (e.g., 'SMA', 'EMA', 'RSI')
            **kwargs: Indicator parameters (non-positional)
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
            
        Raises:
            PyTAExceptionIndicatorNotFound: If indicator name is not found in descriptions
        """
        # Get indicator description
        if name not in self._indicator_descriptions:
            raise R2D2IndicatorNotFoundError(f"TA-Lib indicator '{name}' is not available or has invalid parameters")
        
        description = self._indicator_descriptions[name]
        
        # Get function from talib
        talib_function = getattr(talib, name)
        
        # Build positional arguments from quotes_data
        args = []
        args_names = []  # Names for positional arguments (for error formatting)
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
                try:
                    args.append(self.quotes_data[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value' parameter, but it's not available in quotes_data"
                    )
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
                try:
                    args.append(self.quotes_data[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value0' parameter, but it's not available in quotes_data"
                    )
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
                try:
                    args.append(self.quotes_data[series_name])
                    args_names.append(series_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires series '{series_name}' "
                        f"from 'value1' parameter, but it's not available in quotes_data"
                    )
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
                args_names.append(str(periods_value))  # Show as number in error message
            else:
                # Regular parameter - get directly from quotes_data
                try:
                    args.append(self.quotes_data[param_name])
                    args_names.append(param_name)
                except (KeyError, AttributeError):
                    raise ValueError(
                        f"TA-Lib indicator '{name}' requires parameter '{param_name}', "
                        f"but it's not available in quotes_data"
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
    # Lines priority: kwargs.lines > indicator.lines > defaults
    INDICATOR_SERIES_NAMES = {
        # Bollinger Bands - custom colors for upper/middle/lower bands
        'bollinger_bands': {
            'lines': '#006666;2;solid|#B0B0B0;2;solid|#006666;2;solid'
        },
    }
    
    def __init__(self, broker):
        """
        Initialize pyita proxy.
        
        Args:
            broker: Reference to broker instance
        """
        super().__init__(broker)
    
    def calc_indicator(self, name: str, **kwargs) -> ta.IndicatorResult:
        """
        Calculate indicator values using pyita.
        
        Args:
            name: Indicator name (e.g., 'sma', 'ema', 'rsi')
            **kwargs: Indicator parameters
            
        Returns:
            IndicatorResult object with indicator values for entire dataset
            
        Raises:
            PyTAExceptionIndicatorNotFound: If indicator name is not found
        """
        # Check if indicator exists in metadata
        if name.lower() not in self._indicator_metadata:
            raise R2D2IndicatorNotFoundError(f"pyita indicator '{name}' is not available")
        
        # Get indicator function via getattr
        try:
            indicator_func = getattr(ta, name.lower())
        except AttributeError:
            raise R2D2IndicatorNotFoundError(f"pyita indicator '{name}' is not available")
        
        # Call indicator (quotes_data is already a Quotes object)
        try:
            result = indicator_func(self.quotes_data, **kwargs)
        except Exception as e:
            formatted_args = self._format_indicator_args(name, kwargs=kwargs)
            raise RuntimeError(f"Error calling pyita.{formatted_args}: {e}") from e
        
        # Return IndicatorResult as is
        return result

