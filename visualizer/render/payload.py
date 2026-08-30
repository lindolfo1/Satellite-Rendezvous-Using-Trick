"""Pack a `Run` into the interleaved float32 block the viewer decodes.

This module is the **only** place metres become kilometres.

WebGL stores vertex attributes as float32, which resolves 0.49 mm at a 6800 km
orbit radius when the geometry arrives in kilometres -- and 0.5 m if the same
geometry arrives in metres, which would swallow a 5 m separation whole. `data/`
and `core/` stay float64 SI per spec; the conversion happens here, once, and
nothing downstream may undo it.

Stage 1 packs nothing: `Run` does not exist until Stage 4. `empty()` returns
the metadata shape the viewer expects so the HUD and the camera can be built
and exercised against a real contract rather than a guess.
"""

from __future__ import annotations

# Precision note. `time_s` is packed float32 like everything else, which
# resolves ~1 ms at t = 10 000 s. That is fine for display and for integrating
# rate * wall_dt, and it is *not* fine for identifying an event -- hence
# EVENT_KEYS below.

import base64

import config
from core import earth

#: Events carry a sample INDEX (`i`), never a time.
#:
#: Sample times are float32 by the time the viewer sees them, while an event
#: time computed in `data/events.py` is float64. The two never compare equal, so
#: a time-keyed event list makes next-event seeking stick on the event it just
#: arrived at. Indices are exact. `js/40_clock.js` documents the same rule from
#: the other side; the two must not drift.
EVENT_KEYS = ("i", "kind", "label")

