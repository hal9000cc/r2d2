from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import ccxt
import asyncio
from datetime import datetime
import json
from app.services.tasks.tasks import TaskList
from app.services.tasks import strategies_get_list as strategies_get_list
from app.services.quotes.timeframe import Timeframe

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

# Get TaskList singleton instance
task_list = TaskList()


def _get_timeframes_list() -> List[str]:
    """
    Get list of timeframes from Timeframe class.
    Selects all attributes that start with 't' and have numeric type.
    Returns names without 't' prefix (e.g., '1m' instead of 't1m'),
    sorted by value in ascending order.
    """
    timeframes = []
    for attr_name in dir(Timeframe):
        if attr_name.startswith('t') and not attr_name.startswith('__'):
            attr_value = getattr(Timeframe, attr_name)
            if isinstance(attr_value, (int, float)):
                # Store tuple (value, name) for sorting by value
                timeframes.append((attr_value, attr_name[1:]))
    # Sort by value (first element of tuple) and return only names
    return [name for _, name in sorted(timeframes, key=lambda x: x[0])]


@router.get("/timeframes", response_model=List[str])
async def get_timeframes():
    """
    Get list of available timeframes
    """
    return _get_timeframes_list()


@router.get("/sources", response_model=List[str])
async def get_sources():
    """
    Get list of available sources (exchanges) from ccxt
    """
    # Get list of all available exchanges from ccxt
    return sorted(ccxt.exchanges)


# Cache for symbols by source
source_symbols: Dict[str, List[str]] = {}


@router.get("/sources/{source}/symbols", response_model=List[str])
async def get_source_symbols(source: str):
    """
    Get list of symbols for a specific source (exchange)
    Symbols are cached per source to avoid repeated API calls
    """
    # Check cache first
    if source in source_symbols:
        return source_symbols[source]
    
    try:
        # Create exchange instance
        exchange_class = getattr(ccxt, source)
        exchange = exchange_class({
            'enableRateLimit': True,
        })
        
        # Load markets to get symbols
        markets = exchange.load_markets()
        
        # Extract unique symbols
        symbols = sorted(list(set(markets.keys())))
        
        # Cache the result
        source_symbols[source] = symbols
        
        return symbols
    except AttributeError:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found in ccxt")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load symbols for source '{source}': {str(e)}")


@router.get("/strategies", response_model=List[str])
async def get_strategies():
    """
    Get list of available strategy identifiers from Python files in STRATEGIES_DIR
    """
    return strategies_get_list()


@router.get("", response_model=List[Dict[str, Any]])
async def get_active_strategies():
    """
    Get list of active strategies
    """
    tasks = task_list.get_tasks()
    return [task.to_dict() for task in tasks]


@router.get("/{strategy_id}", response_model=Dict[str, Any])
async def get_active_strategy(strategy_id: int):
    """
    Get single active strategy by ID
    If strategy_id is 0, returns empty strategy with new ID
    """
    # If strategy_id == 0, return empty strategy with new ID
    if strategy_id == 0:
        task = task_list.new_task()
        return task.to_dict()
    
    task = task_list.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    return task.to_dict()


@router.delete("/{strategy_id}", response_model=List[Dict[str, Any]])
async def delete_strategy(strategy_id: int):
    """
    Delete active strategy
    Returns updated list of strategies
    """
    try:
        task_list.delete_task(strategy_id)
        tasks = task_list.get_tasks()
        return [task.to_dict() for task in tasks]
    except KeyError:
        raise HTTPException(status_code=404, detail="Strategy not found")


@router.post("/{strategy_id}/start", response_model=Dict[str, Any])
async def start_strategy(strategy_id: int):
    """
    Start strategy
    Returns updated strategy object
    """
    task = task_list.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update isRunning to True
    task.isRunning = True
    updated_task = task_list.put_task(task)
    return updated_task.to_dict()


@router.post("/{strategy_id}/stop", response_model=Dict[str, Any])
async def stop_strategy(strategy_id: int):
    """
    Stop strategy
    Returns updated strategy object
    """
    task = task_list.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update isRunning to False
    task.isRunning = False
    updated_task = task_list.put_task(task)
    return updated_task.to_dict()


@router.post("/{strategy_id}/toggle-trading", response_model=Dict[str, Any])
async def toggle_trading(strategy_id: int):
    """
    Toggle trading for strategy
    Returns updated strategy object
    """
    task = task_list.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Toggle isTrading
    task.isTrading = not task.isTrading
    updated_task = task_list.put_task(task)
    return updated_task.to_dict()


