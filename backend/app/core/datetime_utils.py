"""
Utility functions for datetime handling.
"""
from datetime import datetime, timezone
import numpy as np


def parse_utc_datetime(date_str: str) -> datetime:
    """
    Parse date string and convert to datetime in UTC (naive datetime, but UTC time).
    
    Handles various date string formats:
    - ISO format with timezone (e.g., "2024-01-01T00:00:00Z" or "2024-01-01T00:00:00+00:00")
    - ISO format without timezone (assumed UTC)
    
    Args:
        date_str: Date string in ISO format
        
    Returns:
        datetime object representing the date in UTC (naive, but UTC time)
    """
    # Replace 'Z' with '+00:00' for fromisoformat compatibility
    date_str_normalized = date_str.replace('Z', '+00:00')
    
    # Parse datetime
    date_dt = datetime.fromisoformat(date_str_normalized)
    
    # Ensure UTC timezone
    if date_dt.tzinfo is None:
        date_dt = date_dt.replace(tzinfo=timezone.utc)
    else:
        date_dt = date_dt.astimezone(timezone.utc)
    
    # Return naive datetime (but we know it's UTC)
    return date_dt.replace(tzinfo=None)


def parse_utc_datetime64(date_str: str) -> np.datetime64:
    """
    Parse date string and convert to numpy datetime64 in UTC.
    
    Handles various date string formats:
    - ISO format with timezone (e.g., "2024-01-01T00:00:00Z" or "2024-01-01T00:00:00+00:00")
    - ISO format without timezone (assumed UTC)
    
    Args:
        date_str: Date string in ISO format
        
    Returns:
        numpy.datetime64 object representing the date in UTC (naive, but UTC time)
    """
    # Use parse_utc_datetime and convert to numpy datetime64
    date_dt = parse_utc_datetime(date_str)
    return np.datetime64(date_dt, 'ns')
