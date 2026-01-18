from typing import List

from app.services.tasks.broker_new import Broker, Order


class BrokerBacktesting(Broker):
    """
    Backtesting broker implementation.
    
    Inherits from Broker and implements abstract methods for backtesting scenarios.
    """
    
    def create_order(self, order: Order) -> List[str]:
        """
        Create an order (backtesting implementation).
        
        Args:
            order: Order object to create
        
        Returns:
            List of errors. Empty list if order was created successfully.
        """
        # TODO: Implement order creation logic for backtesting
        return []
    
    def cancel_order(self, order_id: str, symbol: str) -> List[str]:
        """
        Cancel an order by its ID (backtesting implementation).
        
        Args:
            order_id: Order ID to cancel
            symbol: Trading symbol (e.g., 'BTC/USDT')
        
        Returns:
            List of error messages. Empty list means success (order was canceled successfully).
            Non-empty list contains error descriptions if cancellation failed.
        """
        # TODO: Implement order cancellation logic for backtesting
        return []

