"""The relative-navigation estimate: where the chaser believes it is.

`chaser.sat.relNav.xHat` is a twelve-element filter state -- relative position
(3), relative velocity (3), leftover attitude error (3), gyro bias (3) -- all
expressed in the **target's LVLH** frame. Only the first three are used here.

On the project's axis convention that frame is

    x = radial       Earth centre to the satellite
    y = along-track  z-hat x x-hat
    z = orbit normal x-hat x velocity

so `xHat[0:3]` is (R, V, H) and the estimated position is

    target + R * x-hat + V * y-hat + H * z-hat

read directly, with nothing inferred.

What remains is a **consistency check**: the same components are predicted from
the run's own geometry and compared, so a rebuilt simulation that changes sense
or axis order is caught rather than drawn as a sudden navigation failure. It is
a tripwire, not a search.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

#: Which way round `xHat[0:3]` is measured. The source describes it as
#: "relative position" without saying relative to which; this is the reading,
#: and `RelNavCheck.reversed_fits` reports when the data says otherwise.
#: Which way round `xHat[0:3]` is measured.
#:
#: Read off real output rather than assumed: `xHat` opens at V = +1000.4 m on a
#: run where the chaser trails the target by 1000 m, so it is the target as seen
#: from the chaser. Taking it the other way put the ghost 2000 m out, on the far
#: side of the target -- which reads as a catastrophic navigation failure rather
#: than as a sign error.
SENSE = "target - chaser"

#: How much better the assumed sense must fit than its opposite.
#:
#: The frame is judged by *comparing hypotheses*, not against an absolute
#: tolerance. Dividing the error by the separation looked reasonable and is
#: wrong at close range: a correct filter carrying 1.5 m of error reads as 150%
#: when the vehicles are a metre apart, so a converged rendezvous trips it while
#: the frame is perfectly right. A wrong sense, by contrast, is always about
#: twice the separation *and* is beaten by its own reverse -- which is true at
#: every range.
DISCRIMINATION = 0.5

#: A last sanity bound, against the widest separation in the run rather than
#: the instantaneous one. Catches an estimate that fits neither sense.
SANITY_FRACTION = 0.5

#: Beyond this multiple of the widest separation the estimate is not drawn --
#: not because it is wrong, but because it would throw the ghost so far from
#: the scene that the view is useless. Everything short of that *is* drawn,
#: including a filter that is performing badly.
#:
#: Refusing to draw a poor estimate was the wrong call. A run whose filter sits
#: 860 m off a 1000 m separation is exactly what a navigation overlay is for;
#: switching it off and printing a frame warning hides the very thing being
#: investigated. The frame check is now a warning, not a veto.
UNUSABLE_MULTIPLE = 50.0

#: Legacy: how large `relative_error` may be before the frame is called into question.
#: A filter half as wrong as the vehicles are far apart is not flying a
#: rendezvous, so this size of error means the frame changed rather than the
#: navigation degraded.
CONSISTENCY_LIMIT = 0.5

#: Separations below this are treated as this, so the ratio below does not
#: divide by a range on its way to zero at contact.
RANGE_FLOOR_M = 0.1


@dataclass(frozen=True)
class RelNavCheck:
    """How well the estimate matches the frame it is documented to be in."""

    #: Median |xHat[0:3] - prediction|. The navigation error on a healthy run.
    residual_m: float

    #: Median of |residual| / separation -- the statistic the check is made on,
    #: and the reason it is a ratio rather than a distance.
    #:
    #: An absolute threshold fails at both ends of a rendezvous. Early, a filter
    #: that starts diverged is genuinely metres wrong under the *correct*
    #: reading, so a tight limit rejects a working overlay. Late, the separation
    #: goes to zero and every reading agrees to within a metre, so a loose limit
    #: accepts anything. Dividing by the separation removes both: a wrong frame
    #: is wrong in proportion to how far apart the vehicles are, at every
    #: sample, so its ratio sits near 1 throughout while a working filter's sits
    #: near zero.
    relative_error: float

    #: Median true separation, for scale.
    scale_m: float

    consistent: bool

    #: Whether the estimate can be drawn at all -- finite, and near enough the
    #: scene to be worth looking at. Deliberately separate from `consistent`: an
    #: estimate may disagree with the declared frame *or* simply come from a
    #: filter that is performing poorly, and the second is what a navigation
    #: overlay exists to show.
    usable: bool = True

    #: What the opposite sense scores on the same statistic. Only meaningful
    #: when the primary reading fails, where it says whether to flip `SENSE`.
    reversed_relative_error: float = float("inf")
    #: Filled only on failure: what fits better, and by how much.
    alternative: str = ""
    alternative_residual_m: float = float("inf")

    @property
    def label(self) -> str:
        return f"target LVLH · {SENSE} · (R, V, H)"

    @property
    def reversed_fits(self) -> bool:
        """Whether flipping `SENSE` would fix it -- the one likely mistake."""
        return (not self.consistent
                and self.reversed_relative_error
                < DISCRIMINATION * self.relative_error)


def lvlh_to_eci(components: np.ndarray, run) -> np.ndarray:  # noqa: ANN001
    """(R, V, H) on the target's axes, as an ECI offset."""
    return (components[:, 0:1] * run.target_ez      # radial
            + components[:, 1:2] * run.target_ex    # along-track
            + components[:, 2:3] * run.target_ey)   # orbit normal


