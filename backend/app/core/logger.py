"""
Logging configuration for the application.
Provides console and file logging with rotation.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from app.core.config import LOGS_DIR, LOG_LEVEL


class SingleLetterFormatter(logging.Formatter):
    """Custom formatter that uses single letter for log levels"""
    
    LEVEL_MAP = {
        'DEBUG': 'D',
        'INFO': 'I',
        'WARNING': 'W',
        'ERROR': 'E',
        'CRITICAL': 'C',
    }
    
    # Format with file and line number for ERROR and CRITICAL
    FORMAT_WITH_LOCATION = '%(asctime)s [%(levelname)s] %(name)s:%(filename)s:%(lineno)d: %(message)s'
    # Format without file and line number for other levels
    FORMAT_WITHOUT_LOCATION = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    
    def __init__(self, *args, **kwargs):
        # Store original format
        self._original_fmt = kwargs.get('fmt', self.FORMAT_WITHOUT_LOCATION)
        super().__init__(*args, **kwargs)
    
    def format(self, record):
        # Replace level name with single letter
        record.levelname = self.LEVEL_MAP.get(record.levelname, record.levelname[0])
        
        # Use format with location for ERROR and CRITICAL
        if record.levelno >= logging.ERROR:
            self._style._fmt = self.FORMAT_WITH_LOCATION
        else:
            self._style._fmt = self.FORMAT_WITHOUT_LOCATION
        
        return super().format(record)


def setup_logging():
    """
    Setup logging configuration.
    Creates console and file handlers with rotation.
    """
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create formatter with single letter levels
    formatter = SingleLetterFormatter(
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler: use original stdout to avoid pytest/capture closing it
    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation
    log_file = LOGS_DIR / "r2d2.log"
    file_handler = RotatingFileHandler(
        filename=str(log_file),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,  # Keep 5 backup files
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Set logging level for ccxt library to INFO (to avoid debug messages)
    ccxt_logger = logging.getLogger('ccxt')
    ccxt_logger.setLevel(logging.INFO)
    
    # Log initialization
    logger.info(f"Log level: {LOG_LEVEL}")
    logger.info(f"Log file: {log_file}")


def get_logger(name: str) -> logging.Logger:
    """
    Get logger instance for a module.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)

