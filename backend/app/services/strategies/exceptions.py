"""
Custom exceptions for strategies service
"""

from app.core.exceptions import R2D2Exception


class R2D2StrategyError(R2D2Exception):
    """Base exception for strategy-related errors"""
    pass


class R2D2StrategyNameError(R2D2StrategyError):
    """Raised when strategy name is invalid"""
    pass


class R2D2StrategyNotFoundError(R2D2StrategyError):
    """Raised when strategy file is not found"""
    pass


class R2D2StrategySyntaxError(R2D2StrategyError):
    """Raised when strategy Python code has syntax errors"""
    
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []


class R2D2StrategyFileError(R2D2StrategyError):
    """Raised when file operations fail"""
    pass

