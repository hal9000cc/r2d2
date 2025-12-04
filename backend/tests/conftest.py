"""
Pytest configuration for test ordering.
Automatically sets order for tests based on file name.
Tests from test_quotes.py get order=1, all others get order=2.
"""
import pytest


def pytest_collection_modifyitems(config, items):
    """
    Automatically set order for tests based on file name.
    Tests from test_quotes.py get order=1, all others get order=2.
    This ensures test_quotes.py runs first, then all other tests.
    Works with both sequential and parallel test execution (pytest-xdist).
    """
    for item in items:
        # Get the file path - try different attributes for compatibility
        file_path = str(getattr(item, 'fspath', None) or getattr(item, 'path', None) or '')
        
        # Check if it's test_quotes.py
        if 'test_quotes' in file_path:
            # Add order=1 marker if not already present
            if not any(mark.name == 'order' for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(1))
        else:
            # Add order=2 marker if not already present
            if not any(mark.name == 'order' for mark in item.iter_markers()):
                item.add_marker(pytest.mark.order(2))

