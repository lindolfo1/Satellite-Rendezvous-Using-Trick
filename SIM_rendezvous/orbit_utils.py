#############################################################################
# orbit_utils.py
#
# Standalone orbital-mechanics helpers used by the input file. No Trick-
# specific objects are touched here except for reading/writing `.sat`
# attributes on the `target`/`chaser` objects passed in -- everything else
# is plain math, so this can be tested or reused independently of the sim.
#############################################################################

import math
import random


def _dot(u, v):
    return sum(uk * vk for uk, vk in zip(u, v))


def _cross(u, v):
    return [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]


def _norm(v):
    return math.sqrt(_dot(v, v))


def _unit(v):
    m = _norm(v)
    return [vk / m for vk in v]


def coe_to_eci(a, e, i, raan, argp, nu, mu):
    """Classical orbital elements -> ECI position/velocity vectors."""
    p = a * (1.0 - e ** 2)
    r = p / (1.0 + e * math.cos(nu))

    # position/velocity in the perifocal (PQW) frame
    r_pqw = [r * math.cos(nu), r * math.sin(nu), 0.0]
    h = math.sqrt(mu * p)
    v_pqw = [-mu / h * math.sin(nu), mu / h * (e + math.cos(nu)), 0.0]

    # PQW -> ECI rotation matrix (3-1-3: RAAN, inc, argp)
    cO, sO = math.cos(raan), math.sin(raan)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)

    R = [
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si,                 cw * si,                 ci],
    ]

    def rotate(v):
        return [
            R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
            R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
            R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2],
        ]

    return rotate(r_pqw), rotate(v_pqw)


def eci_to_coe(r_vec, v_vec, mu):
    """ECI position/velocity vectors -> classical orbital elements
    (a, e, i, raan, argp, nu). Standard rv2coe conversion."""

    r = _norm(r_vec)
    v = _norm(v_vec)

    h_vec = _cross(r_vec, v_vec)
    h = _norm(h_vec)

    n_vec = _cross([0.0, 0.0, 1.0], h_vec)   # node vector
    n = _norm(n_vec)

    e_vec = [
        (1.0 / mu) * ((v * v - mu / r) * r_vec[k] - _dot(r_vec, v_vec) * v_vec[k])
        for k in range(3)
    ]
    e = _norm(e_vec)

    energy = v * v / 2.0 - mu / r
    a = -mu / (2.0 * energy)

    i = math.acos(max(-1.0, min(1.0, h_vec[2] / h)))

    # RAAN
    if n > 1e-12:
        raan = math.acos(max(-1.0, min(1.0, n_vec[0] / n)))
        if n_vec[1] < 0.0:
            raan = 2.0 * math.pi - raan
    else:
        raan = 0.0   # equatorial orbit -- RAAN undefined, default to 0

    # argument of perigee
    if n > 1e-12 and e > 1e-12:
        argp = math.acos(max(-1.0, min(1.0, _dot(n_vec, e_vec) / (n * e))))
        if e_vec[2] < 0.0:
            argp = 2.0 * math.pi - argp
    else:
        argp = 0.0   # circular and/or equatorial -- undefined, default to 0

    # true anomaly
    if e > 1e-12:
        nu = math.acos(max(-1.0, min(1.0, _dot(e_vec, r_vec) / (e * r))))
        if _dot(r_vec, v_vec) < 0.0:
            nu = 2.0 * math.pi - nu
    else:
        # circular orbit -- measure angle from node (or from x-axis if equatorial)
        ref = n_vec if n > 1e-12 else [1.0, 0.0, 0.0]
        ref_n = _norm(ref)
        nu = math.acos(max(-1.0, min(1.0, _dot(ref, r_vec) / (ref_n * r))))
        if r_vec[2] < 0.0:
            nu = 2.0 * math.pi - nu

    return a, e, i, raan, argp, nu


