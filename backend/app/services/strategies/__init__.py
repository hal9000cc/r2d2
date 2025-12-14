"""
Strategies service module
"""

from typing import List, Tuple, Dict, Optional, Any
from pathlib import Path
import re
import importlib.util
import sys
from pydantic import BaseModel
from app.core.config import STRATEGIES_DIR
from app.services.strategies.exceptions import (
    StrategyNameError,
    StrategyNotFoundError,
    StrategySyntaxError,
    StrategyFileError
)


class ParameterDescription(BaseModel):
    """
    Parameter description with default value, type and description
    """
    default_value: Any  # Default value for the parameter
    type: str  # Type name as string (e.g., "int", "float", "str")
    description: str


class StrategyModel(BaseModel):
    """
    Strategy model with name, text, parameters description, loading errors and filename
    """
    name: str
    text: str
    filename: str = ""  # Full path or filename of the strategy file
    parameters_description: Optional[Dict[str, ParameterDescription]] = None
    loading_errors: List[str] = []


class StrategySaveResponse(BaseModel):
    """
    Response model for strategy save operation
    """
    success: bool
    message: str
    syntax_errors: List[str] = []
    loading_errors: List[str] = []


def validate_strategy_name(name: str) -> None:
    """
    Validate strategy name for file system safety
    
    Args:
        name: Strategy name to validate
        
    Raises:
        StrategyNameError: If name is invalid
    """
    if not name:
        raise StrategyNameError("Strategy name cannot be empty")
    
    # Check for invalid characters
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    if re.search(invalid_chars, name):
        raise StrategyNameError(
            "Strategy name contains invalid characters. Allowed: letters, numbers, spaces, hyphens, underscores"
        )
    
    # Check for reserved names (Windows)
    reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 
                      'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 
                      'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
    if name.upper() in reserved_names:
        raise StrategyNameError(f"Strategy name '{name}' is reserved")
    
    # Check for dots at the end (Windows issue)
    if name.endswith('.'):
        raise StrategyNameError("Strategy name cannot end with a dot")
    
    # Check for spaces at the end
    if name.endswith(' '):
        raise StrategyNameError("Strategy name cannot end with a space")


def validate_strategy_file_path(file_path: str) -> None:
    """
    Validate strategy file path for security and correctness
    
    Args:
        file_path: Absolute file path (without .py extension)
        
    Raises:
        StrategyFileError: If path is invalid
    """
    if not file_path:
        raise StrategyFileError("File path cannot be empty")
    
    # Normalize path separators to forward slashes for processing
    normalized_path = file_path.replace('\\', '/')
    
    # Check for path traversal attempts (..)
    if '..' in normalized_path:
        raise StrategyFileError(
            "File path cannot contain '..'. Path traversal is not allowed for security reasons."
        )
    
    # Check that path is within STRATEGIES_DIR
    try:
        # Convert to Path object and resolve
        path_obj = Path(file_path)
        if not path_obj.is_absolute():
            raise StrategyFileError(
                f"File path must be absolute. Received: '{file_path}'"
            )
        
        resolved_path = path_obj.resolve()
        strategies_dir_resolved = STRATEGIES_DIR.resolve()
        
        # Check that resolved path is within STRATEGIES_DIR
        try:
            resolved_path.relative_to(strategies_dir_resolved)
        except ValueError:
            raise StrategyFileError(
                f"File path must be within strategies directory '{STRATEGIES_DIR}'. "
                f"Received path resolves to: '{resolved_path}'"
            )
    except (OSError, ValueError) as e:
        raise StrategyFileError(f"Invalid file path: {str(e)}")
    
    # Extract relative path from STRATEGIES_DIR for segment validation
    try:
        relative_path = resolved_path.relative_to(strategies_dir_resolved)
        path_str = str(relative_path).replace('\\', '/')
    except ValueError:
        # Should not happen after the check above, but just in case
        raise StrategyFileError("Failed to validate file path structure")
    
    # Remove .py extension if present for validation
    if path_str.endswith('.py'):
        path_str = path_str[:-3]
    
    # Split into segments
    segments = [s for s in path_str.split('/') if s]
    if not segments:
        raise StrategyFileError("File path must contain at least one non-empty segment")
    
    # Validate each segment (directory and filename)
    for segment in segments:
        # Check for invalid characters in segment
        invalid_chars = r'[<>:"|?*\x00-\x1f]'
        if re.search(invalid_chars, segment):
            raise StrategyFileError(
                f"File path segment '{segment}' contains invalid characters. "
                "Allowed: letters, numbers, spaces, hyphens, underscores, dots, forward slashes"
            )
        
        # Check for reserved names (Windows) in segment
        reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 
                          'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 
                          'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
        if segment.upper() in reserved_names:
            raise StrategyFileError(f"File path segment '{segment}' is a reserved name")
        
        # Check for dots/spaces at the end (Windows issue)
        if segment.endswith('.') or segment.endswith(' '):
            raise StrategyFileError(f"File path segment '{segment}' cannot end with a dot or space")
    
    # Validate filename (last segment)
    filename = segments[-1]
    if not filename:
        raise StrategyFileError("File path must end with a valid filename")


