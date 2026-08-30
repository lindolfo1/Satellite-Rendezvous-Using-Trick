"""Session state — now only the load-time choices.

Stage 0 moved the render loop into the browser, and that moved most of this
module with it. Anything the user changes *during* a session lives in
`render/static/js/00_state.js`, because changing it from Python would re-inject
the component HTML and remount the iframe, resetting the camera and the clock.

So Python owns which run is selected, and nothing else. `t_index`, `playing`,
`rate`, `active_view`, the sensor toggles, the arrow scale mode, the unit mode
and the panel visibility dict all moved to browser state. They are listed here
by name so the split is documented rather than inferred from an absence.
"""

from __future__ import annotations

import streamlit as st

#: Moved to js/00_state.js in Stage 1. Kept as a comment-in-code so a future
#: reader looking for them here finds out where they went.
MOVED_TO_BROWSER = (
    "t_index", "playing", "rate", "active_view", "show_imu",
    "show_rangefinder", "arrow_scale_mode", "unit_mode", "panel_visibility",
)

_DEFAULTS = {
    #: JSON filename stem of the selected run, or None (spec 1).
    "run_stem": None,
}


def init_state() -> None:
    """Populate any missing key with its default. Safe to call every rerun."""
    for key, value in _DEFAULTS.items():
        st.session_state.setdefault(key, value)


def select_run(stem: str | None) -> None:
    """Switch runs.

    Playback resets to t = 0 as a side effect rather than by assignment: a new
    run means a new payload, which remounts the component, which starts the
    browser-side clock at zero.
    """
    st.session_state["run_stem"] = stem