def eci_to_lvlh(vector: np.ndarray, run) -> np.ndarray:  # noqa: ANN001
    """An ECI offset as (R, V, H) on the target's axes."""
    return np.stack([
        np.sum(vector * run.target_ez, axis=1),
        np.sum(vector * run.target_ex, axis=1),
        np.sum(vector * run.target_ey, axis=1),
    ], axis=1)


def truth_lvlh(run) -> np.ndarray:  # noqa: ANN001
    """The true relative position in the sense `SENSE` names, as (R, V, H)."""
    relative = (run.rel_pos_eci if SENSE == "target - chaser"
                else -run.rel_pos_eci)
    return eci_to_lvlh(relative, run)


def rotate_about(vectors: np.ndarray, axis: np.ndarray,
                 angle: np.ndarray) -> np.ndarray:
    """Rodrigues rotation of `vectors` about a unit `axis` by `angle` radians."""
    cos = np.cos(angle)[:, None]
    sin = np.sin(angle)[:, None]
    dot = np.sum(axis * vectors, axis=1)[:, None]
    return (vectors * cos
            + np.cross(axis, vectors) * sin
            + axis * dot * (1.0 - cos))


def believed_attitude(run) -> np.ndarray | None:  # noqa: ANN001
    """The chaser's body triad as the filter believes it, as xyzw quaternions.

    `xHat[6:9]` is the **leftover attitude error**: a small-angle correction,
    not an absolute orientation. The chaser has no attitude quaternion in this
    data -- spec 3.4 defines its attitude as its own LVLH triad -- so the
    believed attitude is that triad rotated by this error.

    The error is a vector in the target's LVLH, so it is applied in that frame
    rather than in the body: the rotation is composed on the left. For the
    small angles this state carries, the two orders agree to first order and the
    difference is not visible; the choice is documented rather than hidden.

    Returns None when the run logs only the first six elements. The attitude
    tail is a filter internal, and a run that omits it is not broken -- the
    ghost simply carries the chaser's true attitude, which is what it would
    have anyway with a zero error.
    """
    from core import frames

    if run.raw.relnav_xhat.shape[1] < 9:
        return None

    delta = run.raw.relnav_xhat[:, 6:9]
    axis_eci = lvlh_to_eci(delta, run)
    angle = np.linalg.norm(axis_eci, axis=1)

    # A zero-length rotation vector has no axis; leave those samples unrotated.
    safe = np.where(angle[:, None] > 0, angle[:, None], 1.0)
    unit_axis = axis_eci / safe

    ex = rotate_about(run.chaser_ex, unit_axis, angle)
    ey = rotate_about(run.chaser_ey, unit_axis, angle)
    ez = rotate_about(run.chaser_ez, unit_axis, angle)
    return frames.triad_quaternion(ex, ey, ez), angle


