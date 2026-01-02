"""
Custom exceptions for strategies service
"""

from app.core.exceptions import R2D2Exception


class StrategyError(R2D2Exception):
    """Base exception for strategy-related errors"""
    pass


class StrategyNameError(StrategyError):
    """Raised when strategy name is invalid"""
    pass


class StrategyNotFoundError(StrategyError):
    """Raised when strategy file is not found"""
    pass


class StrategySyntaxError(StrategyError):
    """Raised when strategy Python code has syntax errors"""
    
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []


class StrategyFileError(StrategyError):
    """Raised when file operations fail"""
    pass

