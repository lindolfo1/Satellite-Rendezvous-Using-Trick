"""`fmt_range` and the fixed-width value formatters.

Ported unit switching: metres below 1 km, kilometres above. Formatters are
fixed-width so nothing jitters horizontally during playback (spec 8). The
viewer's JS mirrors `fmt_range`; the two must agree.
"""

from __future__ import annotations

import numpy as np


def fmt_range(metres: float, mode: str = "auto") -> str:
    """Metres below 1 km, kilometres above, unless `mode` forces one."""
    if metres is None or not np.isfinite(metres):
        return "—"
    if mode == "m" or (mode == "auto" and abs(metres) < 1000.0):
        return f"{metres:,.1f} m"
    return f"{metres / 1000.0:,.3f} km"


def fmt_vec(vec, unit: str = "m", places: int = 1) -> str:
    return ", ".join(f"{c:,.{places}f}" for c in vec) + f" {unit}"


def fmt_angle_mrad(radians: float) -> str:
    """Angular errors read in milliradians (spec 4.7)."""
    if radians is None or not np.isfinite(radians):
        return "—"
    return f"{radians * 1000.0:+.3f} mrad"


def fmt_duration(seconds: float) -> str:
    seconds = float(seconds)
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