@router.put("/{strategy_id}", response_model=Dict[str, Any])
async def update_strategy(strategy_id: int, strategy_data: Dict[str, Any]):
    """
    Update active strategy
    Returns updated strategy object
    """
    # Ensure active_strategy_id matches
    strategy_data["active_strategy_id"] = strategy_id
    
    # Convert dict to Task object
    from app.services.tasks.tasks import Task
    task = Task.from_dict(strategy_data)
    
    # put_task will add or update the strategy
    updated_task = task_list.put_task(task)
    return updated_task.to_dict()


# In-memory storage for messages (strategy_id -> list of messages)
_messages_storage: Dict[int, List[Dict[str, Any]]] = {}


def _generate_messages(strategy_id: int, count: int = 10) -> List[Dict[str, Any]]:
    """
    Generate sample messages for a strategy (stub implementation)
    
    Args:
        strategy_id: Strategy ID
        count: Number of messages to generate
        
    Returns:
        List of message dictionaries
    """
    import random
    levels = ['info', 'warning', 'error', 'debug']
    messages = [
        f"Strategy {strategy_id} initialized",
        f"Processing data for strategy {strategy_id}",
        f"Strategy {strategy_id} running normally",
        f"Warning: Strategy {strategy_id} detected anomaly",
        f"Error in strategy {strategy_id}",
        f"Strategy {strategy_id} completed operation",
        f"Debug: Strategy {strategy_id} state check",
        f"Strategy {strategy_id} updated parameters"
    ]
    
    result = []
    for i in range(count):
        result.append({
            "timestamp": (datetime.now().isoformat()),
            "level": random.choice(levels),
            "message": random.choice(messages)
        })
    
    return result


@router.get("/{strategy_id}/messages", response_model=List[Dict[str, Any]])
async def get_messages(strategy_id: int):
    """
    Get messages for a strategy
    
    Args:
        strategy_id: Strategy ID
        
    Returns:
        List of messages
    """
    # Check if task exists
    task = task_list.get_task(strategy_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Generate messages on the fly (stub)
    if strategy_id not in _messages_storage:
        _messages_storage[strategy_id] = _generate_messages(strategy_id, 1)
    
    return _messages_storage[strategy_id]


# WebSocket connections storage (strategy_id -> set of websockets)
_websocket_connections: Dict[int, set] = {}


@router.websocket("/{strategy_id}/messages")
async def websocket_messages(websocket: WebSocket, strategy_id: int):
    """
    WebSocket endpoint for real-time message updates
    
    Args:
        websocket: WebSocket connection
        strategy_id: Strategy ID
    """
    await websocket.accept()
    
    # Check if task exists
    task = task_list.get_task(strategy_id)
    if task is None:
        await websocket.close(code=1008, reason="Strategy not found")
        return
    
    # Add connection to storage
    if strategy_id not in _websocket_connections:
        _websocket_connections[strategy_id] = set()
    _websocket_connections[strategy_id].add(websocket)
    
    try:
        # Send initial messages
        # if strategy_id in _messages_storage:
        #     initial_messages = _messages_storage[strategy_id][-10:]  # Last 10 messages
        #     for msg in initial_messages:
        #         await websocket.send_json(msg)
        
        # Generate and send new messages periodically (stub)
        counter = 0
        for i in range(4):
            await asyncio.sleep(5)
            
            # Generate new message
            new_message = {
                "timestamp": datetime.now().isoformat(),
                "level": "info",
                "message": f"Strategy {strategy_id} update #{counter}"
            }
            
            # Store message
            if strategy_id not in _messages_storage:
                _messages_storage[strategy_id] = []
            _messages_storage[strategy_id].append(new_message)
            
            # Keep only last 100 messages
            # if len(_messages_storage[strategy_id]) > 100:
            #     _messages_storage[strategy_id] = _messages_storage[strategy_id][-100:]
            
            # Send to all connected clients for this strategy
            disconnected = set()
            for ws in _websocket_connections[strategy_id]:
                try:
                    await ws.send_json(new_message)
                except Exception:
                    disconnected.add(ws)
            
            # Remove disconnected clients
            _websocket_connections[strategy_id] -= disconnected
            
            counter += 1
            
    except WebSocketDisconnect:
        pass
    finally:
        # Remove connection from storage
        if strategy_id in _websocket_connections:
            _websocket_connections[strategy_id].discard(websocket)
            if not _websocket_connections[strategy_id]:
                del _websocket_connections[strategy_id]

