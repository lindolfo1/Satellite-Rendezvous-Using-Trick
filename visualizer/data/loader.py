"""`load_run(record) -> RawRun`: header parsing, unit validation, sidecar.

Spec 2, 3. Parses the Trick header by column **name**. The interleaving of
position and velocity components is incidental and may change between runs, so
nothing here may depend on column order -- confirmed against real output, where
the columns arrive as target pos/vel alternating, then chaser pos/vel
alternating, then thrustAcc/dVel alternating.

Every unit is validated against the expected unit for that variable. The check
is free and catches a rebuilt sim silently switching to kilometres, which would
otherwise surface as an orbit a thousand times too large.

Returns raw arrays plus sidecar metadata -- no derived quantities. Those are
Stage 4's job, in `data/run.py`.

Together with `discovery.py`, this is one of only two modules that change when
the input file format changes (acceptance criterion 11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from data import discovery

# --------------------------------------------------------------------------
# Column contract (spec 3.2)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """One variable: its Trick name, internal name, expected unit, and width."""

    trick: str
    internal: str
    unit: str
    dim: int = 1  # 3 => arrives as name[0..2] and lands as an (N, 3) array
    boolean: bool = False

    #: A column the run may or may not carry. Absent is not an error; the
    #: feature that needs it simply switches off.
    optional: bool = False

    #: Per-element units, for arrays whose entries are not all the same
    #: quantity. `unit` is then ignored and each element is checked against
    #: this map, with anything unlisted accepted as-is.
    element_units: dict | None = None

    #: Former names for the same variable. The simulation moves things between
    #: modules -- thrust from `sat` to `thruster`, accumulated delta-V from
    #: `guidance` to `thruster` -- and a rename should not strand every run
    #: recorded before it. Whichever name a file uses, it lands in the same
    #: place; a file carrying two names for one variable is an error rather
    #: than a guess.
    aliases: tuple = ()

    @property
    def all_names(self) -> tuple:
        return (self.trick,) + tuple(self.aliases)

    #: Elements 0..min_dim-1 are required; anything up to `dim` is taken if
    #: present and ignored if not. For an array whose tail is filter internals
    #: the sim may stop logging, a fixed width turns a harmless change into a
    #: hard load failure.
    min_dim: int | None = None

    @property
    def required_dim(self) -> int:
        return self.dim if self.min_dim is None else self.min_dim


COLUMN_SPECS: tuple[ColumnSpec, ...] = (
    ColumnSpec("sys.exec.out.time", "time_s", "s"),
    ColumnSpec("target.sat.pos_eci", "target_pos_eci", "m", 3),
    ColumnSpec("target.sat.vel_eci", "target_vel_eci", "m/s", 3),
    ColumnSpec("chaser.sat.pos_eci", "chaser_pos_eci", "m", 3),
    ColumnSpec("chaser.sat.vel_eci", "chaser_vel_eci", "m/s", 3),
    # Canonical name taken from real output, not from the data-recording
    # script: the script says `chaser.thruster.thrustAcc_eci`, the emitted
    # header says `chaser.sat.thruster.thrustAcc_eci`. Both are accepted, along
    # with the original `chaser.sat.thrustAcc_eci`, but the one the files
    # actually carry is the one named first.
    ColumnSpec("chaser.sat.thruster.thrustAcc_eci", "thrust_acc_eci", "m/s2", 3,
               aliases=("chaser.thruster.thrustAcc_eci",
                        "chaser.sat.thrustAcc_eci")),
    ColumnSpec("chaser.sat.imu.dVel", "imu_dvel_body", "m/s", 3),
    ColumnSpec("chaser.sat.imu.isValid", "imu_valid", "--", 1, True),
    ColumnSpec("chaser.sat.thruster.dVAccumulated", "dv_accumulated", "m/s",
               aliases=("chaser.sat.guidance.dVAccumulated",)),
    ColumnSpec("chaser.sat.guidance.currentWaypoint", "wp_current", "--"),
    ColumnSpec("chaser.sat.rangefinder.range", "rf_range", "m"),
    ColumnSpec("chaser.sat.rangefinder.azimuth", "rf_az", "rad"),
    ColumnSpec("chaser.sat.rangefinder.elevation", "rf_el", "rad"),
    ColumnSpec("chaser.sat.rangefinder.isValid", "rf_valid", "--", 1, True),

    # The attitude-navigation estimate: where the chaser believes it is
    # pointing, body to ECI. Optional, like the filter state.
    #
    # The component order is not stated anywhere -- `qHat[0..3]` is scalar-first
    # in much flight software and scalar-last in much graphics code -- so it is
    # measured on load rather than assumed. See data/attnav.py.
    ColumnSpec("chaser.sat.attNav.qHat", "attnav_qhat", "--", 4, optional=True),

    # The relative-navigation filter state. Optional: runs written before it
    # was added must keep loading.
    #
    # Twelve elements, and only the first six matter here: position, then
    # velocity. The remaining six are attitude error and gyro bias, carried
    # through and ignored. The units differ by element, so they are checked
    # per element rather than against one value for the whole array.
    ColumnSpec(
        "chaser.sat.relNav.xHat", "relnav_xhat", "", 12,
        optional=True,
        # Position and velocity are what this tool reads. The attitude error and
        # gyro bias that follow are filter internals; a run that stops logging
        # them must still load.
        min_dim=6,
        # Trick writes `{--}` for the whole array rather than a unit per
        # element, so dimensionless is accepted and read as SI. The explicit
        # units are still accepted, and `{km}` still rescales, so a sim that
        # starts declaring them is handled without another change here.
        element_units={
            0: ("--", "m", "km"), 1: ("--", "m", "km"), 2: ("--", "m", "km"),
            3: ("--", "m/s", "km/s"), 4: ("--", "m/s", "km/s"),
            5: ("--", "m/s", "km/s"),
        },
    ),
)

SPEC_BY_TRICK = {name: spec for spec in COLUMN_SPECS for name in spec.all_names}

#: `name[0] {unit}` / `name {unit}`, tolerating whitespace anywhere sane.
_CELL = re.compile(r"^\s*(?P<name>.*?)\s*\{\s*(?P<unit>[^}]*?)\s*\}\s*$")
_INDEX = re.compile(r"^(?P<base>.+?)\[(?P<idx>\d+)\]$")


class LoadError(RuntimeError):
    """Any hard load failure. The message names the specific problem."""


@dataclass
class RawRun:
    """Raw columns plus sidecar metadata. No derived quantities (spec 3)."""

    stem: str
    csv_path: Path
    utc_start: datetime
    waypoint_range_m: tuple[float, ...]
    tolerance: float | None

    time_s: np.ndarray = field(repr=False)
    target_pos_eci: np.ndarray = field(repr=False)
    target_vel_eci: np.ndarray = field(repr=False)
    chaser_pos_eci: np.ndarray = field(repr=False)
    chaser_vel_eci: np.ndarray = field(repr=False)
    thrust_acc_eci: np.ndarray = field(repr=False)
    imu_dvel_body: np.ndarray = field(repr=False)
    imu_valid: np.ndarray = field(repr=False)
    dv_accumulated: np.ndarray = field(repr=False)
    wp_current: np.ndarray = field(repr=False)
    rf_range: np.ndarray = field(repr=False)
    rf_az: np.ndarray = field(repr=False)
    rf_el: np.ndarray = field(repr=False)
    rf_valid: np.ndarray = field(repr=False)

    #: (N, 4) believed attitude quaternion, body to ECI, in the file's own
    #: component order. None when the run carries no such column.
    attnav_qhat: np.ndarray | None = field(default=None, repr=False)

    #: (N, 6) or wider relative-navigation filter state, or None when the run
    #: carries no such column. Elements 0-2 position, 3-5 velocity; anything
    #: beyond is attitude error and gyro bias, kept if logged. Units normalised
    #: to metres and m/s on load.
    relnav_xhat: np.ndarray | None = field(default=None, repr=False)

    wp_base_detected: int = 0
    wp_base_ambiguous: bool = False

    @property
    def n(self) -> int:
        return int(self.time_s.size)

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1] - self.time_s[0]) if self.n else 0.0

    @property
    def dt_stats(self) -> tuple[float, float, float]:
        """(min, median, max) sample spacing. Variable dt is allowed (spec 3.2)."""
        if self.n < 2:
            return (0.0, 0.0, 0.0)
        d = np.diff(self.time_s)
        return (float(d.min()), float(np.median(d)), float(d.max()))


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------


def parse_header(line: str) -> list[tuple[str, int | None, str]]:
    """Split a header line into (base name, component index, unit) per cell.

    A trailing comma produces an empty final cell, which is dropped rather than
    treated as a nameless column.
    """
    out: list[tuple[str, int | None, str]] = []
    for pos, cell in enumerate(line.rstrip("\r\n").split(",")):
        if not cell.strip():
            continue  # trailing comma, or padding
        match = _CELL.match(cell)
        if match is None:
            raise LoadError(
                f"header column {pos} ({cell.strip()!r}) has no {{unit}} suffix; "
                "expected Trick format like 'chaser.sat.pos_eci[0] {m}'"
            )
        name, unit = match.group("name"), match.group("unit")
        idx_match = _INDEX.match(name)
        if idx_match:
            out.append((idx_match.group("base"), int(idx_match.group("idx")), unit))
        else:
            out.append((name, None, unit))
    return out


def validate_and_map(cells: list[tuple[str, int | None, str]]) -> dict[str, list[int]]:
    """Map internal name -> the CSV column positions holding it.

    Raises on an unknown unit, a missing column, or a component that is absent
    or duplicated. Order is irrelevant throughout: everything is keyed by name.
    """
    found: dict[str, dict[int, int]] = {}
    seen_names: dict[str, str] = {}

    for pos, (base, idx, unit) in enumerate(cells):
        spec = SPEC_BY_TRICK.get(base)
        if spec is None:
            continue  # unknown column: ignored, not an error -- the sim may add fields
        component = 0 if idx is None else idx
        if spec.element_units is not None:
            allowed = spec.element_units.get(component)
            if allowed is not None and unit not in allowed:
                raise LoadError(
                    f"unit mismatch on '{base}[{component}]': file says "
                    f"{{{unit}}}, expected one of "
                    + ", ".join(f"{{{u}}}" for u in allowed)
                )
        elif unit != spec.unit:
            raise LoadError(
                f"unit mismatch on '{base}': file says {{{unit}}}, "
                f"expected {{{spec.unit}}}. A rebuilt sim may have changed units."
            )
        if spec.dim == 1 and idx is not None:
            raise LoadError(f"'{base}' is a scalar but arrived indexed as [{idx}]")
        if spec.dim == 3 and idx is None:
            raise LoadError(f"'{base}' is a 3-vector but arrived without [0..2]")
        if component >= spec.dim:
            raise LoadError(f"'{base}[{component}]' is out of range for a {spec.dim}-vector")
        slot = found.setdefault(spec.internal, {})
        if component in slot:
            previous = seen_names.get(spec.internal)
            if previous and previous != base:
                raise LoadError(
                    f"'{base}' and '{previous}' are two names for the same "
                    "variable and both appear; the file is ambiguous")
            raise LoadError(f"'{base}' component {component} appears more than once")
        slot[component] = pos
        seen_names[spec.internal] = base

    columns: dict[str, list[int]] = {}
    for spec in COLUMN_SPECS:
        slot = found.get(spec.internal)
        if slot is None:
            if spec.optional:
                continue
            names = " or ".join(f"'{n}'" for n in spec.all_names)
            raise LoadError(f"missing required column {names}")
        missing = [i for i in range(spec.required_dim) if i not in slot]
        if missing:
            names = ", ".join(f"{spec.trick}[{i}]" for i in missing)
            raise LoadError(f"missing required column(s): {names}")

        # Take the contiguous run from element 0: a gap ends the array rather
        # than silently shifting later elements into the wrong slot.
        width = spec.required_dim
        while width < spec.dim and width in slot:
            width += 1
        columns[spec.internal] = [slot[i] for i in range(width)]
    return columns


# --------------------------------------------------------------------------
# Body
# --------------------------------------------------------------------------


def coerce_bool(values: np.ndarray, column: str) -> np.ndarray:
    """Coerce a validity flag from 0/1, 0.0/1.0, or True/False (spec 3.1)."""
    if values.dtype == bool:
        return values
    if np.issubdtype(values.dtype, np.number):
        unique = np.unique(values[~np.isnan(values.astype(float))])
        bad = [v for v in unique if v not in (0.0, 1.0)]
        if bad:
            raise LoadError(f"'{column}' holds non-boolean values: {bad[:5]}")
        return values.astype(float) > 0.5
    text = pd.Series(values).astype(str).str.strip().str.lower()
    mapping = {"true": True, "false": False, "1": True, "0": False,
               "1.0": True, "0.0": False}
    unknown = sorted(set(text) - set(mapping))
    if unknown:
        raise LoadError(f"'{column}' holds unrecognised boolean values: {unknown[:5]}")
    return text.map(mapping).to_numpy(dtype=bool)


def detect_waypoint_base(wp: np.ndarray, corridor_len: int) -> tuple[int, bool]:
    """Infer the index base and normalise to 0-based (spec 3.3).

    Returns (base, ambiguous). Values outside both ranges mean "corridor
    complete" and are excluded from the inference rather than breaking it.
    """
    finite = wp[np.isfinite(wp)]
    inside = finite[(finite >= 0) & (finite <= corridor_len)]
    if inside.size == 0:
        return 0, True
    lo, hi = float(inside.min()), float(inside.max())
    if lo == 0:
        return 0, False  # a 0 can only be 0-based
    if hi == corridor_len:
        return 1, False  # a value equal to the length can only be 1-based
    # Everything observed sits in 1..len-1, which fits either reading. Assume
    # 0-based (the observed convention) and flag it so the status panel can say
    # the detection was ambiguous rather than implying certainty.
    return 0, True


def _read_frame(csv_path: Path, n_cols: int) -> pd.DataFrame:
    """Read the body: float64 where possible, whitespace and padding tolerated.

    The real output right-aligns every field with leading spaces, and not
    uniformly -- some columns are padded and some are not -- so
    `skipinitialspace` is load-bearing, not decoration.
    """
    try:
        frame = pd.read_csv(
            csv_path,
            skiprows=1,
            header=None,
            skipinitialspace=True,
            skip_blank_lines=True,
            usecols=range(n_cols),  # ignores the field a trailing comma adds
            low_memory=False,
        )
    except pd.errors.EmptyDataError as exc:
        # A header with no rows. pandas raises before we can look, so the
        # translation happens here -- every failure out of this module is a
        # LoadError with a readable reason, never a library traceback.
        raise LoadError(f"{csv_path.name} has a header but no data rows") from exc
    except pd.errors.ParserError as exc:
        raise LoadError(f"{csv_path.name} is malformed: {exc}") from exc
    if frame.empty:
        raise LoadError(f"{csv_path.name} has a header but no data rows")
    return frame


def load_raw(record: discovery.RunRecord) -> RawRun:
    """Load one run. Every failure is a `LoadError` naming the specific problem."""
    if not record.available:
        raise LoadError(f"{record.stem} is not available: {record.reason}")

    csv_path = Path(record.csv_path)
    with csv_path.open("r") as handle:
        header_line = handle.readline()
    if not header_line.strip():
        raise LoadError(f"{csv_path.name} is empty")

    cells = parse_header(header_line)
    columns = validate_and_map(cells)
    frame = _read_frame(csv_path, len(cells))

    def take(internal: str) -> np.ndarray:
        positions = columns[internal]
        block = frame.iloc[:, positions]
        if len(positions) == 1:
            return block.iloc[:, 0].to_numpy()
        return np.ascontiguousarray(block.to_numpy(dtype=np.float64))

    values: dict[str, np.ndarray] = {}
    for spec in COLUMN_SPECS:
        if spec.internal not in columns:
            values[spec.internal] = None      # optional, and this run lacks it
            continue
        raw = take(spec.internal)
        if spec.boolean:
            values[spec.internal] = coerce_bool(raw, spec.trick)
        elif spec.dim == 1:
            values[spec.internal] = raw.astype(np.float64)
        else:
            values[spec.internal] = raw

    time_s = values["time_s"]
    if time_s.size < 2:
        raise LoadError(f"{csv_path.name} has fewer than two samples")
    if np.any(np.diff(time_s) <= 0):
        first = int(np.argmax(np.diff(time_s) <= 0))
        raise LoadError(
            f"time is not strictly increasing at sample {first + 1} "
            f"({time_s[first]} -> {time_s[first + 1]})"
        )

    # Normalise the filter state's units: kilometres in the header become
    # metres here, so nothing downstream has to ask.
    if values["relnav_xhat"] is not None:
        by_position = {(0 if i is None else i): u for _, i, u in cells}
        scale = np.ones(values["relnav_xhat"].shape[1])
        for element in range(min(6, scale.size)):
            for pos_index, (b, i, u) in enumerate(cells):
                if b == "chaser.sat.relNav.xHat" and (i or 0) == element:
                    scale[element] = 1000.0 if u.startswith("km") else 1.0
        values["relnav_xhat"] = values["relnav_xhat"] * scale

    base, ambiguous = detect_waypoint_base(
        values["wp_current"], len(record.waypoint_range_m)
    )
    wp_normalised = values["wp_current"] - base

    return RawRun(
        stem=record.stem,
        csv_path=csv_path,
        utc_start=record.utc_start,
        waypoint_range_m=record.waypoint_range_m,
        tolerance=record.tolerance,
        time_s=time_s,
        target_pos_eci=values["target_pos_eci"],
        target_vel_eci=values["target_vel_eci"],
        chaser_pos_eci=values["chaser_pos_eci"],
        chaser_vel_eci=values["chaser_vel_eci"],
        thrust_acc_eci=values["thrust_acc_eci"],
        imu_dvel_body=values["imu_dvel_body"],
        imu_valid=values["imu_valid"],
        dv_accumulated=values["dv_accumulated"],
        wp_current=wp_normalised,
        rf_range=values["rf_range"],
        rf_az=values["rf_az"],
        rf_el=values["rf_el"],
        rf_valid=values["rf_valid"],
        relnav_xhat=values["relnav_xhat"],
        attnav_qhat=values["attnav_qhat"],
        wp_base_detected=base,
        wp_base_ambiguous=ambiguous,
    )


@st.cache_data(show_spinner="Loading run…", max_entries=4)
def load_run(stem: str, csv_mtime: float, json_mtime: float) -> RawRun:
    """Cached entry point. Keyed on path + mtime, so an overwritten file re-reads.

    `csv_mtime` and `json_mtime` are unused in the body and exist only as cache
    keys -- deliberate, not an oversight (spec 1).
    """
    del csv_mtime, json_mtime
    record = discovery.find(stem)
    if record is None:
        raise LoadError(f"run '{stem}' is no longer in the runs folder")
    return load_raw(record)
