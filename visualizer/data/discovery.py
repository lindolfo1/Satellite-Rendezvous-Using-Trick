"""Scan the runs folder and pair `<stem>.csv` with `<stem>.json`.

Spec 1. Reads the sidecar JSON only -- cheap, and enough to show UTC start and
the waypoint corridor in the selector. The CSV is never opened here; that is
Stage 3's job, and doing it at scan time would make the sidebar cost grow with
the number of runs on disk.

An unpaired or malformed run is **listed as unavailable with its reason**, not
skipped. A file that vanishes from the UI teaches you nothing; one that says
"no matching run_1.csv" tells you exactly what to fix.

Together with `loader.py`, this is one of only two modules that change when the
input file format changes (acceptance criterion 11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

import config


@dataclass(frozen=True)
class RunRecord:
    """One candidate run. `available` is the only thing the UI must check."""

    stem: str
    csv_path: Path | None
    json_path: Path | None
    available: bool
    reason: str | None = None
    utc_start: datetime | None = None
    waypoint_range_m: tuple[float, ...] | None = None

    #: Fractional position tolerance on each waypoint, from the sidecar. The
    #: ball around waypoint i has radius |tolerance * waypoint_range[i]|.
    #: None when the sidecar predates the field.
    tolerance: float | None = None
    csv_bytes: int | None = None
    mtime: float = 0.0

    @property
    def tolerance_label(self) -> str:
        if self.tolerance is None:
            return "not in sidecar"
        return f"{self.tolerance * 100:g}% of each standoff"

    @property
    def corridor_label(self) -> str:
        """Always shown outermost to innermost, whichever way the file lists it.

        A corridor reads as an approach, so it is displayed as one; the file's
        own order is reported separately rather than by scrambling the label.
        """
        if not self.waypoint_range_m:
            return "—"
        ordered = self.waypoint_range_m
        if not corridor_descends(ordered):
            ordered = tuple(reversed(ordered))
        label = " → ".join(f"{v:g}" for v in ordered) + " m"
        if not corridor_descends(self.waypoint_range_m):
            label += "  (file lists it innermost first)"
        return label

    @property
    def size_label(self) -> str:
        if self.csv_bytes is None:
            return "—"
        mb = self.csv_bytes / 1_048_576
        return f"{mb:.1f} MB" if mb >= 1 else f"{self.csv_bytes / 1024:.0f} KB"


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 instant, accepting `Z` as well as `+00:00`.

    Spec 2 requires timezone awareness. A naive timestamp is rejected rather
    than assumed to be UTC: silently guessing the zone would put the Earth's
    rotation hours out, and the error would surface as a wrong ground track --
    a long way from its cause.
    """
    if not isinstance(value, str):
        raise ValueError(f"utc_start_time must be a string, got {type(value).__name__}")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"utc_start_time '{value}' has no timezone offset")
    return parsed.astimezone(timezone.utc)


def parse_tolerance(value: object) -> float:
    """Validate the sidecar's `tolerance`: a fraction of each standoff.

    A fraction, not a distance -- the ball around a 750 m waypoint is larger
    than the one around 20 m. Rejecting values above 1 catches a file that put
    metres here instead: a tolerance wider than the standoff itself would make
    the innermost ball swallow the target.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"tolerance must be a number, got {value!r}")
    if not 0 < float(value) <= 1.0:
        raise ValueError(
            f"tolerance must be a fraction in (0, 1], got {value} -- "
            "it multiplies each standoff rather than being a distance")
    return float(value)


def parse_corridor(value: object) -> tuple[float, ...]:
    """Validate `waypoint_range` and return it as floats, in file order.

    Length is read from the file, never assumed to be 4 (spec 2).

    Spec 2 says outermost to innermost. The array is **not** reordered when it
    arrives the other way round: `currentWaypoint` indexes it as written, so
    reversing it here would silently point every waypoint lookup at the wrong
    entry. The direction is detected instead -- see `corridor_descends` -- and
    everything downstream works from that.

    What is rejected is a corridor that is not monotonic at all. An approach
    goes one way; a jumbled list is a broken file rather than a convention.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("waypoint_range must be a non-empty list")
    out = []
    for i, v in enumerate(value):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"waypoint_range[{i}] is not a number: {v!r}")
        if v <= 0:
            raise ValueError(f"waypoint_range[{i}] must be positive, got {v}")
        out.append(float(v))

    if len(out) > 1:
        steps = [b - a for a, b in zip(out, out[1:])]
        if any(step > 0 for step in steps) and any(step < 0 for step in steps):
            raise ValueError(
                "waypoint_range must run one way, outermost to innermost or "
                f"the reverse; got {out}")
        if any(step == 0 for step in steps):
            raise ValueError(f"waypoint_range has a repeated standoff: {out}")
    return tuple(out)


