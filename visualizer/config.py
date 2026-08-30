"""Every tunable constant: paths, thresholds, arrow scales, colours, panel sizes.

Nothing here is computed and nothing here imports from the rest of the project,
so any module may import it without a cycle. Earth's radius and rotation rate
deliberately do *not* live here -- spec 6 puts them in `core/earth.py` and
nowhere else.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

#: Folder scanned for `<stem>.csv` + `<stem>.json` pairs (spec 1).
RUNS_DIR = Path(__file__).parent / "runs"


# --------------------------------------------------------------------------
# Physics / detection thresholds
# --------------------------------------------------------------------------

#: A sample counts as thrusting when |thrust_acc_eci| exceeds this (spec 4.4).
THRUST_EPS = 1e-6  # m/s^2

#: True magnitudes below these floors make percent error meaningless, so the
#: percent series is NaN there instead of exploding (spec 4.7).
RANGE_PERCENT_FLOOR = 1e-3  # m
ANGLE_PERCENT_FLOOR = 1e-6  # rad
DVEL_PERCENT_FLOOR = 1e-9  # m/s


# --------------------------------------------------------------------------
# Playback (spec 7)
# --------------------------------------------------------------------------

RATE_PRESETS = (1.0, 5.0, 25.0, 100.0, 500.0)
RATE_DEFAULT = 1.0
RATE_MIN = 0.1
RATE_MAX = 1000.0

# NOTE (Stage 0, Spike C): there is no Python-side refresh rate any more. The
# render component owns its own requestAnimationFrame clock, so the playback
# loop never round-trips to Python. The old REFRESH_PERIOD_S lived here; it is
# removed rather than left at a value nothing reads.


# --------------------------------------------------------------------------
# View geometry
# --------------------------------------------------------------------------

#: Initial camera standoff in the local satellite view, along +ez (spec 9b).
LOCAL_VIEW_STANDOFF_M = 25.0

#: Satellite bus edge length, drawn at true scale (spec 9b).
CUBESAT_SIZE_M = 1.0

#: Ball radius to draw when the sidecar carries no `tolerance`, as a fraction
#: of each standoff. Labelled as assumed wherever it is shown -- an unlabelled
#: default here would be a tolerance the simulation never stated.
DEFAULT_TOLERANCE_ASSUMED = 0.02

#: Scene units are KILOMETRES past the packing boundary. float32 (what WebGL
#: stores vertices as) resolves 0.49 mm at a 6800 km orbit radius, versus 0.5 m
#: if the same geometry were packed in metres. `data/` and `core/` stay float64
#: SI per spec; `render/payload.py` is the only place the conversion happens.
SCENE_UNITS_PER_METRE = 1e-3

#: The largest burn in a run draws as this fraction of the Earth radius in the
#: orbit-plane view; every other burn scales linearly from it (spec 9a).
BURN_ARROW_MAX_FRAC_EARTH_R = 0.08

#: Fixed on-screen arrow length in the local view, as a fraction of the scene
#: half-width, used by the direction-only scaling policy (spec 9b).
ARROW_FIXED_FRAC = 0.35

#: Below this fraction of a run's peak IMU delta-V, the measurement is sensor
#: noise and has no direction worth drawing. Coasting samples read ~1e-6 m/s
#: against a 3e-2 m/s peak, and the arrow -- drawn at full length under the
#: direction-only policy -- swung 75 to 146 degrees between frames.
IMU_DVEL_FLOOR_FRACTION = 1e-3

ARROW_SCALE_MODES = ("fixed", "relative")


# --------------------------------------------------------------------------
# Earth texture
# --------------------------------------------------------------------------

#: Filename looked for in `render/static/textures/`. Missing is not an error:
#: the viewer falls back to a wireframe globe.
EARTH_TEXTURE_NAME = "earth_texture.jpg"

#: Longitude at the texture's left edge (u = 0), degrees east.
#:
#: Derived from the seam being about 30 statute miles west of
#: 51.269181 N, 179.120772 W: 48.28 km at that latitude is 0.693 degrees of
#: longitude, giving -179.814. That is 0.19 degrees off the -180 antimeridian a
#: standard equirectangular map uses, i.e. about 21 km at the equator -- change
#: this to -180.0 if the map turns out to be conventional after all.
EARTH_TEXTURE_SEAM_LON_DEG = -179.814


# --------------------------------------------------------------------------
# Colours -- unlit and flat throughout; no sun vector, no terminator (spec 5).
# --------------------------------------------------------------------------

COLOR_EARTH_FILL = "#1b2a3a"
COLOR_EARTH_EDGE = "#3d5a75"
COLOR_MERIDIAN_TICK = "#e0c060"

COLOR_CHASER = "#4fc3f7"
COLOR_TARGET = "#ff8a65"

# WebGL ignores line width, so every track is one pixel however it is styled.
# These are brighter than they might otherwise be because contrast is the only
# lever available for legibility.
COLOR_PATH_FUTURE = "#6b83a0"  # not yet traversed
COLOR_PATH_PAST = "#d6e6f5"  # traversed up to the current time: brighter

COLOR_CORRIDOR = "#2f4858"

COLOR_VELOCITY = "#9ccc65"
COLOR_THRUST = "#ffca28"
COLOR_IMU_DVEL = "#ba68c8"
COLOR_RANGEFINDER = "#4dd0e1"

COLOR_BURN_SPAN = "#ffca28"
COLOR_WAYPOINT_TICK = "#4fc3f7"
COLOR_PLAYHEAD = "#ffffff"

COLOR_STALE = "#6b6b6b"  # greyed sensor numbers when isValid is false
COLOR_WARN = "#ef5350"


# --------------------------------------------------------------------------
# Layout (spec 10)
# --------------------------------------------------------------------------

#: Stats panel must stay within 20% of screen width. The view selector shares
#: the top row; the render area takes the remainder.
STATS_WIDTH_FRAC = 0.20
VIEW_SELECTOR_WIDTH_FRAC = 0.16

#: Bottom row: view options bottom-left (right edge aligned with the stats
#: panel's right edge, so it takes the same fraction), status bottom-right.
VIEW_OPTIONS_WIDTH_FRAC = STATS_WIDTH_FRAC
STATUS_WIDTH_FRAC = 0.20

#: Fallback iframe height in pixels. `st.components.v1.html` only accepts a
#: fixed pixel height, so the viewport fill is done in CSS (see app.py) and this
#: is what applies if that CSS ever fails to match. Keep it tall enough to be
#: usable and short enough not to force a page scrollbar on a small laptop.
RENDER_HEIGHT_PX = 760

#: Vertical space Streamlit's own toolbar occupies. The component is offset by
#: this so the HUD's top row is not hidden behind the Deploy button, and the
#: fill height subtracts it.
HEADER_CLEARANCE_REM = 3.4

#: Floor for the fill, so the HUD does not collapse on a very short window.
RENDER_MIN_HEIGHT_PX = 520

TIMELINE_HEIGHT_PX = 90