#: Interleaved column order. The viewer reads by this offset, so the two must
#: change together -- which is why the order lives here as data rather than
#: being implied by the packing code.
COLUMNS = (
    "time_s",
    "chaser_x_km", "chaser_y_km", "chaser_z_km",
    "target_x_km", "target_y_km", "target_z_km",
    # Body orientation as xyzw quaternions. Four floats instead of the nine a
    # triad would need, and the renderer applies them directly. The triad in
    # core/frames.py stays authoritative for everything computed.
    "chaser_qx", "chaser_qy", "chaser_qz", "chaser_qw",
    "target_qx", "target_qy", "target_qz", "target_qw",
    "dv_accumulated",
    "wp_current",
    "thrusting",
    # Earth orientation and ground tracks (spec 5, 6).
    "gmst_rad",
    # Position is reported as the sub-satellite point plus height above the
    # WGS84 ellipsoid, which is what "where is it" actually means for a
    # spacecraft. The ECI xyz spec 8 asks for is an orbit radius and three
    # numbers whose frame you have to remember; this is readable off a map.
    "chaser_lat_deg", "chaser_lon_deg", "chaser_alt_m",
    "target_lat_deg", "target_lon_deg", "target_alt_m",
    # Stats panel (spec 8). Velocity and thrust are in SI, not scene units:
    # they are read, never rendered, so there is no float32 headroom to buy.
    "chaser_vx", "chaser_vy", "chaser_vz",
    "target_vx", "target_vy", "target_vz",
    "thrust_ax", "thrust_ay", "thrust_az",
    # True range, packed rather than differenced from the two positions.
    # Positions are float32 kilometres, which resolve 0.49 m at orbit radius --
    # fine for drawing, useless for a separation the run ends at 1 m. Taking the
    # difference in float64 here and packing the small number keeps it exact.
    "true_range_m",
    # Relative position, target minus chaser, in METRES.
    #
    # The two absolute positions are float32 kilometres, quantised to 0.49 m
    # each and quantised *independently*, so their difference wanders by around
    # 0.12 m from one sample to the next. At orbital scale that is nothing; at
    # the 1 m separation this run ends on it is the whole signal, and it shows
    # up as the two vehicles shivering against each other.
    #
    # Packing the difference itself -- taken in float64, and small enough that
    # float32 resolves it to 3e-8 m -- fixes it at the source. The renderer then
    # places the target *relative to the chaser* rather than positioning both
    # absolutely and hoping the subtraction survives.
    "rel_x_m", "rel_y_m", "rel_z_m",
    # The waypoint being approached and how far there is left to it. Computed in
    # data/run.py because picking the right corridor entry needs the detected
    # convention, which is not something a display panel should be deciding.
    "wp_target", "wp_distance_m",
    # Sensors, for the arrows and the measured-vs-true readout (spec 9b).
    # Truth is packed alongside the measurement so the panel can show both; the
    # error is one subtraction of two comparable small numbers, which is
    # well-conditioned in a way the 6878 km positions were not.
    "imu_dvel_bx", "imu_dvel_by", "imu_dvel_bz",
    "dv_true_bx", "dv_true_by", "dv_true_bz",
    "imu_valid",
    "rf_range_m", "rf_az_rad", "rf_el_rad", "rf_valid",
    "az_true_rad", "el_true_rad",
    "los_clear",
    # Relative position in the target's LVLH -- R-bar, V-bar, H-bar -- and how
    # far the chaser's own LVLH is from the target's.
    "rel_r_m", "rel_v_m", "rel_h_m", "lvlh_angle_urad",
    # Low-order half of the chaser position, in kilometres.
    #
    # float32 resolves 0.49 m at a 6878 km orbit radius, so the packed position
    # is *already* on that grid before any vertex buffer sees it -- which is
    # what makes the drawn orbit tracks shimmer as they are rebuilt. Splitting
    # the value across two float32s (the double-single trick) and adding them
    # back in JS, where numbers are float64, reconstructs it to 3e-9 m. The
    # target's position needs no equivalent: it is this plus the exact relative
    # vector.
    "chaser_lo_x", "chaser_lo_y", "chaser_lo_z",
    # Relative-navigation estimate. Zero throughout when the run has no
    # `relNav.xHat`; `meta["relnav"]` says whether it is real.
    #
    # The *error* is packed rather than the estimated position: it is a
    # metre-scale number, so float32 resolves it to microns, where an absolute
    # estimate would land back on the 0.49 m grid. The ghost is drawn at the
    # true position plus this.
    "nav_err_x", "nav_err_y", "nav_err_z",
    # And the estimate as the relative-motion view needs it: chaser-believed
    # position relative to the target, in the target's LVLH.
    "nav_est_r", "nav_est_v", "nav_est_h",
    # Believed attitude: the chaser's own LVLH triad rotated by the filter's
    # leftover attitude error, xHat[6:9]. Packed as a quaternion so the
    # renderer applies it directly, exactly as the true attitude is.
    "nav_qx", "nav_qy", "nav_qz", "nav_qw",
    # And the error itself, for the readout: three components and a magnitude.
    "nav_att_r", "nav_att_v", "nav_att_h", "nav_att_rad",
    # Bitmask of waypoints entered so far, bit k for waypoint k. A waypoint is
    # entered when the chaser is inside its tolerance ball, which is not the
    # same as reaching that range: the chaser can sit at 751 m and still be 40 m
    # from the 750 m waypoint's centre if it is off the V-bar.
    "wp_entered_mask",
    # Believed attitude from attNav.qHat, as an xyzw quaternion in the reading
    # the data supports, plus the angle from the true attitude.
    "att_qx", "att_qy", "att_qz", "att_qw", "att_err_rad",
    # The same error as a rotation vector on the chaser's R, V, H axes: which
    # way the belief is tipped, not just how far.
    "att_err_r", "att_err_v", "att_err_h",
    # Closing speed, m/s: how fast the gap is shrinking, which is what an
    # approach is actually doing. Positive while closing.
    "closing_rate",
    # Distance to the nearest waypoint centre, metres. Continuous across an
    # arrival, where the distance to the waypoint being flown to is not.
    "wp_nearest_m",
    # And to the nearest one not yet entered: NaN once the corridor is done,
    # which is the signal that there is nothing left to slow down for.
    "wp_pending_m",
)
STRIDE = len(COLUMNS)

