"""
Custom exceptions for tasks service
"""

from app.core.exceptions import R2D2Exception


class R2D2IndicatorError(R2D2Exception):
    """Base exception for indicator-related errors"""
    pass


class R2D2IndicatorNotFoundError(R2D2IndicatorError):
    """Raised when indicator is not found in metadata"""
    pass

