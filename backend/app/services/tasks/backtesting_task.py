"""
Backtesting task management with Redis storage.
"""
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Type
from pydantic import Field, model_validator
from app.core.objects2redis import Objects2Redis, Objects2RedisList
from app.core.logger import get_logger

logger = get_logger(__name__)


class BacktestingTask(Objects2Redis):
    """
    Backtesting task class representing a backtesting strategy task.
    Inherits from Objects2Redis for Redis storage with Pydantic validation.
    """
    
    strategy_id: str = ""
    name: str = ""
    source: str = ""
    symbol: str = ""
    timeframe: str = ""
    isRunning: bool = False
    dateStart: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-30)).isoformat()
    )
    dateEnd: str = Field(
        default_factory=lambda: (datetime.now() + timedelta(days=-1)).isoformat()
    )
    parameters: Dict[str, Any] = Field(default_factory=dict)
    
    @model_validator(mode='after')
    def generate_name(self):
        """Generate name if not set"""
        if not self.name and self.strategy_id:
            self.name = f'{self.strategy_id} ({self.source}:{self.symbol} {self.timeframe})'
        return self
    
    def get_key(self) -> str:
        """
        Returns secondary key for the backtesting task (strategy_id).
        Used for indexing and searching backtesting tasks by strategy.
        """
        return self.strategy_id if self.strategy_id else ""


class BacktestingTaskList(Objects2RedisList[BacktestingTask]):
    """
    Singleton class for managing backtesting tasks in Redis.
    Inherits from Objects2RedisList.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BacktestingTaskList, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, redis_params: Optional[Dict] = None):
        # If already initialized, just return (allow multiple calls without params)
        if BacktestingTaskList._initialized:
            return
            
        # First initialization requires redis_params
        if redis_params is not None:
            super().__init__(redis_params)
            BacktestingTaskList._initialized = True
    
    def list_key(self) -> str:
        """Returns the prefix for backtesting task keys in Redis"""
        return "backtesting_tasks"
    
    def object_class(self) -> Type[BacktestingTask]:
        """Returns the BacktestingTask class"""
        return BacktestingTask