def corridor_descends(corridor: tuple[float, ...]) -> bool:
    """True when the corridor is written outermost first, as spec 2 asks."""
    return len(corridor) < 2 or corridor[0] > corridor[-1]


@st.cache_data(show_spinner=False)
def _read_sidecar(path_str: str, mtime: float) -> dict:
    """Parse one sidecar. Cached on path + mtime, so an edited file is re-read.

    `mtime` is unused in the body and present only as a cache key -- that is
    deliberate, not an oversight.
    """
    del mtime
    raw = json.loads(Path(path_str).read_text())
    if not isinstance(raw, dict):
        raise ValueError("sidecar must be a JSON object")
    for key in ("utc_start_time", "waypoint_range"):
        if key not in raw:
            raise ValueError(f"missing '{key}'")
    return {
        "utc_start": parse_utc(raw["utc_start_time"]),
        "waypoint_range_m": parse_corridor(raw["waypoint_range"]),
        # Optional: sidecars written before the field must keep loading.
        "tolerance": (parse_tolerance(raw["tolerance"])
                      if "tolerance" in raw else None),
    }


def scan(runs_dir: Path | None = None) -> list[RunRecord]:
    """Every candidate run in `runs_dir`, sorted by name.

    Keyed on the JSON stem per spec 1, with orphaned CSVs appended so a run
    whose sidecar was never written is visible rather than absent.
    """
    directory = Path(runs_dir or config.RUNS_DIR)
    if not directory.is_dir():
        return []

    json_stems = {p.stem: p for p in sorted(directory.glob("*.json"))}
    csv_stems = {p.stem: p for p in sorted(directory.glob("*.csv"))}

    records: list[RunRecord] = []

    for stem, json_path in json_stems.items():
        csv_path = csv_stems.get(stem)
        if csv_path is None:
            records.append(RunRecord(
                stem=stem, csv_path=None, json_path=json_path, available=False,
                reason=f"no matching {stem}.csv",
            ))
            continue
        try:
            meta = _read_sidecar(str(json_path), json_path.stat().st_mtime)
        except Exception as exc:  # noqa: BLE001 -- the reason is the payload
            records.append(RunRecord(
                stem=stem, csv_path=csv_path, json_path=json_path, available=False,
                reason=f"{stem}.json: {exc}",
            ))
            continue
        records.append(RunRecord(
            stem=stem, csv_path=csv_path, json_path=json_path, available=True,
            utc_start=meta["utc_start"],
            waypoint_range_m=meta["waypoint_range_m"],
            tolerance=meta["tolerance"],
            csv_bytes=csv_path.stat().st_size,
            mtime=max(csv_path.stat().st_mtime, json_path.stat().st_mtime),
        ))

    for stem, csv_path in csv_stems.items():
        if stem not in json_stems:
            records.append(RunRecord(
                stem=stem, csv_path=csv_path, json_path=None, available=False,
                reason=f"no matching {stem}.json sidecar",
                csv_bytes=csv_path.stat().st_size,
            ))

    return sorted(records, key=lambda r: r.stem)


def find(stem: str, runs_dir: Path | None = None) -> RunRecord | None:
    """The record for one stem, or None if it is no longer on disk."""
    return next((r for r in scan(runs_dir) if r.stem == stem), None)
