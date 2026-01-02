"""
Utility functions
"""
import random

# Good colors for indicators (matching frontend generateRandomColor)
GOOD_COLORS = [
    '#FF6B6B', '#4ECDC4', '#FFD166', '#06D6A0',
    '#118AB2', '#EF476F', '#7209B7', '#F3722C',
    '#277DA1', '#90BE6D', '#F9C74F', '#43AA8B',
    '#577590', '#F94144', '#F8961E', '#277DA1'
]


def generate_random_color() -> str:
    """
    Generate random color from predefined good colors list.
    Matches frontend generateRandomColor function.
    
    Returns:
        Hex color string (e.g., '#FF6B6B')
    """
    return random.choice(GOOD_COLORS)