def check_consistency(run) -> RelNavCheck:  # noqa: ANN001
    """Judge the frame by comparing the assumed sense against its opposite.

    Both hypotheses are scored on the same samples, so the comparison carries no
    units and no dependence on how close the vehicles happen to be. A wrong
    sense predicts a position on the far side of the target -- about twice the
    separation out -- and is beaten by its own reverse at every range. A right
    one is beaten by nothing.

    The earlier test divided the error by the instantaneous separation, which
    fails on exactly the runs this tool exists for: at a metre of separation a
    correct filter carrying a metre of error reads as 100% and the overlay
    switches itself off just as the rendezvous gets interesting.
    """
    estimate = run.raw.relnav_xhat[:, 0:3]
    truth = truth_lvlh(run)

    assumed = float(np.median(np.linalg.norm(estimate - truth, axis=1)))
    reversed_ = float(np.median(np.linalg.norm(estimate + truth, axis=1)))
    widest = float(np.max(run.true_range))

    fits_better = assumed < DISCRIMINATION * reversed_
    within_scale = assumed < SANITY_FRACTION * max(widest, RANGE_FLOOR_M)
    usable = bool(np.isfinite(estimate).all()) and (
        assumed < UNUSABLE_MULTIPLE * max(widest, RANGE_FLOOR_M))

    return RelNavCheck(
        usable=usable,
        residual_m=assumed,
        relative_error=assumed / max(widest, RANGE_FLOOR_M),
        reversed_relative_error=reversed_ / max(widest, RANGE_FLOOR_M),
        scale_m=widest,
        consistent=fits_better and within_scale,
    )


#: Readings scored only when the declared one fails, to name what does fit.
#: Not a chooser -- the frame is documented, and a mismatch means the
#: documentation and the output have diverged, which is worth reporting rather
#: than silently working around.
def _alternatives(run) -> dict:  # noqa: ANN001
    rel = run.rel_pos_eci
    axes = {"R": run.target_ez, "V": run.target_ex, "H": run.target_ey}

    def lvlh(vector, order=("R", "V", "H")):
        return np.stack([np.sum(vector * axes[name], axis=1) for name in order],
                        axis=1)

    return {
        "the opposite sense": lvlh(-rel),
        "ECI, target − chaser": rel,
        "ECI, chaser − target": -rel,
        "target LVLH in (V, H, R) order": lvlh(rel, ("V", "H", "R")),
    }


def best_alternative(run) -> tuple:  # noqa: ANN001
    """(name, residual) of whatever fits better than the declared reading."""
    estimate = run.raw.relnav_xhat[:, 0:3]
    scored = sorted(
        (float(np.median(np.linalg.norm(estimate - predicted, axis=1))), name)
        for name, predicted in _alternatives(run).items()
    )
    return scored[0][1], scored[0][0]


def build(run) -> dict:  # noqa: ANN001
    """Navigation error arrays, or an empty result when there is no estimate."""
    empty = {"relnav_fit": None, "relnav_est_eci": None, "relnav_err_eci": None,
             "relnav_err_m": None, "relnav_est_lvlh": None, "relnav_quat": None,
             "relnav_att_err": None, "relnav_att_err_rad": None}
    if run.raw.relnav_xhat is None:
        return empty

    fit = check_consistency(run)
    if not fit.consistent:
        name, residual = best_alternative(run)
        fit = replace(fit, alternative=name, alternative_residual_m=residual)

    if not fit.usable:
        # Non-finite, or so far out that drawing it would throw the ghost clean
        # out of the scene. Nothing else stops the overlay.
        return {**empty, "relnav_fit": fit}
        # Say so and draw nothing. A ghost placed with the wrong frame looks
        # like a navigation failure, which is worse than a blank.
        return {**empty, "relnav_fit": fit}

    est_lvlh = run.raw.relnav_xhat[:, 0:3]
    if SENSE == "target - chaser":
        est_lvlh = -est_lvlh
    estimated = run.raw.target_pos_eci + lvlh_to_eci(est_lvlh, run)
    error = estimated - run.raw.chaser_pos_eci

    # None when the run logs only position and velocity: the ghost then carries
    # the chaser's true attitude, which is what a zero error would give anyway.
    attitude = believed_attitude(run)
    if attitude is None:
        from core import frames
        quaternion = frames.triad_quaternion(run.chaser_ex, run.chaser_ey,
                                             run.chaser_ez)
        att_angle = np.zeros(run.n)
    else:
        quaternion, att_angle = attitude

    return {
        "relnav_fit": fit,
        "relnav_est_eci": estimated,
        "relnav_err_eci": error,
        "relnav_err_m": np.linalg.norm(error, axis=1),
        "relnav_est_lvlh": est_lvlh,
        "relnav_quat": quaternion,
        "relnav_att_err": (run.raw.relnav_xhat[:, 6:9]
                           if run.raw.relnav_xhat.shape[1] >= 9 else None),
        "relnav_att_err_rad": att_angle,
    }
