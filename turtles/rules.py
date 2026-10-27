"""Tanya Finch's field knowledge as numbers (email of Oct 27, 2026). Shared by the planner, F1 and F3.

Change these only with Tanya's input; each rule says where it came from.
"""
from __future__ import annotations

ACTIVE_F = (63, 83)          # box turtles' preferred air temperature range
ACTIVE_MONTHS = range(4, 11)  # active April-October; dormant (brumating) by early November
DAYTIME_ONLY = True           # diurnal, and not active at dawn or dusk
GOOD_RAIN_IN_PER_H = 0.1      # "rain-jacket rain", not drizzle; brings them out, especially after hot dry spells


def activity_note(month: int, temp_f: float | None, rain_in: float = 0.0) -> str:
    """One plain-English line on whether turtles were likely to be moving, for reports and the planner."""
    if month not in ACTIVE_MONTHS:
        return "Outside the April-October active season: turtles are likely dormant."
    if temp_f is None:
        return "No temperature recorded."
    lo, hi = ACTIVE_F
    if rain_in >= GOOD_RAIN_IN_PER_H and temp_f >= lo - 5:
        return f"Real rain at {temp_f:.0f}°F: a high-activity window."
    if temp_f < lo:
        return f"{temp_f:.0f}°F, below the {lo}-{hi}°F active range: low activity expected."
    if temp_f > hi:
        return f"{temp_f:.0f}°F, above the {lo}-{hi}°F active range: turtles likely sheltering."
    return f"{temp_f:.0f}°F, inside the {lo}-{hi}°F active range: turtles likely moving."
