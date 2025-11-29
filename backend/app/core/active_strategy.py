import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.core.config import (
    DATA_DIR, 
    ACTIVE_STRATEGIES_FILE
)
from app.core.logger import get_logger

logger = get_logger(__name__)

# Store strategies as dict: {active_strategy_id: strategy_dict}
strategies: Dict[int, Dict[str, Any]] = {}
next_id: int = 0


def startup():
    """
    Initialize active strategies storage.
    Loads strategies from file into memory and initializes ID counter.
    """
    global strategies, next_id
    
    DATA_DIR.mkdir(exist_ok=True)
    try:
        # Load strategies from file (returns list)
        strategies_list = load_file()
        
        # Convert list to dict: {active_strategy_id: strategy_dict}
        strategies = {strategy["active_strategy_id"]: strategy for strategy in strategies_list}
        
        # Initialize ID counter
        if strategies:
            # Find maximum ID and set counter to max_id (next new_id() will return max_id + 1)
            next_id = max(strategies.keys())
        else:
            # Empty dict - initialize counter to 0 (next new_id() will return 1)
            next_id = 0
            
    except Exception as e:
        logger.critical(f"Failed to initialize active strategies storage: {str(e)}")
        raise RuntimeError(f"Failed to initialize active strategies storage: {str(e)}") from e


def shutdown():
    """
    Shutdown active strategies storage.
    Saves strategies from memory to file.
    """
    try:
        # Save current state to file (convert dict to list)
        if strategies:
            strategies_list = list(strategies.values())
            save_file(strategies_list)
    except Exception as e:
        logger.error(f"Failed to shutdown active strategies storage: {str(e)}")
        raise RuntimeError(f"Failed to shutdown active strategies storage: {str(e)}") from e


def save_file(active_strategies: List[Dict[str, Any]]) -> None:
    """
    Save list of active strategies to JSON file
    
    Args:
        active_strategies: List of strategy dictionaries
    """
    try:
        with open(ACTIVE_STRATEGIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(active_strategies, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise IOError(f"Failed to save active strategies: {str(e)}")


def load_file() -> List[Dict[str, Any]]:
    """
    Load list of active strategies from JSON file
    
    Returns:
        List of strategy dictionaries, empty list if file doesn't exist
    """
    try:
        if not ACTIVE_STRATEGIES_FILE.exists():
            return []
        
        with open(ACTIVE_STRATEGIES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure it's a list
            if isinstance(data, list):
                return data
            else:
                return []
    except json.JSONDecodeError:
        # If file is corrupted, return empty list
        return []
    except Exception as e:
        raise IOError(f"Failed to load active strategies: {str(e)}")


def get() -> List[Dict[str, Any]]:
    """
    Get list of active strategies from memory cache
    
    Returns:
        List of strategy dictionaries
    """
    return list(strategies.values())


def keep(active_strategies: List[Dict[str, Any]]) -> None:
    """
    Save list of active strategies to memory cache and file
    
    Args:
        active_strategies: List of strategy dictionaries
        
    Raises:
        IOError: If cannot save to file
    """
    global strategies
    try:
        # Convert list to dict and update memory cache
        strategies = {strategy["active_strategy_id"]: strategy for strategy in active_strategies}
        # Save to file
        save_file(active_strategies)
    except Exception as e:
        raise RuntimeError(f"Failed to keep active strategies: {str(e)}") from e


def get_by_id(active_strategy_id: int) -> Optional[Dict[str, Any]]:
    """
    Get single active strategy by ID
    
    Args:
        active_strategy_id: Strategy ID
        
    Returns:
        Strategy dictionary or None if not found
    """
    return strategies.get(active_strategy_id)


def update(active_strategy_id: int, strategy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update active strategy
    
    Args:
        active_strategy_id: Strategy ID
        strategy: Strategy dictionary
        
    Returns:
        Updated strategy dictionary
        
    Raises:
        KeyError: If strategy not found
    """
    if active_strategy_id not in strategies:
        raise KeyError(f"Strategy with ID {active_strategy_id} not found")
    
    # Ensure active_strategy_id matches
    strategy["active_strategy_id"] = active_strategy_id
    strategies[active_strategy_id] = strategy
    
    # Save to file
    save_file(list(strategies.values()))
    
    return strategy.copy()


def add(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add new active strategy
    
    Args:
        strategy: Strategy dictionary (must have active_strategy_id)
        
    Returns:
        Added strategy dictionary
    """
    active_strategy_id = strategy["active_strategy_id"]
    strategies[active_strategy_id] = strategy
    
    # Save to file
    save_file(list(strategies.values()))
    
    return strategy.copy()


def delete(active_strategy_id: int) -> None:
    """
    Delete active strategy
    
    Args:
        active_strategy_id: Strategy ID
        
    Raises:
        KeyError: If strategy not found
    """
    if active_strategy_id not in strategies:
        raise KeyError(f"Strategy with ID {active_strategy_id} not found")
    
    del strategies[active_strategy_id]
    
    # Save to file
    save_file(list(strategies.values()))


def new_id() -> int:
    """
    Get new unique ID for active strategy
    
    Returns:
        New unique ID for active strategy
    """
    global next_id
    next_id += 1
    return next_id

def new_strategy() -> Dict[str, Any]:
    """
    Create a new empty strategy with a new ID
    
    Returns:
        New strategy dictionary
    """
    return {
        "active_strategy_id": new_id(),
        "strategy_id": "",
        "name": "",
        "source": "",
        "symbol": "",
        "timeframe": "",
        "isRunning": False,
        "isTrading": False,
        "dateStart": (datetime.now() + timedelta(days=-30)).isoformat(),
        "dateEnd": (datetime.now() + timedelta(days=-1)).isoformat(),
        "parameters": {}
    }