def validate_python_syntax(text: str) -> List[str]:
    """
    Validate Python syntax of strategy text
    
    Args:
        text: Python code to validate
        
    Returns:
        List of error messages (empty if no errors)
    """
    errors = []
    
    if not text.strip():
        return errors  # Empty text is valid
    
    try:
        compile(text, '<string>', 'exec')
    except SyntaxError as e:
        error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
        if e.text:
            error_msg += f"\n  {e.text.rstrip()}"
            if e.offset:
                error_msg += f"\n  {' ' * (e.offset - 1)}^"
        errors.append(error_msg)
    except Exception as e:
        errors.append(f"Error validating Python syntax: {str(e)}")
    
    return errors


def create_strategy(name: str, file_path: Optional[str] = None) -> Tuple[str, str]:
    """
    Create a new strategy file with given name or path
    
    Args:
        name: Strategy name (used for class name and as fallback filename)
        file_path: Optional file path relative to STRATEGIES_DIR (without .py extension).
                   If provided, this path will be used instead of name.
        
    Returns:
        Tuple of (name, text) - strategy name and empty text
        
    Raises:
        StrategyNameError: If name is invalid
        StrategyFileError: If file already exists or creation fails
    """
    # Validate strategy name (for class name)
    validate_strategy_name(name)
    
    # Use provided file_path or construct from name
    if file_path:
        # Validate the absolute file path
        validate_strategy_file_path(file_path)
        
        # Convert to Path and add .py extension
        target_path = Path(file_path)
        if not target_path.suffix:
            target_path = target_path.with_suffix('.py')
        elif target_path.suffix != '.py':
            raise StrategyFileError(f"File path must have .py extension or no extension. Got: '{target_path.suffix}'")
        
        # Ensure parent directories exist
        target_path.parent.mkdir(parents=True, exist_ok=True)
        strategy_file_path = target_path.resolve()
        
        # Use absolute path as strategy identifier (without .py extension)
        strategy_identifier = str(strategy_file_path)
        if strategy_identifier.endswith('.py'):
            strategy_identifier = strategy_identifier[:-3]
        # Normalize to forward slashes
        strategy_identifier = strategy_identifier.replace('\\', '/')
    else:
        strategy_file_path = STRATEGIES_DIR / f"{name}.py"
        strategy_file_path = strategy_file_path.resolve()
        # Use absolute path as strategy identifier
        strategy_identifier = str(strategy_file_path)
        if strategy_identifier.endswith('.py'):
            strategy_identifier = strategy_identifier[:-3]
        strategy_identifier = strategy_identifier.replace('\\', '/')
    
    if strategy_file_path.exists():
        raise StrategyFileError(f"Strategy file already exists: {strategy_file_path}")
    
    # Get template content
    template_file = Path(__file__).parent / 'strategy_template.py'
    template_text = template_file.read_text(encoding='utf-8')
    
    # Replace class name in template with strategy name
    # Convert name to PascalCase for class name
    class_name = ''.join(word.capitalize() for word in name.replace('_', ' ').replace('-', ' ').split())
    if not class_name:
        class_name = "MyStrategy"  # Fallback if name is empty after processing
    
    # Replace MovingAverageCrossoverStrategy with the new class name
    template_text = template_text.replace("MyStrategy", class_name)
    
    try:
        strategy_file_path.write_text(template_text, encoding='utf-8')
    except Exception as e:
        raise StrategyFileError(f"Failed to create strategy file: {str(e)}")
    
    # Return strategy identifier (file path without extension) and text
    return (strategy_identifier, template_text)


def save_strategy(name: str, text: str) -> List[str]:
    """
    Save strategy to file
    
    Args:
        name: Strategy name (relative path from STRATEGIES_DIR without .py extension)
        text: Strategy Python code
        
    Returns:
        List of syntax errors (empty if no errors)
        
    Raises:
        StrategyNameError: If name is invalid
        StrategyFileError: If save fails
    """
    validate_strategy_name(name)
    
    # Validate Python syntax (but don't fail, just collect errors)
    syntax_errors = validate_python_syntax(text)
    
    # Save file regardless of syntax errors
    file_path = STRATEGIES_DIR / f"{name}.py"
    try:
        file_path.write_text(text, encoding='utf-8')
    except Exception as e:
        raise StrategyFileError(f"Failed to save strategy file: {str(e)}")
    
    return syntax_errors


