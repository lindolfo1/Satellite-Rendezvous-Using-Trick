"""Measured-vs-true comparisons, validity masks, and stale-value lookups.

Spec 4.7-4.8. Signed error is `measured - true`. Percent of true magnitude is
computed with a floor below which it is `NaN` rather than enormous -- a 2 cm
error on a 1 mm true range is not "2000% wrong" in any useful sense.

For azimuth and elevation the **primary figure is absolute angular error in
milliradians**. Percent is near-meaningless on an angle whose zero is a frame
convention: the same physical pointing error reads as 1% or 400% depending on
where the target happens to sit relative to the body +X axis.
"""

from __future__ import annotations

import numpy as np

import config
from core import frames


def signed_error(measured: np.ndarray, true: np.ndarray) -> np.ndarray:
    """measured - true, elementwise."""
    return measured - true


def percent_error(measured: np.ndarray, true: np.ndarray,
                  floor: float) -> np.ndarray:
    """Signed error as a percentage of |true|, NaN where |true| < floor.

    The floor is what keeps this from dividing by zero on a coasting sample or
    a zero-length vector, so no `errstate` juggling is needed downstream.
    """
    magnitude = np.abs(true)
    out = np.full(magnitude.shape, np.nan, dtype=np.float64)
    usable = magnitude >= floor
    out[usable] = (measured[usable] - true[usable]) / magnitude[usable] * 100.0
    return out


def wrap_angle(radians: np.ndarray) -> np.ndarray:
    """Wrap to (-pi, pi].

    Azimuth is an `atan2` output, so a measurement either side of the +/-pi
    branch cut differs by 2*pi from its truth while being physically identical.
    Without this, a rendezvous that happens to approach along -X reports
    six-radian errors.
    """
    return (radians + np.pi) % (2.0 * np.pi) - np.pi


def last_valid_index(valid: np.ndarray) -> np.ndarray:
    """For each sample, the last index at or before it where `valid` is True.

    -1 where no valid sample has occurred yet. Lets a panel show a greyed stale
    reading instead of blanking (spec 4.8), which matters because the real run
    starts with both sensors invalid.
    """
    indices = np.where(valid, np.arange(valid.size), -1)
    return np.maximum.accumulate(indices)


def true_delta_v_body(time_s: np.ndarray, thrust_acc_eci: np.ndarray,
                      ex: np.ndarray, ey: np.ndarray,
                      ez: np.ndarray) -> np.ndarray:
    """Per-interval delta-V in the body frame (spec 4.3).

    Trapezoidal integral of the commanded thrust over [t_{i-1}, t_i], rotated
    into the body frame at sample i. **Thrust only, no gravity term**: the
    vehicle is in free fall, so an accelerometer senses only non-gravitational
    acceleration and `imu_dvel_body` compares against this directly. Adding
    gravity here would produce a ~9 m/s per-interval discrepancy and look like
    a broken IMU.
    """
    dv_eci = np.zeros_like(thrust_acc_eci)
    dt = np.diff(time_s)[:, None]
    dv_eci[1:] = 0.5 * (thrust_acc_eci[1:] + thrust_acc_eci[:-1]) * dt
    return frames.to_body(dv_eci, ex, ey, ez)


def build(run) -> dict:  # noqa: ANN001 -- data.run.Run, mid-construction
    """Every error series, as a dict of arrays to splice onto `Run`."""
    raw = run.raw

    range_err = signed_error(raw.rf_range, run.true_range)
    az_err = wrap_angle(signed_error(raw.rf_az, run.az_true))
    el_err = wrap_angle(signed_error(raw.rf_el, run.el_true))

    dv_true = true_delta_v_body(raw.time_s, raw.thrust_acc_eci,
                                run.chaser_ex, run.chaser_ey, run.chaser_ez)
    dv_err = raw.imu_dvel_body - dv_true
    dv_true_mag = np.linalg.norm(dv_true, axis=1)
    dv_err_mag = np.linalg.norm(dv_err, axis=1)

    return {
        "range_err": range_err,
        "range_err_pct": percent_error(raw.rf_range, run.true_range,
                                       config.RANGE_PERCENT_FLOOR),
        "az_err": az_err,
        "az_err_mrad": az_err * 1000.0,
        "el_err": el_err,
        "el_err_mrad": el_err * 1000.0,
        "dv_body_true": dv_true,
        "dv_body_err": dv_err,
        "dv_err_mag": dv_err_mag,
        "dv_err_pct": percent_error(
            np.linalg.norm(raw.imu_dvel_body, axis=1), dv_true_mag,
            config.DVEL_PERCENT_FLOOR),
        "imu_last_valid": last_valid_index(raw.imu_valid),
        "rf_last_valid": last_valid_index(raw.rf_valid),
    }
