"""
Module for managing strategy files.
Strategies are stored as Python files in STRATEGIES_DIR.
"""
from pathlib import Path
from typing import List
from app.core.config import STRATEGIES_DIR


def get_list() -> List[str]:
    """
    Get list of strategy identifiers from Python files in STRATEGIES_DIR.
    
    Returns:
        List of strategy identifiers (file names without .py extension)
    """
    strategy_ids = []
    
    for file_path in STRATEGIES_DIR.glob("*.py"):
        # Get file name without extension
        strategy_id = file_path.stem
        strategy_ids.append(strategy_id)
    
    # Return sorted list
    return sorted(strategy_ids)
