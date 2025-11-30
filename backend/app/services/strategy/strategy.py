from abc import ABC, abstractmethod

class Strategy(ABC):
    
    @abstractmethod
    def on_bar(self):
        """
        Called when a new bar is received.
        """
        pass
    
