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
    Strategy model with name, file path, text, parameters description and loading errors
    """
    name: str  # Strategy name (can be arbitrary, not necessarily related to file path)
    file_path: str  # Relative path to strategy file (from STRATEGIES_DIR, with .py extension)
    text: str
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


def validate_relative_path(relative_path: str) -> None:
    """
    Validate relative strategy file path for security and correctness.
    This function validates that the relative path stays within STRATEGIES_DIR.
    
    Args:
        relative_path: Relative file path from STRATEGIES_DIR
        
    Raises:
        StrategyFileError: If path is invalid or would escape STRATEGIES_DIR
    """
    if not relative_path:
        raise StrategyFileError("File path cannot be empty")
    
    # Normalize path separators to forward slashes for processing
    normalized_path = relative_path.replace('\\', '/')
    
    # Remove leading/trailing slashes
    normalized_path = normalized_path.strip('/')
    
    # Check that path ends with .py extension
    if not normalized_path.endswith('.py'):
        raise StrategyFileError(
            f"File path must end with .py extension. Received: '{relative_path}'"
        )
    
    # Check for path traversal attempts (..)
    if '..' in normalized_path:
        raise StrategyFileError(
            "File path cannot contain '..'. Path traversal is not allowed for security reasons."
        )
    
    # Check for absolute path (should not start with / on Unix or drive letter on Windows)
    if normalized_path.startswith('/') or (len(normalized_path) > 1 and normalized_path[1] == ':'):
        raise StrategyFileError(
            f"File path must be relative to strategies directory. Received: '{relative_path}'"
        )
    
    # Split into segments (path with .py extension)
    segments = [s for s in normalized_path.split('/') if s]
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
        
        # Check for dots/spaces at the end (Windows issue) - but allow .py at the end of filename
        if segment != segments[-1]:  # Not the last segment (filename)
            if segment.endswith('.') or segment.endswith(' '):
                raise StrategyFileError(f"File path segment '{segment}' cannot end with a dot or space")
    
    # Validate filename (last segment must end with .py)
    filename = segments[-1]
    if not filename:
        raise StrategyFileError("File path must end with a valid filename")
    
    if not filename.endswith('.py'):
        raise StrategyFileError("File path must end with .py extension")
    
    # Security check: verify that the resolved path stays within STRATEGIES_DIR
    try:
        # Build absolute path from relative (path already has .py extension)
        absolute_path = STRATEGIES_DIR / normalized_path
        absolute_path = absolute_path.resolve()
        strategies_dir_resolved = STRATEGIES_DIR.resolve()
        
        # Check that resolved path is within STRATEGIES_DIR
        try:
            absolute_path.relative_to(strategies_dir_resolved)
        except ValueError:
            raise StrategyFileError(
                f"File path would escape strategies directory. "
                f"Resolved path: '{absolute_path}' is not within '{strategies_dir_resolved}'"
            )
    except (OSError, ValueError) as e:
        raise StrategyFileError(f"Invalid file path: {str(e)}")


def validate_strategy_file_path(file_path: str) -> None:
    """
    Validate strategy file path for security and correctness.
    This is an alias for validate_relative_path for backward compatibility.
    
    Args:
        file_path: Relative file path from STRATEGIES_DIR (with .py extension)
        
    Raises:
        StrategyFileError: If path is invalid
    """
    validate_relative_path(file_path)


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
    Create a new strategy file with given name and file path
    
    Args:
        name: Strategy name (used for class name, can contain any characters)
        file_path: Relative file path from STRATEGIES_DIR (with .py extension).
                   Must be provided - name cannot be used for file path.
        
    Returns:
        Tuple of (relative_path, text) - relative path (with .py extension) and empty text
        
    Raises:
        StrategyFileError: If file_path is not provided, file already exists or creation fails
    """
    # Check that name is not empty
    if not name or not name.strip():
        raise StrategyFileError("Strategy name cannot be empty")
    
    # file_path is required - name cannot be used for file operations
    # name can contain any characters (e.g., "Вася пупкин: дурак!"), so it cannot be used as path
    if not file_path:
        raise StrategyFileError(
            "file_path is required. Strategy name cannot be used as file path."
        )
    
    # Validate relative path (must end with .py)
    validate_relative_path(file_path)
    
    # Use file_path as is (already has .py extension)
    relative_path = file_path
    
    # Build absolute path for file operations (using relative_path with .py, not name!)
    strategy_file_path = STRATEGIES_DIR / relative_path
    strategy_file_path = strategy_file_path.resolve()
    
    strategy_identifier = relative_path
    
    if strategy_file_path.exists():
        raise StrategyFileError(f"Strategy file already exists: {strategy_file_path}")
    
    # Ensure parent directories exist
    strategy_file_path.parent.mkdir(parents=True, exist_ok=True)
    
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
    
    # Return relative path (with .py extension) and text
    return (strategy_identifier, template_text)


def save_strategy(file_path: str, text: str) -> List[str]:
    """
    Save strategy to file
    
    Args:
        file_path: Relative path to strategy file (from STRATEGIES_DIR, with .py extension)
        text: Strategy Python code
        
    Returns:
        List of syntax errors (empty if no errors)
        
    Raises:
        StrategyFileError: If path is invalid or save fails
    """
    validate_relative_path(file_path)
    
    # Validate Python syntax (but don't fail, just collect errors)
    syntax_errors = validate_python_syntax(text)
    
    # Save file regardless of syntax errors (file_path already has .py extension)
    absolute_file_path = STRATEGIES_DIR / file_path
    try:
        absolute_file_path.write_text(text, encoding='utf-8')
    except Exception as e:
        raise StrategyFileError(f"Failed to save strategy file: {str(e)}")
    
    return syntax_errors


def load_strategy(file_path: str) -> Tuple[str, str, str]:
    """
    Load strategy from file by relative path

    Args:
        file_path: Relative path to strategy file (from STRATEGIES_DIR, with .py extension)

    Returns:
        Tuple of (name, file_path, text) - strategy name (extracted from path without .py), relative path (with .py), and code

    Raises:
        StrategyFileError: If path is invalid
        StrategyNotFoundError: If strategy file not found
    """
    # Validate relative path (must end with .py)
    validate_relative_path(file_path)

    # file_path already has .py extension
    absolute_file_path = STRATEGIES_DIR / file_path
    
    # Security check: ensure path is within STRATEGIES_DIR
    try:
        file_path_resolved = absolute_file_path.resolve()
        strategies_dir_resolved = STRATEGIES_DIR.resolve()
        if not str(file_path_resolved).startswith(str(strategies_dir_resolved)):
            raise StrategyNotFoundError(f"Strategy '{file_path}' not found")
    except (OSError, ValueError):
        raise StrategyNotFoundError(f"Strategy '{file_path}' not found")
    
    if not absolute_file_path.exists():
        raise StrategyNotFoundError(f"Strategy '{file_path}' not found")

    try:
        text = absolute_file_path.read_text(encoding='utf-8')
    except Exception as e:
        raise StrategyFileError(f"Failed to read strategy file: {str(e)}")

    # Extract strategy name from file path (filename without .py extension)
    path_segments = file_path.replace('\\', '/').split('/')
    filename_with_ext = path_segments[-1] if path_segments else file_path
    # Remove .py extension from filename for strategy name
    if filename_with_ext.endswith('.py'):
        strategy_name = filename_with_ext[:-3]
    else:
        strategy_name = filename_with_ext

    return (strategy_name, file_path, text)


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