def randomize_chaser_position(target, chaser, mu, radius_m=1000.0, max_angle_from_behind_deg=45.0):
    """Place the chaser at a random point on the surface of a sphere of
    radius `radius_m` around the target, in an arbitrary direction (no
    orbital-plane alignment) -- and give it the velocity needed for
    BOUNDED relative motion (a closed, periodic relative orbit about the
    target, rather than a drifting one).

    Simply copying the target's inertial velocity puts the chaser on a
    slightly different orbit (different energy/period for the same
    velocity vector at a different radius), which secularly drifts apart
    from and back toward the target -- what looked like a spiral before
    the guidance system corrected it.

    Instead this uses the Clohessy-Wiltshire (CW / Hill's) relative-motion
    equations. In the target's rotating R-V-H frame (radial, along-track,
    cross-track), the along-track velocity needed to eliminate secular
    drift for a given radial offset x0 is:

        vy0 = -2 * n * x0        (n = target mean motion)

    with the radial and cross-track velocities left at zero (chaser starts
    momentarily "at rest" relative to the target in those two directions).
    Cross-track motion is a simple harmonic oscillation and is always
    bounded on its own, so no constraint is needed there.

    A random offset generally isn't a point on the target's orbit, so
    writing pos_eci/vel_eci alone isn't enough -- if the sim reconstructs
    state from orbital elements at initialize(), that write gets clobbered.
    This converts the chaser's actual ECI state back into its own orbital
    elements too, so the result holds regardless of which representation
    the sim treats as authoritative.

    Returns the offset vector [x0, y0, z0] (in the target's R-V-H frame)
    actually drawn, for logging.

    `max_angle_from_behind_deg` restricts where on the sphere the chaser can
    land: only within that many degrees of the "back" of the target's orbit
    (the trailing / anti-along-track direction, -V_hat). A value of 180
    would allow the full sphere; 45 (the default) keeps the chaser roughly
    trailing the target rather than out to the side, ahead, or off-plane.
    """

    # ---- 1. target orbital elements -> ECI state vector ----
    target_pos_eci, target_vel_eci = coe_to_eci(
        float(target.sat.sma),
        float(target.sat.ecc),
        float(target.sat.inc),
        float(getattr(target.sat, "raan", 0.0)),
        float(getattr(target.sat, "argp", 0.0)),
        float(target.sat.trueAnom),
        mu,
    )

    # ---- 2. build the target's R-V-H (radial / along-track / cross-track) frame ----
    R_hat = _unit(target_pos_eci)                                  # radial
    h_vec = _cross(target_pos_eci, target_vel_eci)                 # angular momentum
    H_hat = _unit(h_vec)                                           # cross-track (orbit normal)
    V_hat = _cross(H_hat, R_hat)                                   # along-track (completes R,V,H)

    # ---- 3. random offset within a cone of the "back" of the orbit ----
    # "Back" = trailing the target = the anti-along-track direction (-V_hat),
    # i.e. [x,y,z]_rvh = [0,-1,0]. Sample a spherical cap of half-angle
    # `max_angle_from_behind_deg` around that direction, uniform by area
    # (cos(theta) uniform over [cos(max_angle), 1]), then rotate azimuthally
    # about that axis using the R/H directions, which are perpendicular to it.
    max_angle = math.radians(max_angle_from_behind_deg)
    cos_theta = random.uniform(math.cos(max_angle), 1.0)
    sin_theta = math.sqrt(1.0 - cos_theta ** 2)
    phi = random.uniform(0.0, 2.0 * math.pi)

    x0 = radius_m * sin_theta * math.cos(phi)   # radial
    y0 = radius_m * -cos_theta                  # along-track (negative = trailing/behind)
    z0 = radius_m * sin_theta * math.sin(phi)   # cross-track
    offset_rvh = [x0, y0, z0]

    # ---- 4. CW no-drift velocity in the rotating R-V-H frame ----
    target_sma = float(target.sat.sma)
    n = math.sqrt(mu / target_sma ** 3)   # target mean motion
    vx0 = 0.0
    vy0 = -2.0 * n * x0                       # no-drift (bounded motion) condition
    vz0 = 0.0

    # convert rotating-frame relative velocity to inertial relative velocity:
    # v_inertial = v_rotating + omega x r,  omega = n * H_hat
    omega_cross_r = [-n * y0, n * x0, 0.0]    # cross([0,0,n], [x0,y0,z0]) in R-V-H components
    v_rel_rvh_inertial = [
        vx0 + omega_cross_r[0],
        vy0 + omega_cross_r[1],
        vz0 + omega_cross_r[2],
    ]

    # ---- 5. rotate offset and relative velocity from R-V-H into ECI ----
    def rvh_to_eci(v_rvh):
        return [
            R_hat[k] * v_rvh[0] + V_hat[k] * v_rvh[1] + H_hat[k] * v_rvh[2]
            for k in range(3)
        ]

    offset_eci = rvh_to_eci(offset_rvh)
    v_rel_eci = rvh_to_eci(v_rel_rvh_inertial)

    chaser_pos_eci = [target_pos_eci[k] + offset_eci[k] for k in range(3)]
    chaser_vel_eci = [target_vel_eci[k] + v_rel_eci[k] for k in range(3)]

    # ---- 6. convert chaser's actual state back to orbital elements ----
    a, e, i, raan, argp, nu = eci_to_coe(chaser_pos_eci, chaser_vel_eci, mu)

    chaser.sat.sma = a
    chaser.sat.ecc = e
    chaser.sat.inc = i
    if hasattr(chaser.sat, "raan"):
        chaser.sat.raan = raan
    if hasattr(chaser.sat, "argp"):
        chaser.sat.argp = argp
    chaser.sat.trueAnom = nu

    # also write the vectors directly, in case the sim DOES take pos_eci/
    # vel_eci as authoritative -- harmless either way, and self-consistent
    # with the elements just computed.
    chaser.sat.pos_eci = chaser_pos_eci
    chaser.sat.vel_eci = chaser_vel_eci

    return offset_rvh