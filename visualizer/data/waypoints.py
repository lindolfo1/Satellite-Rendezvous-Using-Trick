"""Where the waypoints are, and when the chaser has been in them.

A waypoint is a **place**, not a range. It sits on the V-bar at its standoff
behind the target -- along the target's velocity, opposite in direction -- and
carries a ball of `|tolerance x standoff|` around it. Reaching one means being
inside that ball.

Both of the readings this replaced were wrong in ways that looked plausible:

* **By range.** A chaser at 757.5 m of range is at the 750 m standoff, but if it
  is 9 m off the V-bar it is 11.7 m from the waypoint itself -- outside a 7.5 m
  ball. Range turns the sphere green while the vehicle is still flying to it.
* **By `currentWaypoint`.** That needs the index base and the naming convention
  to both be right, and they are not separable: an index counting the waypoint
  being *approached* spans 1..N, exactly like a 1-based index counting the last
  one *reached*. Guessing wrong makes the panel name the next waypoint while the
  current one is still ahead.

Measuring the geometry needs neither.
"""

from __future__ import annotations

import numpy as np


def centre_distances(chaser_pos_eci: np.ndarray,
                     target_pos_eci: np.ndarray,
                     target_vel_eci: np.ndarray,
                     corridor_m: np.ndarray) -> np.ndarray:
    """(N, K) distance from the chaser to each waypoint's centre, metres."""
    v_hat = target_vel_eci / np.linalg.norm(target_vel_eci, axis=1, keepdims=True)
    from_target = chaser_pos_eci - target_pos_eci
    # chaser - (target - standoff * v_hat), for every standoff at once.
    offsets = (from_target[:, None, :]
               + np.asarray(corridor_m)[None, :, None] * v_hat[:, None, :])
    return np.linalg.norm(offsets, axis=2)


def entry_state(distance_m: np.ndarray, corridor_m: np.ndarray,
                tolerance: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Latching entry flags, the waypoint being flown to, and the gap to it.

    Entry latches: a waypoint stays reached once entered, even if the chaser
    drifts back out. The one being flown to is the outermost not yet entered,
    which is `-1` once every waypoint has been visited.
    """
    corridor = np.asarray(corridor_m, dtype=np.float64)
    radii = np.abs(tolerance * corridor)

    entered = np.logical_or.accumulate(distance_m <= radii[None, :], axis=0)

    order = np.argsort(-corridor)              # widest standoff first
    pending = ~entered[:, order]
    has_pending = pending.any(axis=1)
    target = np.where(has_pending, order[np.argmax(pending, axis=1)], -1)
    gap = np.where(has_pending,
                   distance_m[np.arange(distance_m.shape[0]),
                              np.clip(target, 0, None)],
                   np.nan)
    return entered, target, gap
