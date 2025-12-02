"""
Back testing and live trading
"""

from typing import List
from app.core.config import STRATEGIES_DIR


def strategies_get_list() -> List[str]:
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
