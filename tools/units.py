"""Unit conversion utilities.

FreeCAD works in millimeters internally. The agent and user work in feet and inches.
All tool functions accept feet/inches and convert to mm before calling FreeCAD.
"""

MM_PER_INCH = 25.4
INCHES_PER_FOOT = 12


def feet_to_mm(feet: float) -> float:
    return feet * INCHES_PER_FOOT * MM_PER_INCH


def inches_to_mm(inches: float) -> float:
    return inches * MM_PER_INCH


def ft_in_to_mm(feet: float, inches: float = 0) -> float:
    """Convert feet + inches to mm."""
    total_inches = feet * INCHES_PER_FOOT + inches
    return total_inches * MM_PER_INCH


def mm_to_feet(mm: float) -> float:
    return mm / MM_PER_INCH / INCHES_PER_FOOT


def mm_to_inches(mm: float) -> float:
    return mm / MM_PER_INCH


def mm_to_ft_in(mm: float) -> tuple[int, float]:
    """Convert mm to (whole_feet, remaining_inches)."""
    total_inches = mm / MM_PER_INCH
    feet = int(total_inches // INCHES_PER_FOOT)
    remaining = total_inches - feet * INCHES_PER_FOOT
    return feet, round(remaining, 2)


def format_ft_in(feet: int, inches: float) -> str:
    if inches == 0:
        return f"{feet}'-0\""
    return f"{feet}'-{inches}\""
