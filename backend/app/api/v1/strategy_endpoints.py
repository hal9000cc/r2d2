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
    validate_relative_path,
    ParameterDescription,
    StrategyModel,
    StrategySaveResponse
)
from app.services.strategies.exceptions import (
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
    path: Optional[str] = Query(None, description="Relative path from STRATEGIES_DIR (empty for root)"),
    mask: Optional[str] = Query(None, description="File mask filter (e.g., '*.py')")
):
    """
    List files and directories in the specified path
    
    Args:
        path: Relative path from STRATEGIES_DIR. If None or empty, uses STRATEGIES_DIR root
        mask: Optional file mask filter (e.g., '*.py' for Python files only)
        
    Returns:
        FileListResponse with current path (relative), parent path (relative), and list of items
    """
    # Convert relative path to absolute for file operations
    if path:
        # path is a directory path, not a file path, so we don't validate it with validate_relative_path
        # (which requires .py extension). Instead, just check for path traversal.
        normalized_path = path.replace('\\', '/').strip('/')
        if '..' in normalized_path:
            raise HTTPException(
                status_code=400,
                detail="Path cannot contain '..'. Path traversal is not allowed."
            )
        
        # Build absolute path from relative
        target_dir = STRATEGIES_DIR / path
        target_dir = target_dir.resolve()
        
        # Security check: ensure resolved path is within STRATEGIES_DIR
        strategies_dir_resolved = STRATEGIES_DIR.resolve()
        try:
            target_dir.relative_to(strategies_dir_resolved)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: Path must be within strategies directory"
            )
    else:
        target_dir = STRATEGIES_DIR
    
    # Check if path exists and is a directory
    if not target_dir.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {path}")
    
    if not target_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
    
    # Get parent path (relative)
    parent_path = None
    if target_dir != STRATEGIES_DIR and target_dir.parent != target_dir:
        try:
            parent_relative = target_dir.parent.resolve().relative_to(STRATEGIES_DIR.resolve())
            parent_path = str(parent_relative).replace('\\', '/')
        except ValueError:
            parent_path = None
    
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
    
    # Return relative paths
    try:
        current_relative = target_dir.resolve().relative_to(STRATEGIES_DIR.resolve())
        current_path_str = str(current_relative).replace('\\', '/')
        # Normalize: if path is "." (root), return empty string
        if current_path_str == '.' or current_path_str == './':
            current_path_str = ""
    except ValueError:
        current_path_str = ""
    
    return FileListResponse(
        current_path=current_path_str,
        parent_path=parent_path,
        items=items
    )


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
async def new_strategy(name: str, file_path: Optional[str] = Query(None, description="Relative file path from STRATEGIES_DIR (with .py extension)")):
    """
    Create a new strategy with given name and file path
    
    Args:
        name: Strategy name (used for class name, can contain any characters)
        file_path: Relative file path from STRATEGIES_DIR (with .py extension).
                   Must be provided - name cannot be used for file path.
        
    Returns:
        Strategy JSON with name, file_path, text, and parameters description
    """
    try:
        # file_path is required
        if not file_path:
            raise HTTPException(
                status_code=400,
                detail="file_path is required. Strategy name cannot be used as file path."
            )
        
        # Validate relative path (must end with .py)
        validate_relative_path(file_path)
        
        relative_path, strategy_text = create_strategy(name, file_path)
        # Extract strategy name from path (filename without .py extension)
        # relative_path is guaranteed to end with .py (validated by validate_relative_path)
        path_segments = relative_path.replace('\\', '/').split('/')
        filename_with_ext = path_segments[-1] if path_segments else relative_path
        strategy_name = filename_with_ext[:-3]  # Remove .py extension
        
        params_dict, errors = get_strategy_parameters_description_service(relative_path, strategy_text)
        parameters_description = convert_parameters_to_model(params_dict)
        return StrategyModel(
            name=strategy_name,  # Strategy name (extracted from path)
            file_path=relative_path,  # Relative path to file
            text=strategy_text,
            parameters_description=parameters_description,
            loading_errors=errors
        )
    except StrategyFileError as e:
        raise HTTPException(status_code=400, detail=str(e))


class StrategySaveRequest(BaseModel):
    """Request model for saving strategy (only file_path and text are required)"""
    file_path: str  # Relative path to strategy file (from STRATEGIES_DIR, with .py extension)
    text: str  # Strategy Python code


@router.post("/save", response_model=StrategySaveResponse)
async def save_strategy(strategy: StrategySaveRequest):
    """
    Save strategy to file
    
    Args:
        strategy: Strategy JSON with file_path (relative path with .py extension) and text
    
    Returns:
        Response with syntax errors (if any)
    """
    try:
        # Validate relative path (must end with .py)
        validate_relative_path(strategy.file_path)
        
        syntax_errors = save_strategy_service(strategy.file_path, strategy.text)
        return StrategySaveResponse(
            success=True,
            message="Strategy saved successfully",
            syntax_errors=syntax_errors
        )
    except StrategyFileError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/load/{name}", response_model=StrategyModel)
async def load_strategy(name: str):
    """
    Load strategy from file by relative path
    
    Args:
        name: Relative path to strategy file (with .py extension, can include subdirectories)
        
    Returns:
        Strategy JSON with name, file_path, text, and parameters description
    """
    try:
        # Validate relative path (must end with .py)
        validate_relative_path(name)
        
        strategy_name, file_path, strategy_text = load_strategy_service(name)
        params_dict, errors = get_strategy_parameters_description_service(file_path, strategy_text)
        parameters_description = convert_parameters_to_model(params_dict)
        return StrategyModel(
            name=strategy_name,  # Strategy name (extracted from path)
            file_path=file_path,  # Relative path to file
            text=strategy_text,
            parameters_description=parameters_description,
            loading_errors=errors
        )
    except StrategyNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StrategyFileError as e:
        raise HTTPException(status_code=500, detail=str(e))

