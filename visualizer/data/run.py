"""The `Run` dataclass: raw arrays, sidecar metadata, and derived arrays.

Spec 4. Everything the UI needs is computed once here at load time and cached.
No panel and no view computes derived data -- if they need a number, it comes
from a `Run` field or a helper in `core/`.

Stage 4 adds items 1-2 of spec 4: relative state in ECI and body, true range,
and true rangefinder range/azimuth/elevation. Events, error series and Earth
orientation follow in Stages 5-6.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import numpy as np

import config
from core import earth as earth_module
from core import frames
from core import geometry
from data import errors as errors_module
from data import relnav as relnav_module
from data import waypoints as waypoints_module
from data import attnav as attnav_module
from data import events as events_module
from data.loader import RawRun


@dataclass
class Run:
    """A loaded run with its derived geometry. Constructed by `build`."""

    raw: RawRun

    # --- body frames (spec 3.4) -------------------------------------------
    chaser_ex: np.ndarray
    chaser_ey: np.ndarray
    chaser_ez: np.ndarray
    target_ex: np.ndarray
    target_ey: np.ndarray
    target_ez: np.ndarray
    chaser_quat: np.ndarray  # (N, 4) xyzw, for the renderer only
    target_quat: np.ndarray

    # --- true relative state (spec 4.1) -----------------------------------
    rel_pos_eci: np.ndarray
    rel_pos_body: np.ndarray
    true_range: np.ndarray

    # --- true rangefinder values (spec 4.2) -------------------------------
    az_true: np.ndarray
    el_true: np.ndarray

    # --- burns, arrivals, and the one event list (spec 4.4-4.6) -----------
    thrust_mag: np.ndarray
    thrusting: np.ndarray
    burns: list = field(default_factory=list)
    arrivals: list = field(default_factory=list)
    events: list = field(default_factory=list)

    # --- error series and validity (spec 4.7-4.8) -------------------------
    range_err: np.ndarray | None = None
    range_err_pct: np.ndarray | None = None
    az_err: np.ndarray | None = None
    az_err_mrad: np.ndarray | None = None
    el_err: np.ndarray | None = None
    el_err_mrad: np.ndarray | None = None
    dv_body_true: np.ndarray | None = None
    dv_body_err: np.ndarray | None = None
    dv_err_mag: np.ndarray | None = None
    dv_err_pct: np.ndarray | None = None
    imu_last_valid: np.ndarray | None = None
    rf_last_valid: np.ndarray | None = None

    #: Index of the waypoint being approached, or -1 past the last one. This is
    #: `wp_current` shifted by the detected convention, not `wp_current` itself.
    wp_target: np.ndarray | None = None

    #: True range minus the standoff of the waypoint being approached
    #: (spec 3.5). NaN once the corridor is complete.
    wp_distance_m: np.ndarray | None = None

    #: 0 if `wp_current` named the waypoint being approached, 1 if it named the
    #: last one reached. Surfaced in the status panel beside the index base.
    #: Used for arrival *events* only -- the sim's own index says when it
    #: switched. Which waypoint is being flown to is measured instead; see
    #: `wp_entered`.
    wp_convention: int = 0

    #: Per sample, per waypoint: has the chaser been inside this waypoint's
    #: tolerance ball at any time up to now? Latching, so a waypoint stays
    #: reached once entered even if the chaser drifts back out.
    wp_entered: np.ndarray | None = None
    #: Distance from the chaser to each waypoint's centre, metres.
    wp_centre_distance_m: np.ndarray | None = None

    #: Distance to the nearest waypoint the chaser has not yet entered, metres,
    #: or NaN once every one has been. This is what "still to fly" means: a
    #: waypoint already visited is not something to slow down for, and holding
    #: at the innermost one is not an approach.
    wp_pending_m: np.ndarray | None = None

    #: Distance to the *nearest* waypoint centre, metres. Continuous where the
    #: distance to the one being flown to is not: the moment a waypoint is
    #: reached the target index advances and that gap jumps from nothing to the
    #: whole next leg. Anything pacing itself on proximity needs this one.
    wp_nearest_m: np.ndarray | None = None

    # --- relative-navigation estimate (optional column) -------------------
    #: Which reading of `xHat[0:3]` fits the run's geometry, or None when the
    #: column is absent. See data/relnav.py.
    relnav_fit: object | None = None
    #: Where the chaser believes it is, ECI metres. None when unrecognised.
    relnav_est_eci: np.ndarray | None = None
    relnav_err_eci: np.ndarray | None = None
    relnav_err_m: np.ndarray | None = None
    relnav_est_lvlh: np.ndarray | None = None

    # --- attitude estimate (optional attNav.qHat column) ------------------
    #: Which reading of `qHat` the data supports; see data/attnav.py.
    attnav_fit: object | None = None
    #: Believed body->ECI attitude, xyzw, or None when the column is absent.
    attnav_quat: np.ndarray | None = None
    #: Angle between the believed attitude and the true one, radians.
    attnav_err_rad: np.ndarray | None = None
    #: That error as a rotation vector on the chaser's R, V, H axes, radians.
    attnav_err_rvh: np.ndarray | None = None

    @property
    def has_attnav(self) -> bool:
        return self.attnav_quat is not None
    #: Believed body attitude, xyzw quaternions: the chaser's LVLH triad
    #: rotated by the filter's leftover attitude error.
    relnav_quat: np.ndarray | None = None
    relnav_att_err: np.ndarray | None = None      # (N, 3) rad, target LVLH
    relnav_att_err_rad: np.ndarray | None = None  # (N,) magnitude

    @property
    def has_relnav(self) -> bool:
        return self.relnav_est_eci is not None

    #: Orbital period of the target, seconds. From the vis-viva energy rather
    #: than the radius, so it is right for an eccentric orbit too.
    orbit_period_s: float = 0.0

    #: Closing speed, metres per second: positive while the gap is shrinking.
    #: The rate of change of the separation, which is the radial component of
    #: the relative velocity -- not the magnitude of that velocity, most of
    #: which is along-track and does not close anything.
    closing_rate_m_s: np.ndarray | None = None

    #: True where the chaser-target sight line clears the Earth (spec 9c).
    los_clear: np.ndarray | None = None

    #: The **chaser's** position relative to the target, resolved in the
    #: target's LVLH: (R, V, H) = radial, along-track, orbit normal.
    #:
    #: Note the sense. `rel_pos_eci` is target minus chaser, which is what the
    #: rangefinder needs -- the bearing *from* the chaser *to* the target. A
    #: relative-motion plot is the other way round: where the chaser sits in the
    #: target's frame. A chaser trailing by a kilometre reads V = -1000 m, on
    #: the negative V-bar, which is the convention.
    rel_lvlh: np.ndarray | None = None

    #: Angle between the chaser's LVLH and the target's, microradians. About
    #: 145 urad at 1 km separation -- 0.008 degrees, invisible on screen.
    lvlh_angle_urad: np.ndarray | None = None

    # --- Earth orientation (spec 5, 6) ------------------------------------
    julian_date: np.ndarray | None = None
    gmst: np.ndarray | None = None
    chaser_lat_deg: np.ndarray | None = None
    chaser_lon_deg: np.ndarray | None = None
    chaser_alt_m: np.ndarray | None = None
    target_lat_deg: np.ndarray | None = None
    target_lon_deg: np.ndarray | None = None
    target_alt_m: np.ndarray | None = None

    # Convenience passthroughs, so panels never reach into `raw`.
    @property
    def n(self) -> int:
        return self.raw.n

    @property
    def stem(self) -> str:
        return self.raw.stem

    @property
    def time_s(self) -> np.ndarray:
        return self.raw.time_s

    @property
    def utc_start(self) -> datetime:
        return self.raw.utc_start

    @property
    def waypoint_range_m(self) -> tuple[float, ...]:
        return self.raw.waypoint_range_m

    @property
    def tolerance(self) -> float | None:
        return self.raw.tolerance

    @property
    def duration_s(self) -> float:
        return self.raw.duration_s

    @property
    def csv_path(self) -> Path:
        return self.raw.csv_path

    @property
    def total_dv_mps(self) -> float:
        """Sum of the segment delta-Vs. Compare against `dv_accumulated`."""
        return float(sum(b.dv_mps for b in self.burns))

    @property
    def dv_accumulated_final(self) -> float:
        return float(self.raw.dv_accumulated[-1]) if self.n else 0.0


def build(raw: RawRun) -> Run:
    """Compute every derived array for a loaded run. Called once, at load."""
    c_ex, c_ey, c_ez = frames.lvlh_frame(raw.chaser_pos_eci, raw.chaser_vel_eci)
    t_ex, t_ey, t_ez = frames.lvlh_frame(raw.target_pos_eci, raw.target_vel_eci)

    rel_pos_eci = raw.target_pos_eci - raw.chaser_pos_eci
    rel_pos_body = frames.to_body(rel_pos_eci, c_ex, c_ey, c_ez)
    true_range = np.linalg.norm(rel_pos_eci, axis=1)

    # Sensor axes: x radial, y along-track, z orbit normal. `rel_pos_body` is
    # in the internal (ex, ey, ez) order, so the components are permuted here
    # rather than by rebuilding the frame.
    bx = rel_pos_body[:, 2]    # radial
    by = rel_pos_body[:, 0]    # along-track
    bz = rel_pos_body[:, 1]    # orbit normal
    az_true = np.arctan2(by, bx)
    # Guarded division: a zero range would be a coincident pair, which is not
    # physical, but NaN here would propagate into the error series in Stage 5.
    safe = np.where(true_range > 0, true_range, 1.0)
    el_true = np.arcsin(np.clip(bz / safe, -1.0, 1.0))

    thrust_mag = events_module.thrust_magnitude(raw.thrust_acc_eci)
    thrusting = thrust_mag > config.THRUST_EPS

    burns = events_module.segment_burns(raw.time_s, raw.thrust_acc_eci)
    # The ignition position is a property of the run, not of the segmentation,
    # so it is filled here rather than threading positions into events.py.
    burns = [
        replace(b, ignition_pos_eci=raw.chaser_pos_eci[b.start_index])
        for b in burns
    ]
    arrivals = events_module.waypoint_arrivals(
        raw.time_s, raw.wp_current, raw.waypoint_range_m, true_range)

    # Distance to the waypoint being approached (spec 3.5). Which index that is
    # depends on the sim's convention, so it is detected rather than assumed --
    # see events.detect_waypoint_convention. Out-of-corridor indices mean
    # "complete" and get NaN, not a wrapped lookup.
    # The convention is still detected, but only so arrival *events* can be
    # read from the sim's own index. Which waypoint is being flown to is
    # measured from the geometry below, because the index cannot always answer
    # it: an index counting the waypoint being approached spans 1..N, which is
    # indistinguishable from a 1-based index counting the last one reached.
    corridor = np.asarray(raw.waypoint_range_m, dtype=np.float64)
    convention = events_module.detect_waypoint_convention(
        raw.wp_current, raw.waypoint_range_m, true_range)

    # Chaser relative to target, resolved in the target's LVLH (R, V, H).
    chaser_from_target = -rel_pos_eci
    rel_lvlh = np.stack([
        np.sum(chaser_from_target * t_ez, axis=1),   # radial
        np.sum(chaser_from_target * t_ex, axis=1),   # along-track
        np.sum(chaser_from_target * t_ey, axis=1),   # orbit normal
    ], axis=1)
    # How far apart the two LVLH frames actually are, so "it looks like the
    # chaser's" can be answered with a number instead of an argument.
    cos_angle = np.clip(np.sum(c_ez * t_ez, axis=1), -1.0, 1.0)
    lvlh_angle_urad = np.arccos(cos_angle) * 1e6

    # ---- waypoints as places, measured rather than indexed ---------------
    #
    # A waypoint sits on the V-bar at its standoff behind the target, with a
    # ball of |tolerance x standoff| around it. Reaching one means being inside
    # that ball -- not merely at that range, which the chaser can satisfy while
    # off the V-bar entirely, and not what `currentWaypoint` says, whose index
    # base and naming convention are not always separable.
    corridor = np.asarray(raw.waypoint_range_m, dtype=np.float64)
    tolerance = (raw.tolerance if raw.tolerance is not None
                 else config.DEFAULT_TOLERANCE_ASSUMED)

    wp_centre_distance_m = waypoints_module.centre_distances(
        raw.chaser_pos_eci, raw.target_pos_eci, raw.target_vel_eci, corridor)
    wp_entered, wp_target, wp_distance_m = waypoints_module.entry_state(
        wp_centre_distance_m, corridor, tolerance)
    wp_nearest_m = wp_centre_distance_m.min(axis=1)
    pending = np.where(wp_entered, np.inf, wp_centre_distance_m)
    wp_pending_m = pending.min(axis=1)
    wp_pending_m = np.where(np.isfinite(wp_pending_m), wp_pending_m, np.nan)

    # a = 1 / (2/r - v^2/mu), then Kepler's third law.
    radius = np.linalg.norm(raw.target_pos_eci, axis=1)
    speed_sq = np.sum(raw.target_vel_eci ** 2, axis=1)
    inverse_a = 2.0 / radius - speed_sq / earth_module.MU
    semi_major = float(np.median(1.0 / inverse_a))
    orbit_period_s = float(
        2 * np.pi * np.sqrt(semi_major ** 3 / earth_module.MU)) if semi_major > 0 else 0.0

    rel_vel_eci = raw.target_vel_eci - raw.chaser_vel_eci
    closing_rate_m_s = -np.sum(rel_pos_eci * rel_vel_eci, axis=1) / np.maximum(
        true_range, 1e-9)

    run = Run(
        raw=raw,
        chaser_ex=c_ex, chaser_ey=c_ey, chaser_ez=c_ez,
        target_ex=t_ex, target_ey=t_ey, target_ez=t_ez,
        chaser_quat=frames.triad_quaternion(c_ex, c_ey, c_ez),
        target_quat=frames.triad_quaternion(t_ex, t_ey, t_ez),
        rel_pos_eci=rel_pos_eci,
        rel_pos_body=rel_pos_body,
        true_range=true_range,
        az_true=az_true,
        el_true=el_true,
        thrust_mag=thrust_mag,
        thrusting=thrusting,
        burns=burns,
        arrivals=arrivals,
        events=events_module.build_event_list(burns, arrivals),
        rel_lvlh=rel_lvlh,
        lvlh_angle_urad=lvlh_angle_urad,
        closing_rate_m_s=closing_rate_m_s,
        orbit_period_s=orbit_period_s,
        los_clear=geometry.los_clear(raw.chaser_pos_eci, raw.target_pos_eci,
                                     earth_module.EARTH_RADIUS_M),
        wp_target=wp_target,
        wp_entered=wp_entered,
        wp_centre_distance_m=wp_centre_distance_m,
        wp_nearest_m=wp_nearest_m,
        wp_pending_m=wp_pending_m,
        wp_distance_m=wp_distance_m,
        wp_convention=convention,
    )

    for name, values in errors_module.build(run).items():
        setattr(run, name, values)
    for name, values in attnav_module.build(run).items():
        setattr(run, name, values)
    for name, values in relnav_module.build(run).items():
        setattr(run, name, values)
    for name, values in earth_module.build(
        raw.utc_start, raw.time_s, raw.chaser_pos_eci, raw.target_pos_eci
    ).items():
        setattr(run, name, values)
    return run
