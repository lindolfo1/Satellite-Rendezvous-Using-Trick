"""Where the chaser believes it is pointing.

`chaser.sat.attNav.qHat` is a reference attitude, **body to ECI, scalar first**:
`qHat[0]` is w and `qHat[1..3]` are x, y, z. Read directly; nothing is inferred.

What remains is a **consistency check**. The chaser's true attitude is its own
LVLH triad -- spec 3.4, with the axis naming the rangefinder bearings confirm --
so the angle between `qHat` and that triad is the attitude error, and on a
healthy run it is small. The other three readings of the same four numbers
(scalar last, and either order conjugated) are scored too, not to be chosen but
as a tripwire: reading a quaternion scalar-last turns a near-identity rotation
into roughly a half turn, so if one of them fits far better the convention has
changed and saying so beats drawing a body frame pointing somewhere absurd.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core import frames


#: How the simulation writes it: `qHat[0]` is the scalar part.
ORDER = "wxyz"
CONJUGATED = False


@dataclass(frozen=True)
class AttNavFit:
    """How well `qHat`, read as documented, matches the true attitude."""

    error_rad: float          # median angle from the true attitude
    best_other_rad: float     # closest of the three other readings
    best_other: str
    consistent: bool

    @property
    def label(self) -> str:
        return "qHat scalar-first, body\u2192ECI"


def _as_xyzw(q: np.ndarray, order: str, conjugated: bool) -> np.ndarray:
    """The file's four columns as an xyzw quaternion, under one reading."""
    out = q[:, [1, 2, 3, 0]] if order == "wxyz" else q.copy()
    if conjugated:
        out = out.copy()
        out[:, 0:3] *= -1.0
    return out


def _angle_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation angle between two xyzw quaternion arrays, radians."""
    dot = np.abs(np.sum(a * b, axis=1))          # q and -q are one rotation
    return 2.0 * np.arccos(np.clip(dot, -1.0, 1.0))


def true_attitude(run) -> np.ndarray:  # noqa: ANN001
    """The chaser's true body->ECI quaternion, xyzw.

    Built with the sensor axis convention -- x radial, y along-track, z orbit
    normal -- because that is the frame the rangefinder bearings are expressed
    in, and so the frame the sim's body axes almost certainly are.
    """
    return frames.triad_quaternion(run.chaser_ez, run.chaser_ex, run.chaser_ey)


#: An attitude error this large is not a filter doing badly, it is the four
#: numbers being read the wrong way round.
CONSISTENCY_LIMIT_RAD = np.radians(45.0)


def _normalised(q: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(q, axis=1, keepdims=True)
    return q / np.where(norm == 0, 1.0, norm)


def detect(run) -> AttNavFit | None:  # noqa: ANN001
    """Score the documented reading, and the others as a tripwire."""
    if run.raw.attnav_qhat is None:
        return None

    truth = true_attitude(run)
    error = float(np.median(_angle_between(
        _normalised(_as_xyzw(run.raw.attnav_qhat, ORDER, CONJUGATED)), truth)))

    others = []
    for order in ("wxyz", "xyzw"):
        for conjugated in (False, True):
            if order == ORDER and conjugated == CONJUGATED:
                continue
            candidate = _normalised(_as_xyzw(run.raw.attnav_qhat, order, conjugated))
            sense = "conjugated" if conjugated else "as written"
            others.append((float(np.median(_angle_between(candidate, truth))),
                           f"scalar-{'first' if order == 'wxyz' else 'last'}, {sense}"))
    others.sort()

    return AttNavFit(
        error_rad=error, best_other_rad=others[0][0], best_other=others[0][1],
        consistent=error < CONSISTENCY_LIMIT_RAD,
    )


def error_rotation_rvh(believed: np.ndarray, truth: np.ndarray,
                       run) -> np.ndarray:  # noqa: ANN001
    """The attitude error as a rotation vector on the chaser's R, V, H axes.

    The error is the rotation that takes the true attitude to the believed one,
    `q_err = q_believed * conj(q_true)`, which is a rotation expressed in ECI.
    Its axis-times-angle form is a vector, so it resolves onto the chaser's own
    radial / along-track / normal axes like any other -- which is what makes the
    three numbers readable: they say which way the belief is tipped, not just
    how far.
    """
    bx, by, bz, bw = believed.T
    tx, ty, tz, tw = truth.T

    # Hamilton product with the truth conjugated: q_believed * conj(q_true).
    cx, cy, cz, cw = -tx, -ty, -tz, tw
    ex = bw * cx + bx * cw + by * cz - bz * cy
    ey = bw * cy - bx * cz + by * cw + bz * cx
    ez = bw * cz + bx * cy - by * cx + bz * cw
    ew = bw * cw - bx * cx - by * cy - bz * cz

    # Shortest arc, then axis * angle.
    flip = np.where(ew < 0.0, -1.0, 1.0)
    ex, ey, ez, ew = ex * flip, ey * flip, ez * flip, ew * flip
    angle = 2.0 * np.arccos(np.clip(ew, -1.0, 1.0))
    sin_half = np.sqrt(np.maximum(1.0 - ew * ew, 0.0))
    # Below this the rotation is too small for the axis to be meaningful, and
    # the vector is negligible anyway.
    scale = np.where(sin_half > 1e-12, angle / np.where(sin_half > 1e-12, sin_half, 1.0), 0.0)
    rotation = np.stack([ex, ey, ez], axis=1) * scale[:, None]

    return np.stack([
        np.sum(rotation * run.chaser_ez, axis=1),   # R, radial
        np.sum(rotation * run.chaser_ex, axis=1),   # V, along-track
        np.sum(rotation * run.chaser_ey, axis=1),   # H, orbit normal
    ], axis=1)


def build(run) -> dict:  # noqa: ANN001
    """Believed attitude as xyzw quaternions, plus the error against truth."""
    fit = detect(run)
    if fit is None:
        return {"attnav_fit": None, "attnav_quat": None, "attnav_err_rad": None,
                "attnav_err_rvh": None}

    believed = _normalised(_as_xyzw(run.raw.attnav_qhat, ORDER, CONJUGATED))

    truth = true_attitude(run)
    return {
        "attnav_fit": fit,
        "attnav_quat": believed,
        "attnav_err_rad": _angle_between(believed, truth),
        "attnav_err_rvh": error_rotation_rvh(believed, truth, run),
    }
