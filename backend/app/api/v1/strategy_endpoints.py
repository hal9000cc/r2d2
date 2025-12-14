from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from fnmatch import fnmatch
from pydantic import BaseModel
from app.core.config import STRATEGIES_DIR
from app.services.strategies import (
    create_strategy,
    save_strategy as save_strategy_service,
    load_strategy as load_strategy_service,
    get_strategy_parameters_description as get_strategy_parameters_description_service,
    ParameterDescription,
    StrategyModel,
    StrategySaveResponse
)
from app.services.strategies.exceptions import (
    StrategyNameError,
    StrategyNotFoundError,
    StrategyFileError
)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


class FileItem(BaseModel):
    """File or directory item"""
    name: str
    type: str  # "file" or "directory"


class FileListResponse(BaseModel):
    """Response model for file list"""
    current_path: str
    parent_path: Optional[str]
    items: List[FileItem]


@router.get("/files/list", response_model=FileListResponse)
async def list_files(
    path: Optional[str] = Query(None, description="Full path to directory (empty for root)"),
    mask: Optional[str] = Query(None, description="File mask filter (e.g., '*.py')")
):
    """
    List files and directories in the specified path
    
    Args:
        path: Full path to directory. If None or empty, uses STRATEGIES_DIR root
        mask: Optional file mask filter (e.g., '*.py' for Python files only)
        
    Returns:
        FileListResponse with current path, parent path, and list of items
    """
    # Determine target directory
    if path:
        target_dir = Path(path)
        # Security check: ensure path is within STRATEGIES_DIR
        try:
            # Resolve both paths to absolute paths to handle symlinks and relative paths
            target_dir_resolved = target_dir.resolve()
            strategies_dir_resolved = STRATEGIES_DIR.resolve()
            # Check if target_dir is a subdirectory of STRATEGIES_DIR
            if not str(target_dir_resolved).startswith(str(strategies_dir_resolved)):
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied: Path must be within strategies directory"
                )
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid path: {str(e)}")
    else:
        target_dir = STRATEGIES_DIR
    
    # Check if path exists and is a directory
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {path}")
    
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
    
    # Get parent path
    parent_path = None
    if target_dir != STRATEGIES_DIR and target_dir.parent != target_dir:
        parent_path = str(target_dir.parent)
    
    # List items
    directories = []
    files = []
    try:
        for item in target_dir.iterdir():
            if item.is_dir():
                directories.append(FileItem(name=item.name, type="directory"))
            elif item.is_file():
                # Apply mask filter if provided
                if mask:
                    if fnmatch(item.name, mask):
                        files.append(FileItem(name=item.name, type="file"))
                else:
                    files.append(FileItem(name=item.name, type="file"))
        
        # Sort directories and files by name
        directories.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())
        
        # Combine: directories first, then files
        items = directories + files
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")
    
    # Return paths as-is (normalized with forward slashes)
    # Frontend will convert to Windows-style for display if needed
    current_path_str = str(target_dir)
    parent_path_str = str(parent_path) if parent_path else None
    
    return FileListResponse(
        current_path=current_path_str,
        parent_path=parent_path_str,
        items=items
    )


@router.get("/directory")
async def get_strategies_directory() -> str:
    """
    Get the strategies directory path
    
    Returns:
        Path to the strategies directory (with trailing separator)
    """
    path_str = str(STRATEGIES_DIR)
    # Ensure trailing separator
    if not path_str.endswith('/'):
        path_str += '/'
    return path_str


def convert_parameters_to_model(params_dict: Optional[Dict[str, Tuple[Any, str, str]]]) -> Optional[Dict[str, ParameterDescription]]:
    """
    Convert parameters dictionary from service format to API model format
    
    Args:
        params_dict: Dictionary from service layer with (default_value, type_name, description) tuples
        
    Returns:
        Dictionary with ParameterDescription objects or None
    """
    if params_dict is None:
        return None
    
    result = {}
    for param_name, (default_value, type_name, description) in params_dict.items():
        result[param_name] = ParameterDescription(
            default_value=default_value,
            type=type_name,
            description=description
        )
    
    return result


@router.post("/new", response_model=StrategyModel)
async def new_strategy(name: str, file_path: Optional[str] = Query(None, description="Optional file path relative to STRATEGIES_DIR (without .py extension)")):
    """
    Create a new strategy with given name and optional file path
    
    Args:
        name: Strategy name (used for class name)
        file_path: Optional file path relative to STRATEGIES_DIR (without .py extension).
                   If provided, this path will be used for file location instead of name.
        
    Returns:
        Strategy JSON with name, text, and parameters description
    """
    try:
        strategy_name, strategy_text = create_strategy(name, file_path)
        params_dict, errors = get_strategy_parameters_description_service(strategy_name, strategy_text)
        parameters_description = convert_parameters_to_model(params_dict)
        return StrategyModel(
            name=strategy_name, 
            text=strategy_text,
            parameters_description=parameters_description,
            loading_errors=errors
        )
    except StrategyNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StrategyFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/save", response_model=StrategySaveResponse)
async def save_strategy(strategy: StrategyModel):
    """
    Save strategy to file
    
    Args:
        strategy: Strategy JSON with name and text
    
    Returns:
        Response with syntax errors (if any)
    """
    try:
        syntax_errors = save_strategy_service(strategy.name, strategy.text)
        return StrategySaveResponse(
            success=True,
            message="Strategy saved successfully",
            syntax_errors=syntax_errors
        )
    except StrategyNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StrategyFileError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/load/{name}", response_model=StrategyModel)
async def load_strategy(name: str):
    """
    Load strategy from file by name
    
    Args:
        name: Strategy name (filename without .py extension, can include subdirectories)
        
    Returns:
        Strategy JSON with name, text, and parameters description
    """
    try:
        strategy_name, strategy_text, strategy_filename = load_strategy_service(name)
        params_dict, errors = get_strategy_parameters_description_service(strategy_name, strategy_text)
        parameters_description = convert_parameters_to_model(params_dict)
        return StrategyModel(
            name=strategy_name,
            text=strategy_text,
            filename=strategy_filename,
            parameters_description=parameters_description,
            loading_errors=errors
        )
    except StrategyNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StrategyFileError as e:
        raise HTTPException(status_code=500, detail=str(e))

