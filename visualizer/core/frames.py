"""ECI conventions, the LVLH body frame, and ECI<->body rotations.

Spec 3.4. ECI is right-handed with +X to the vernal equinox and +Z to the north
pole, origin at Earth centre. The chaser body frame -- the reference for both
the IMU and the rangefinder -- is:

    ez = unit(position)                     zenith / radial out
    ex = unit(velocity - radial component)  along-track
    ey = ez x ex                            orbit normal

right-handed, so ex x ey = ez. There is no quaternion in the source data and
none is needed to *define* the frame; one is produced here only as a compact
way to hand the orientation to the renderer.

Verified against the real run: with these definitions, `atan2(by, bx)` and
`asin(bz/range)` reproduce the recorded rangefinder azimuth and elevation.
"""

from __future__ import annotations

import numpy as np


def unit(vectors: np.ndarray) -> np.ndarray:
    """Normalise along the last axis. Zero-length rows come back as zeros."""
    norm = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.divide(vectors, norm, out=np.zeros_like(vectors), where=norm > 0)


def lvlh_frame(pos_eci: np.ndarray, vel_eci: np.ndarray) -> tuple[np.ndarray, ...]:
    """Body triad (ex, ey, ez) per sample, each (N, 3).

    Vectorised over all samples: this is called once per run at load time, never
    per frame.
    """
    ez = unit(pos_eci)
    along = vel_eci - np.sum(vel_eci * ez, axis=-1, keepdims=True) * ez
    ex = unit(along)
    ey = np.cross(ez, ex)
    return ex, ey, ez


def to_body(vec_eci: np.ndarray, ex: np.ndarray, ey: np.ndarray,
            ez: np.ndarray) -> np.ndarray:
    """Rotate an ECI array into body coordinates, componentwise per sample."""
    return np.stack([
        np.sum(vec_eci * ex, axis=-1),
        np.sum(vec_eci * ey, axis=-1),
        np.sum(vec_eci * ez, axis=-1),
    ], axis=-1)


def triad_quaternion(ex: np.ndarray, ey: np.ndarray, ez: np.ndarray) -> np.ndarray:
    """(N, 4) xyzw quaternions for the rotation taking the ECI basis to the triad.

    Packed instead of the nine triad components because a quaternion is four
    floats rather than nine and the renderer applies it directly. Converting
    between rotation representations is presentation, not physics -- the triad
    above stays authoritative for every computed quantity.

    Shepperd's method: pick the largest of the four diagonal combinations, which
    avoids the near-zero divisor the naive trace formula hits at 180 degrees.
    """
    m00, m01, m02 = ex[:, 0], ey[:, 0], ez[:, 0]
    m10, m11, m12 = ex[:, 1], ey[:, 1], ez[:, 1]
    m20, m21, m22 = ex[:, 2], ey[:, 2], ez[:, 2]

    trace = m00 + m11 + m22
    n = trace.size
    quat = np.empty((n, 4), dtype=np.float64)

    case = np.argmax(np.stack([trace, m00, m11, m22], axis=1), axis=1)
    use_trace = trace > 0
    case = np.where(use_trace, 0, case)

    def fill(mask, s, x, y, z, w):
        if not np.any(mask):
            return
        quat[mask, 0] = x[mask] / s[mask]
        quat[mask, 1] = y[mask] / s[mask]
        quat[mask, 2] = z[mask] / s[mask]
        quat[mask, 3] = w[mask] / s[mask]

    with np.errstate(invalid="ignore"):
        s0 = np.sqrt(np.maximum(trace + 1.0, 0.0)) * 2.0
        fill(case == 0, s0, m21 - m12, m02 - m20, m10 - m01, s0 * s0 / 4.0)

        s1 = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 0.0)) * 2.0
        fill(case == 1, s1, s1 * s1 / 4.0, m01 + m10, m02 + m20, m21 - m12)

        s2 = np.sqrt(np.maximum(1.0 + m11 - m00 - m22, 0.0)) * 2.0
        fill(case == 2, s2, m01 + m10, s2 * s2 / 4.0, m12 + m21, m02 - m20)

        s3 = np.sqrt(np.maximum(1.0 + m22 - m00 - m11, 0.0)) * 2.0
        fill(case == 3, s3, m02 + m20, m12 + m21, s3 * s3 / 4.0, m10 - m01)

    return quat / np.linalg.norm(quat, axis=1, keepdims=True)