#: Offsets into a packed sample. Mirrored in js/00_state.js -- the two must
#: change together, so both name this constant in their comments.
OFFSETS = {
    "time": 0, "chaser_pos": 1, "target_pos": 4,
    "chaser_quat": 7, "target_quat": 11,
    "dv": 15, "wp": 16, "thrusting": 17,
    "gmst": 18, "chaser_llh": 19, "target_llh": 22,
    "chaser_vel": 25, "target_vel": 28, "thrust_acc": 31, "true_range": 34,
    "rel_pos": 35, "wp_target": 38, "wp_distance": 39,
    "imu_dvel": 40, "dv_true": 43, "imu_valid": 46,
    "rf_range": 47, "rf_az": 48, "rf_el": 49, "rf_valid": 50,
    "az_true": 51, "el_true": 52, "los_clear": 53,
    "rel_lvlh": 54, "lvlh_angle": 57, "chaser_pos_lo": 58,
    "nav_err": 61, "nav_est_lvlh": 64, "nav_quat": 67, "nav_att_err": 71,
    "nav_att_rad": 74, "wp_entered_mask": 75,
    "att_quat": 76, "att_err_rad": 80, "att_err_rvh": 81, "closing_rate": 84, "wp_nearest": 85, "wp_pending": 86,
}


def empty(record=None) -> tuple[str, dict]:  # noqa: ANN001 -- RunRecord
    """Metadata with no samples: the viewer renders its empty state.

    Passing a discovery record fills in what the sidecar already knows -- name,
    UTC start, corridor -- so the status panel is populated between selecting a
    run and Stage 3 being able to load it.
    """
    return "", {
        "n": 0,
        "stride": STRIDE,
        "columns": list(COLUMNS),
        "stem": getattr(record, "stem", None),
        # Epoch milliseconds too: the cinematic card stamps a wall-clock time,
        # and reparsing an ISO string in the browser every frame is work for
        # nothing.
        "utc_start_ms": (
            record.utc_start.timestamp() * 1000.0
            if record is not None and record.utc_start is not None else 0.0
        ),
        "utc_start": (
            record.utc_start.isoformat()
            if record is not None and record.utc_start is not None
            else None
        ),
        "wp_base": None,
        "waypoint_range_m": list(getattr(record, "waypoint_range_m", None) or []),
        "events": [],
        "pending": record is not None,
    }


def _peak(values, valid) -> float:  # noqa: ANN001
    """Largest magnitude over the samples a sensor called valid.

    Invalid samples can hold anything. Real output opens with an IMU delta-V of
    -1.6e9 m/s -- uninitialised memory, and flagged valid on that first sample
    into the bargain -- which as a peak would scale every other arrow to
    nothing. Falls back to the whole series only if nothing is ever valid, so a
    run with a dead sensor still produces a usable number.
    """
    import numpy as np

    magnitude = np.linalg.norm(values, axis=1) if values.ndim > 1 else np.abs(values)
    usable = magnitude[valid] if valid is not None and valid.any() else magnitude
    finite = usable[np.isfinite(usable)]
    return float(finite.max()) if finite.size else 0.0


def _arrow_maxima(run) -> dict:  # noqa: ANN001
    raw = run.raw
    return {
        "speed": _peak(raw.chaser_vel_eci, None),
        "thrust": _peak(raw.thrust_acc_eci, None),
        "imu_dv": _peak(raw.imu_dvel_body, raw.imu_valid),
        "range": _peak(run.true_range, raw.rf_valid),
    }