def load_strategy(name: str) -> Tuple[str, str, str]:
    """
    Load strategy from file by name or path

    Args:
        name: Strategy name or path (filename without .py extension, can include subdirectories)

    Returns:
        Tuple of (name, text, filename) - strategy identifier, code, and full filename path

    Raises:
        StrategyNameError: If name is invalid
        StrategyNotFoundError: If strategy file not found
        StrategyFileError: If read fails
    """
    # Validate only the filename part (last segment) for paths
    # Extract filename from path if it contains slashes
    if '/' in name or '\\' in name:
        # For paths, validate only the filename part
        filename = name.split('/')[-1].split('\\')[-1]
        validate_strategy_name(filename)
    else:
        validate_strategy_name(name)

    # Support both simple name and path (e.g., "path/to/strategy")
    file_path = STRATEGIES_DIR / f"{name}.py"
    
    # Security check: ensure path is within STRATEGIES_DIR
    try:
        file_path_resolved = file_path.resolve()
        strategies_dir_resolved = STRATEGIES_DIR.resolve()
        if not str(file_path_resolved).startswith(str(strategies_dir_resolved)):
            raise StrategyNotFoundError(f"Strategy '{name}' not found")
    except (OSError, ValueError):
        raise StrategyNotFoundError(f"Strategy '{name}' not found")
    
    if not file_path.exists():
        raise StrategyNotFoundError(f"Strategy '{name}' not found")

    try:
        text = file_path.read_text(encoding='utf-8')
    except Exception as e:
        raise StrategyFileError(f"Failed to read strategy file: {str(e)}")

    return (name, text, str(file_path))


def get_strategy_parameters_description(name: str, text: str) -> Tuple[Optional[Dict[str, Tuple[Any, str, str]]], List[str]]:
    """
    Get parameters description from strategy class by dynamically loading it
    
    Args:
        name: Strategy name
        text: Strategy Python code
        
    Returns:
        Tuple of (parameters_dict, errors_list):
        - parameters_dict: Dictionary where keys are parameter names and values are tuples of (default_value, type_name, description),
          or None if cannot be loaded. Type is determined automatically from default_value.
          For example:
          {
              'fast_ma': (10, 'int', 'Fast moving average period'),
              'slow_ma': (20, 'int', 'Slow moving average period')
          }
        - errors_list: List of error messages (empty if no errors)
    """
    errors = []
    
    try:
        # Create a temporary module name
        module_name = f"strategy_{name}"
        
        # Remove module from cache if it exists
        if module_name in sys.modules:
            del sys.modules[module_name]
        
        # Compile and load the module
        spec = importlib.util.spec_from_loader(module_name, loader=None)
        if spec is None:
            errors.append("Failed to create module spec")
            return None, errors
        
        try:
            module = importlib.util.module_from_spec(spec)
            exec(text, module.__dict__)
            sys.modules[module_name] = module
        except SyntaxError as e:
            error_msg = f"Syntax error in strategy code: {e.msg}"
            if e.lineno:
                error_msg += f" at line {e.lineno}"
            errors.append(error_msg)
            return None, errors
        except Exception as e:
            errors.append(f"Failed to load strategy module: {str(e)}")
            return None, errors
        
        # Find the strategy class (should inherit from StrategyBacktest)
        from app.services.tasks.strategy import StrategyBacktest
        
        strategy_class = None
        for attr_name in dir(module):
            try:
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, StrategyBacktest) and 
                    attr != StrategyBacktest):
                    strategy_class = attr
                    break
            except Exception:
                continue
        
        if strategy_class is None:
            errors.append("Strategy class not found: no class inheriting from StrategyBacktest found in the code")
            return None, errors
        
        # Get parameters description
        try:
            params_dict = strategy_class.get_parameters_description()
            if not isinstance(params_dict, dict):
                errors.append("get_parameters_description() did not return a dictionary")
                return None, errors
            
            # Convert to simple format: Dict[str, Tuple[Any, str, str]]
            # Type is determined automatically from default_value
            result = {}
            for param_name, (default_value, param_desc) in params_dict.items():
                # Determine type from default_value
                if default_value is None:
                    type_name = 'str'  # Default to str if None
                elif isinstance(default_value, bool):
                    type_name = 'bool'
                elif isinstance(default_value, int):
                    type_name = 'int'
                elif isinstance(default_value, float):
                    type_name = 'float'
                elif isinstance(default_value, str):
                    type_name = 'str'
                else:
                    type_name = type(default_value).__name__
                
                result[param_name] = (default_value, type_name, param_desc)
            
            return result, errors
        except NotImplementedError:
            errors.append("Strategy class does not implement get_parameters_description() method")
            return None, errors
        except Exception as e:
            errors.append(f"Failed to get parameters description: {str(e)}")
            return None, errors
        
    except Exception as e:
        errors.append(f"Unexpected error while loading strategy: {str(e)}")
        return None, errors

