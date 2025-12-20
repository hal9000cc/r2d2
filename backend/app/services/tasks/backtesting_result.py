"""
Класс для записи и чтения результатов бэктестинга в Redis.
Использует Sorted Set для хранения операций покупки и продажи.
"""
from typing import Optional, Dict
import numpy as np
from app.services.tasks.tasks import Task
from app.core.logger import get_logger

logger = get_logger(__name__)


class BackTestingResults:
    """
    Класс для записи и чтения результатов бэктестинга в Redis.
    Использует Sorted Set (ZADD) для хранения операций покупки и продажи.
    """
    
    def __init__(self, task: Task):
        """
        Конструктор.
        
        Args:
            task: Task instance (должен иметь метод get_result_key() и метод get_redis_client())
        """
        self.task = task
        self._redis_client = None
    
    def _get_redis_client(self):
        """
        Получить Redis клиент.
        
        Returns:
            redis.Redis: Redis client instance
            
        Raises:
            RuntimeError: If task is not associated with a list or cannot get Redis client
        """
        if self._redis_client is None:
            self._redis_client = self.task.get_redis_client()
        return self._redis_client
    
    def _datetime64_to_timestamp(self, dt64: np.datetime64) -> int:
        """
        Преобразовать np.datetime64 в Unix timestamp (секунды).
        
        Args:
            dt64: numpy datetime64 object
            
        Returns:
            int: Unix timestamp в секундах
        """
        # Преобразуем в секунды и затем в int
        return int(dt64.astype('datetime64[s]').astype(int))
    
    def _datetime64_to_iso(self, dt64: np.datetime64) -> str:
        """
        Преобразовать np.datetime64 в ISO строку.
        
        Args:
            dt64: numpy datetime64 object
            
        Returns:
            str: ISO формат строки (YYYY-MM-DDTHH:MM:SS)
        """
        # Преобразуем в datetime и форматируем
        dt = dt64.astype('datetime64[s]').astype(int)
        from datetime import datetime, timezone
        return datetime.fromtimestamp(dt, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    
    def reset(self) -> None:
        """
        Удаляет все результаты для задачи.
        Удаляет все ключи по паттерну {task.get_result_key()}:*
        
        Raises:
            RuntimeError: If reset operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            pattern = f"{result_key_prefix}:*"
            
            # Найти все ключи по паттерну
            keys = client.keys(pattern)
            
            if keys:
                # Удалить все найденные ключи
                deleted = client.delete(*keys)
                logger.debug(f"Reset backtesting results: deleted {deleted} keys matching pattern {pattern}")
            else:
                logger.debug(f"Reset backtesting results: no keys found matching pattern {pattern}")
        except Exception as e:
            logger.error(f"Failed to reset backtesting results: {str(e)}")
            raise RuntimeError(f"Failed to reset backtesting results: {str(e)}") from e
    
    def append_buy(
        self, 
        result_id: str,
        time: np.datetime64, 
        price: float, 
        volume: float, 
        fee: float, 
        deal_id: str
    ) -> None:
        """
        Добавляет операцию покупки в Redis Sorted Set.
        
        Args:
            result_id: ID результата (обычно task.result_id)
            time: Время операции (np.datetime64)
            price: Цена покупки
            volume: Объем покупки
            fee: Комиссия
            deal_id: ID сделки (для связи операций)
            
        Raises:
            RuntimeError: If append operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            key = f"{result_key_prefix}:{result_id}:buy"
            
            # Преобразуем время в timestamp для score
            score = self._datetime64_to_timestamp(time)
            
            # Формируем member: time_iso:price:volume:fee:deal_id
            time_iso = self._datetime64_to_iso(time)
            member = f"{time_iso}:{price}:{volume}:{fee}:{deal_id}"
            
            # Добавляем в Sorted Set
            client.zadd(key, {member: score})
            
            logger.debug(f"Appended buy operation to {key}: time={time_iso}, price={price}, volume={volume}, fee={fee}, deal_id={deal_id}")
        except Exception as e:
            logger.error(f"Failed to append buy operation: {str(e)}")
            raise RuntimeError(f"Failed to append buy operation: {str(e)}") from e
    
    def append_sell(
        self, 
        result_id: str,
        time: np.datetime64, 
        price: float, 
        volume: float, 
        fee: float, 
        deal_id: str
    ) -> None:
        """
        Добавляет операцию продажи в Redis Sorted Set.
        
        Args:
            result_id: ID результата (обычно task.result_id)
            time: Время операции (np.datetime64)
            price: Цена продажи
            volume: Объем продажи
            fee: Комиссия
            deal_id: ID сделки (для связи операций)
            
        Raises:
            RuntimeError: If append operation fails
        """
        try:
            client = self._get_redis_client()
            result_key_prefix = self.task.get_result_key()
            key = f"{result_key_prefix}:{result_id}:sell"
            
            # Преобразуем время в timestamp для score
            score = self._datetime64_to_timestamp(time)
            
            # Формируем member: time_iso:price:volume:fee:deal_id
            time_iso = self._datetime64_to_iso(time)
            member = f"{time_iso}:{price}:{volume}:{fee}:{deal_id}"
            
            # Добавляем в Sorted Set
            client.zadd(key, {member: score})
            
            logger.debug(f"Appended sell operation to {key}: time={time_iso}, price={price}, volume={volume}, fee={fee}, deal_id={deal_id}")
        except Exception as e:
            logger.error(f"Failed to append sell operation: {str(e)}")
            raise RuntimeError(f"Failed to append sell operation: {str(e)}") from e
    
    def get_results(
        self, 
        result_id: str,
        time_begin: Optional[np.datetime64] = None, 
        time_end: Optional[np.datetime64] = None
    ) -> Dict:
        """
        Получает результаты за указанный интервал времени.
        Пока заглушка - возвращает пустой словарь.
        
        Args:
            result_id: ID результата
            time_begin: Начало интервала (опционально)
            time_end: Конец интервала (опционально)
            
        Returns:
            Словарь с результатами (пока пустой)
        """
        # Заглушка
        return {}