def pack(run) -> tuple[str, dict]:  # noqa: ANN001 -- data.run.Run
    """Pack a run into (base64 float32 block, metadata).

    Only raw columns are packed. The `thrusting` slot stays zero until Stage 5
    computes burn segmentation in `data/events.py` -- deriving it here would put
    physics in the render layer, which is the one rule the build plan holds at
    every stage.
    """
    import numpy as np

    raw = run.raw
    n = raw.n
    block = np.empty((n, STRIDE), dtype=np.float32)
    block[:, 0] = raw.time_s
    # The only metres-to-kilometres conversion in the project.
    block[:, 1:4] = raw.chaser_pos_eci * config.SCENE_UNITS_PER_METRE
    block[:, 4:7] = raw.target_pos_eci * config.SCENE_UNITS_PER_METRE
    block[:, 7:11] = run.chaser_quat
    block[:, 11:15] = run.target_quat
    block[:, 15] = raw.dv_accumulated
    block[:, 16] = raw.wp_current
    block[:, 17] = run.thrusting.astype(np.float32)
    block[:, 18] = run.gmst
    block[:, 19] = run.chaser_lat_deg
    block[:, 20] = run.chaser_lon_deg
    block[:, 21] = run.chaser_alt_m
    block[:, 22] = run.target_lat_deg
    block[:, 23] = run.target_lon_deg
    block[:, 24] = run.target_alt_m
    block[:, 25:28] = raw.chaser_vel_eci
    block[:, 28:31] = raw.target_vel_eci
    block[:, 31:34] = raw.thrust_acc_eci
    block[:, 34] = run.true_range
    block[:, 35:38] = run.rel_pos_eci
    block[:, 38] = run.wp_target
    block[:, 39] = run.wp_distance_m
    block[:, 40:43] = raw.imu_dvel_body
    block[:, 43:46] = run.dv_body_true
    block[:, 46] = raw.imu_valid
    block[:, 47] = raw.rf_range
    block[:, 48] = raw.rf_az
    block[:, 49] = raw.rf_el
    block[:, 50] = raw.rf_valid
    block[:, 51] = run.az_true
    block[:, 52] = run.el_true
    block[:, 53] = run.los_clear
    block[:, 54:57] = run.rel_lvlh
    block[:, 57] = run.lvlh_angle_urad

    # hi is already in block[:, 1:4]; lo is what float32 dropped.
    chaser_km = raw.chaser_pos_eci * config.SCENE_UNITS_PER_METRE
    block[:, 58:61] = chaser_km - block[:, 1:4].astype(np.float64)

    if run.has_attnav:
        block[:, OFFSETS["att_quat"]:OFFSETS["att_quat"] + 4] = run.attnav_quat
        block[:, OFFSETS["att_err_rad"]] = run.attnav_err_rad
        block[:, OFFSETS["att_err_rvh"]:OFFSETS["att_err_rvh"] + 3] = run.attnav_err_rvh
    else:
        # Identity, so a scene that draws it anyway shows the true attitude
        # rather than a degenerate rotation.
        block[:, OFFSETS["att_quat"] + 3] = 1.0

    block[:, OFFSETS["closing_rate"]] = run.closing_rate_m_s
    block[:, OFFSETS["wp_nearest"]] = run.wp_nearest_m
    block[:, OFFSETS["wp_pending"]] = run.wp_pending_m

    if run.wp_entered is not None:
        bits = (1 << np.arange(run.wp_entered.shape[1]))[None, :]
        block[:, OFFSETS["wp_entered_mask"]] = (run.wp_entered * bits).sum(axis=1)

    if run.has_relnav:
        block[:, 61:64] = run.relnav_err_eci
        block[:, 64:67] = run.relnav_est_lvlh
        block[:, 67:71] = run.relnav_quat
        block[:, 71:74] = run.relnav_att_err
        block[:, 74] = run.relnav_att_err_rad
    else:
        block[:, 61:75] = 0.0
        block[:, 70] = 1.0      # identity quaternion, so nothing is degenerate

    meta = {
        "n": n,
        "stride": STRIDE,
        "columns": list(COLUMNS),
        "offsets": OFFSETS,
        "stem": raw.stem,
        "utc_start": raw.utc_start.isoformat(),
        # Epoch milliseconds too: the cinematic card stamps a wall-clock time
        # every frame, and reparsing an ISO string 60 times a second is work
        # for nothing.
        "utc_start_ms": raw.utc_start.timestamp() * 1000.0,

        "wp_base": raw.wp_base_detected,
        "wp_convention": run.wp_convention,
        # None when the run carries no filter state. `consistent` false means
        # the estimate does not match the frame it is documented to be in, and
        # nothing is drawn -- a ghost placed with the wrong frame reads as a
        # navigation failure.
        "relnav": (
            {"frame": run.relnav_fit.label,
             # Metres, because that is what the panel reports. A fraction of
             # the separation was the previous wording and it misled: near
             # contact a healthy filter is a larger number than the gap.
             "residual_m": run.relnav_fit.residual_m,
             "reversed_residual_m": (run.relnav_fit.reversed_relative_error
                                     * run.relnav_fit.scale_m),
             "relative_error": run.relnav_fit.relative_error,
             "consistent": run.relnav_fit.consistent,
             "usable": run.relnav_fit.usable,
             "scale_m": run.relnav_fit.scale_m,
             "reversed_fits": run.relnav_fit.reversed_fits,
             "reversed_relative_error": run.relnav_fit.reversed_relative_error,
             "alternative": run.relnav_fit.alternative,
             "alternative_residual_m": run.relnav_fit.alternative_residual_m}
            if run.relnav_fit is not None else None
        ),
        "has_relnav": bool(run.has_relnav),
        "has_attnav": bool(run.has_attnav),
        "attnav": (
            {"reading": run.attnav_fit.label,
             "error_deg": float(np.degrees(run.attnav_fit.error_rad)),
             "other_deg": float(np.degrees(run.attnav_fit.best_other_rad)),
             "other": run.attnav_fit.best_other,
             "consistent": bool(run.attnav_fit.consistent)}
            if run.attnav_fit is not None else None
        ),
        # Per-quantity maxima for the "relative magnitude" arrow policy
        # (spec 9b). Velocity, thrust and delta-V are orders apart, so each is
        # normalised against its own peak rather than a shared scale.
        # Fixed-policy arrow length, as a fraction of the visible scene.
        # Sourced from config.py rather than duplicated in the JS, so there is
        # one place to tune it.
        "arrow_fixed_frac": config.ARROW_FIXED_FRAC,
        "imu_dvel_floor_fraction": config.IMU_DVEL_FLOOR_FRACTION,
        "arrow_max": _arrow_maxima(run),
        "wp_base_ambiguous": raw.wp_base_ambiguous,
        "waypoint_range_m": list(raw.waypoint_range_m),
        # A waypoint is a point on the V-bar with a ball of tolerance around
        # it, not a shell at that range from the target.
        "tolerance": (raw.tolerance if raw.tolerance is not None
                      else config.DEFAULT_TOLERANCE_ASSUMED),
        "tolerance_assumed": raw.tolerance is None,
        # Sample indices, never times -- see EVENT_KEYS above.
        "events": [
            {"i": e.index, "kind": e.kind, "label": e.label, **e.detail}
            for e in run.events
        ],
        # Burn arrows (spec 9a) need where the burn started and which way it
        # pointed. Position is converted to scene kilometres here, like every
        # other position; the direction is a unit vector and needs no scaling.
        "burns": [
            {
                "i0": b.start_index, "i1": b.end_index,
                "dv": b.dv_mps, "dur": b.duration_s,
                "pos": (b.ignition_pos_eci * config.SCENE_UNITS_PER_METRE).tolist(),
                "dir": b.mean_direction_eci.tolist(),
            }
            for b in run.burns
        ],
        "burn_dv_max": max((b.dv_mps for b in run.burns), default=0.0),
        "burn_arrow_max_frac": config.BURN_ARROW_MAX_FRAC_EARTH_R,
        "total_dv_mps": run.total_dv_mps,
        "pending": False,
        # For the drawn-orbit window: how much of a revolution a stretch of
        # track is worth.
        "orbit_period_s": run.orbit_period_s,
        "duration_s": raw.duration_s,
        "dt_median": raw.dt_stats[1],
        # Earth constants come from core/earth.py and nowhere else (spec 6.4).
        "earth_r_km": earth.EARTH_RADIUS_M * config.SCENE_UNITS_PER_METRE,
        "texture_seam_lon_deg": config.EARTH_TEXTURE_SEAM_LON_DEG,
    }
    return _encode(block), meta


def _encode(arr) -> str:  # noqa: ANN001
    """Float32 C-order block to base64. Kept separate so the unit conversion
    and the encoding can be tested independently."""
    return base64.b64encode(arr.astype("float32").tobytes()).decode()


assert config.SCENE_UNITS_PER_METRE == 1e-3, (
    "the viewer's float32 headroom assumes kilometres; see this module's docstring"
)
