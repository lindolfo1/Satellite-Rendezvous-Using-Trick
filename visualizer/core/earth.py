"""GMST, sub-satellite latitude/longitude, and the Earth constants.

Spec 5, 6. **Every Earth constant lives here and nowhere else** -- the radius
in particular was previously duplicated in the renderer, where it disagreed
with the simulation by 7 km.

Rotation angle is theta = GMST(utc_start + elapsed) about ECI +Z, by the
standard IAU-82 formula. Omitted, deliberately: nutation, polar motion, and the
UT1-UTC correction. ECI is treated as TEME-equivalent, which is what the source
data is. The resulting error is at the arcsecond level -- under 30 m on the
ground -- and is dominated by |UT1-UTC| <= 0.9 s, worth up to 0.4 km of
longitude. That is invisible against a satellite ground track and would matter
only if this tool were used for geolocation, which it is not.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

#: WGS84 equatorial radius, in metres.
#:
#: Not the 6371 km mean radius spec 9a mentions. The simulation's own target
#: sits at 6 878 137 m, which is exactly this plus a round 500 km of altitude,
#: so the sim is built on WGS84 and matching it keeps the occlusion test and the
#: ground tracks consistent with the data rather than with a different sphere.
EARTH_RADIUS_M = 6378137.0

#: WGS84 flattening. Used for geodetic latitude, which is what a map is drawn
#: in -- geocentric latitude differs by up to 0.19 degrees at mid-latitudes,
#: about 21 km, which is plainly visible against a coastline.
EARTH_FLATTENING = 1.0 / 298.257223563

#: Mean sidereal rotation rate, rad/s. Earth turns 360.9856 degrees per solar
#: day, not 360: the extra degree is the day's worth of orbit around the Sun.
EARTH_ROTATION_RATE = 7.292115146706979e-5

#: Gravitational parameter, m^3/s^2. Matches the value implied by the sim's own
#: circular velocity to seven figures.
MU = 3.986004418e14

_JD_UNIX_EPOCH = 2440587.5
_SECONDS_PER_DAY = 86400.0


def julian_dates(utc_start: datetime, time_s: np.ndarray) -> np.ndarray:
    """Julian date per sample, from the sidecar epoch and elapsed sim time.

    Leap seconds are ignored along with everything else in the docstring above;
    UTC is treated as a uniform timescale.
    """
    if utc_start.tzinfo is None:
        raise ValueError("utc_start must be timezone-aware")
    epoch = utc_start.astimezone(timezone.utc).timestamp()
    elapsed = np.asarray(time_s, dtype=np.float64)
    elapsed = elapsed - elapsed[0]
    return _JD_UNIX_EPOCH + (epoch + elapsed) / _SECONDS_PER_DAY


def gmst_radians(julian_date: np.ndarray) -> np.ndarray:
    """Greenwich Mean Sidereal Time, radians in [0, 2*pi).

    IAU-82 series. At J2000.0 exactly it returns 280.46061837 degrees, the
    published value, which is the check in `tests/test_earth.py`.
    """
    centuries = (np.asarray(julian_date, dtype=np.float64) - 2451545.0) / 36525.0
    seconds = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * centuries
        + 0.093104 * centuries**2
        - 6.2e-6 * centuries**3
    )
    degrees = (seconds / 240.0) % 360.0        # 240 s of time = 1 degree
    return np.radians(degrees % 360.0)


def eci_to_ecef(pos_eci: np.ndarray, gmst: np.ndarray) -> np.ndarray:
    """Rotate ECI positions into the rotating frame by -theta about +Z."""
    cos, sin = np.cos(gmst), np.sin(gmst)
    x, y, z = pos_eci[:, 0], pos_eci[:, 1], pos_eci[:, 2]
    return np.stack([cos * x + sin * y, -sin * x + cos * y, z], axis=1)


def sub_satellite(pos_eci: np.ndarray, gmst: np.ndarray) -> tuple[np.ndarray, ...]:
    """Geodetic sub-satellite (latitude, longitude, altitude) in deg, deg, m.

    Longitude is east-positive and wrapped to (-180, 180]. Latitude is geodetic
    via Bowring's closed form: no iteration, and a measured round-trip residual
    of about 3 mm at 500 km altitude. Geodetic rather than geocentric because a
    map is drawn in geodetic latitude -- the two differ by up to 0.19 degrees at
    mid-latitudes, roughly 21 km, which is plainly visible against a coastline.
    """
    ecef = eci_to_ecef(np.asarray(pos_eci, dtype=np.float64), np.asarray(gmst))
    x, y, z = ecef[:, 0], ecef[:, 1], ecef[:, 2]

    a = EARTH_RADIUS_M
    f = EARTH_FLATTENING
    b = a * (1.0 - f)
    e2 = f * (2.0 - f)
    ep2 = e2 / (1.0 - e2)

    p = np.hypot(x, y)
    theta = np.arctan2(z * a, p * b)
    lat = np.arctan2(z + ep2 * b * np.sin(theta) ** 3,
                     p - e2 * a * np.cos(theta) ** 3)
    lon = np.arctan2(y, x)

    n = a / np.sqrt(1.0 - e2 * np.sin(lat) ** 2)
    # cos(lat) -> 0 over the poles, so altitude switches to the polar form.
    with np.errstate(divide="ignore", invalid="ignore"):
        alt = np.where(
            np.abs(np.cos(lat)) > 1e-9,
            p / np.cos(lat) - n,
            np.abs(z) - b,
        )

    return np.degrees(lat), np.degrees(lon), alt


def build(utc_start: datetime, time_s: np.ndarray,
          chaser_pos_eci: np.ndarray, target_pos_eci: np.ndarray) -> dict:
    """Everything Earth-related, as arrays to splice onto `Run`."""
    jd = julian_dates(utc_start, time_s)
    gmst = gmst_radians(jd)
    c_lat, c_lon, c_alt = sub_satellite(chaser_pos_eci, gmst)
    t_lat, t_lon, t_alt = sub_satellite(target_pos_eci, gmst)
    return {
        "julian_date": jd,
        "gmst": gmst,
        "chaser_lat_deg": c_lat, "chaser_lon_deg": c_lon, "chaser_alt_m": c_alt,
        "target_lat_deg": t_lat, "target_lon_deg": t_lon, "target_alt_m": t_alt,
    }
