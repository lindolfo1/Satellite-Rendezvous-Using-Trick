"""Burn segmentation, waypoint arrivals, and the unified event list.

Spec 4.4-4.6. One sorted, typed, labelled list feeds both the timeline strip
and next/previous-event seeking, so the two can never disagree about what an
event is or when it happened.

Every event carries a **sample index** as its primary fact, with the time
derived from it. That is how the spec defines them -- a waypoint arrival *is*
the sample where `wp_current` changes -- and it also avoids a float32/float64
comparison trap on the renderer side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import config


@dataclass(frozen=True)
class BurnSegment:
    """One contiguous span of commanded thrust."""

    start_index: int
    end_index: int          # inclusive
    start_time: float
    end_time: float
    duration_s: float
    dv_mps: float
    mean_direction_eci: np.ndarray = field(repr=False)
    ignition_pos_eci: np.ndarray = field(repr=False)


@dataclass(frozen=True)
class WaypointArrival:
    """The sample at which `wp_current` incremented."""

    index: int
    time_s: float
    waypoint: int                     # 0-based, normalised by the loader
    corridor_range_m: float | None    # None once the corridor is complete
    true_range_m: float

    @property
    def complete(self) -> bool:
        return self.corridor_range_m is None


@dataclass(frozen=True)
class Event:
    """A timeline entry. `kind` is one of burn_start, burn_end, waypoint."""

    index: int
    time_s: float
    kind: str
    label: str
    detail: dict


def thrust_magnitude(thrust_acc_eci: np.ndarray) -> np.ndarray:
    return np.linalg.norm(thrust_acc_eci, axis=1)


def thrusting_mask(thrust_acc_eci: np.ndarray,
                   eps: float = config.THRUST_EPS) -> np.ndarray:
    return thrust_magnitude(thrust_acc_eci) > eps


def _spans(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs for each contiguous True run."""
    if not mask.any():
        return []
    padded = np.concatenate([[False], mask, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b - 1)) for a, b in zip(edges[::2], edges[1::2])]


def segment_burns(time_s: np.ndarray, thrust_acc_eci: np.ndarray,
                  eps: float = config.THRUST_EPS) -> list[BurnSegment]:
    """Contiguous runs where |thrust_acc_eci| exceeds `eps` (spec 4.4).

    Delta-V integrates over the segment **plus the bracketing samples**, and
    that detail is load-bearing. A thruster turning on is discontinuous: in real
    output the magnitude goes from ~0 to its full value between two adjacent
    samples. Integrating only over samples above `eps` therefore drops the half
    interval of ramp at each boundary -- worth 0.115 m/s out of 41 m/s, or 0.3%,
    on the synthetic run, which is far too large to write off as integration
    error and is exactly the size of discrepancy that makes a cross-check
    against the sim useless.

    The bracketing samples are below `eps` by construction, so they add nothing
    but the boundary intervals, and two burns sharing a coast sample cannot
    meaningfully double-count.

    Start and end *times* remain the first and last samples above `eps`, so a
    segment's duration is marginally shorter than the span its delta-V covers.
    """
    magnitude = thrust_magnitude(thrust_acc_eci)
    burns: list[BurnSegment] = []

    last = time_s.size - 1
    for start, end in _spans(magnitude > eps):
        lo, hi = max(0, start - 1), min(last, end + 1)
        times = time_s[lo:hi + 1]
        mags = magnitude[lo:hi + 1]
        dv = float(np.trapezoid(mags, times)) if times.size > 1 else 0.0

        # Mean direction, weighted by acceleration so a long low-thrust tail
        # cannot outvote the part of the burn that did the work.
        weighted = np.sum(thrust_acc_eci[start:end + 1], axis=0)
        norm = np.linalg.norm(weighted)
        direction = weighted / norm if norm > 0 else np.zeros(3)

        burns.append(BurnSegment(
            start_index=start,
            end_index=end,
            start_time=float(time_s[start]),
            end_time=float(time_s[end]),
            duration_s=float(time_s[end] - time_s[start]),
            dv_mps=dv,
            mean_direction_eci=direction,
            ignition_pos_eci=np.zeros(3),  # filled by `build` from the run
        ))
    return burns


def waypoint_arrivals(time_s: np.ndarray, wp_current: np.ndarray,
                      waypoint_range_m: tuple[float, ...],
                      true_range: np.ndarray) -> list[WaypointArrival]:
    """Samples where the normalised waypoint index changes (spec 4.5).

    The first sample is not an arrival: the run starts *at* some waypoint, and
    reporting that as an arrival would put a spurious event at t = 0.
    """
    if wp_current.size < 2:
        return []
    changed = np.flatnonzero(wp_current[1:] != wp_current[:-1]) + 1

    arrivals: list[WaypointArrival] = []
    for index in changed:
        reached = int(round(float(wp_current[index])))
        in_corridor = 0 <= reached < len(waypoint_range_m)
        arrivals.append(WaypointArrival(
            index=int(index),
            time_s=float(time_s[index]),
            waypoint=reached,
            corridor_range_m=waypoint_range_m[reached] if in_corridor else None,
            true_range_m=float(true_range[index]),
        ))
    return arrivals


