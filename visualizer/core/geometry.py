"""Vector helpers, `los_clear`, conic paths, and the plane-projection basis.

`los_clear` is the segment-sphere test ported from the old viewer, keeping its
clamped-t behaviour: what matters is whether the *segment* between the two
satellites intersects the Earth, not the infinite line through them. An
unclamped test reports occlusion when the Earth lies behind the observer.
"""

from __future__ import annotations

import numpy as np

from core.frames import unit


def los_clear(p1: np.ndarray, p2: np.ndarray, radius_m: float) -> np.ndarray:
    """True where the segment p1->p2 clears a sphere of `radius_m` at the origin.

    Vectorised over samples; p1 and p2 are (N, 3).
    """
    d = p2 - p1
    dd = np.sum(d * d, axis=-1)
    # Closest approach of the infinite line, then clamped to the segment.
    t = np.divide(-np.sum(p1 * d, axis=-1), dd, out=np.zeros_like(dd), where=dd > 0)
    t = np.clip(t, 0.0, 1.0)
    closest = p1 + t[..., None] * d
    return np.linalg.norm(closest, axis=-1) >= radius_m


def plane_basis(pos: np.ndarray, vel: np.ndarray) -> tuple[np.ndarray, ...]:
    """(u, v, normal) for the orbit plane spanned by `pos` and `vel` (spec 9a).

    Recomputed at the current time so the projection tracks the plane as
    correction burns change it.
    """
    normal = unit(np.cross(pos, vel))
    u = unit(pos)
    v = np.cross(normal, u)
    return u, v, normal


def project_to_plane(points: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Project (N, 3) ECI points onto the 2D basis (u, v)."""
    return np.stack([points @ u, points @ v], axis=-1)


def conic_path(pos: np.ndarray, vel: np.ndarray, mu: float,
               samples: int = 512) -> np.ndarray:
    """One full orbit through `pos`/`vel` as (samples, 3) ECI points.

    Drawn from the orbital elements rather than by propagating the state, so the
    path closes exactly and does not depend on the run's own sample spacing.
    """
    r = np.linalg.norm(pos)
    v2 = float(vel @ vel)
    h_vec = np.cross(pos, vel)
    e_vec = (np.cross(vel, h_vec) / mu) - pos / r
    ecc = float(np.linalg.norm(e_vec))
    energy = v2 / 2.0 - mu / r
    if abs(1.0 - ecc) < 1e-9 or energy >= 0:
        return np.repeat(pos[None, :], samples, axis=0)  # parabolic/hyperbolic
    a = -mu / (2.0 * energy)
    p = a * (1.0 - ecc**2)

    n_hat = unit(h_vec[None, :])[0]
    e_hat = unit(e_vec[None, :])[0] if ecc > 1e-12 else unit(pos[None, :])[0]
    q_hat = np.cross(n_hat, e_hat)

    nu = np.linspace(0.0, 2.0 * np.pi, samples)
    radius = p / (1.0 + ecc * np.cos(nu))
    return (radius[:, None] * (np.cos(nu)[:, None] * e_hat
                               + np.sin(nu)[:, None] * q_hat))