def detect_waypoint_convention(wp_current: np.ndarray,
                               waypoint_range_m: tuple[float, ...],
                               true_range: np.ndarray) -> int:
    """0 if `wp_current` names the waypoint being approached, 1 if the last reached.

    Spec 3.5 assumes the former and computes `true_range - waypoint_range[wp]`.
    The real output does the latter: it starts at 1000 m with `wp_current = 0`
    against a corridor whose first entry *is* 1000 m. Under the spec's reading
    the distance-to-go then reads 0 while holding and counts down to -750 during
    the transfer -- backwards, and zero exactly when there is furthest to go.

    Two tests, in order.

    First, non-negativity: you approach a waypoint from outside it, so the
    distance to go cannot be negative. That rejects a reading outright.

    Then the decisive one: **at the sample before `wp_current` changes, the
    chaser is at the standoff it was approaching**, so the distance to go is
    about zero there. Non-negativity alone is not enough -- a run that holds at
    each waypoint satisfies it under either reading, the tie falls to whichever
    was tried first, and the corridor then advances a waypoint early. That is
    visible as the ball being approached already marked complete.

    The offset may also be **-1**. Spec 2 asks for the corridor outermost first,
    but a file written innermost first indexes the other way: closing in then
    means walking *down* the array, not up. Searching -1 as well costs nothing
    and covers both orderings without reordering the array, which would break
    every `currentWaypoint` lookup.
    """
    corridor = np.asarray(waypoint_range_m, dtype=np.float64)
    index = np.rint(wp_current).astype(int)

    # The sample before each change of waypoint: the arrival itself.
    changed = np.flatnonzero(np.diff(index) != 0)

    candidates = []
    for offset in (0, 1, -1):
        shifted = index + offset
        inside = (shifted >= 0) & (shifted < corridor.size)
        if not inside.any():
            continue
        distance = true_range[inside] - corridor[shifted[inside]]
        non_negative = float(np.mean(distance >= -1e-6))

        if changed.size:
            at_arrival = changed[inside[changed]]
            residual = (float(np.median(np.abs(
                true_range[at_arrival] - corridor[shifted[at_arrival]])))
                if at_arrival.size else np.inf)
        else:
            residual = np.inf
        candidates.append((offset, non_negative, residual))

    if not candidates:
        return 0

    # Readings that never send the chaser inside its own target, best first by
    # how closely each arrival lands on the standoff it was aiming for.
    clean = [c for c in candidates if c[1] > 0.999]
    pool = clean or candidates
    pool.sort(key=lambda c: (c[2], -c[1]))
    return pool[0][0]


def build_event_list(burns: list[BurnSegment],
                     arrivals: list[WaypointArrival]) -> list[Event]:
    """One sorted list feeding both the timeline and event seeking (spec 4.6)."""
    events: list[Event] = []

    for n, burn in enumerate(burns, start=1):
        events.append(Event(
            index=burn.start_index, time_s=burn.start_time, kind="burn_start",
            label=f"Burn {n} start · {burn.dv_mps:.3f} m/s",
            detail={"burn": n, "dv_mps": burn.dv_mps,
                    "duration_s": burn.duration_s},
        ))
        events.append(Event(
            index=burn.end_index, time_s=burn.end_time, kind="burn_end",
            label=f"Burn {n} end · {burn.duration_s:.1f} s",
            detail={"burn": n, "dv_mps": burn.dv_mps,
                    "duration_s": burn.duration_s},
        ))

    for arrival in arrivals:
        if arrival.complete:
            label = "Corridor complete"
        else:
            label = f"Waypoint {arrival.waypoint} · {arrival.corridor_range_m:g} m"
        events.append(Event(
            index=arrival.index, time_s=arrival.time_s, kind="waypoint",
            label=label,
            detail={"waypoint": arrival.waypoint,
                    "corridor_range_m": arrival.corridor_range_m,
                    "true_range_m": arrival.true_range_m},
        ))

    events.sort(key=lambda e: (e.index, e.kind))
    return events


def next_event_index(events: list[Event], index: int, direction: int) -> int | None:
    """The sample index of the next or previous event, or None at the ends."""
    if direction > 0:
        found = next((e for e in events if e.index > index), None)
    else:
        found = next((e for e in reversed(events) if e.index < index), None)
    return None if found is None else found.index
