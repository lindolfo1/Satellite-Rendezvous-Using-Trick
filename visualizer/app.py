"""Entry point: page config, sidebar, and the viewer component.

The layout is deliberately thin. Spec 10's six panels are a HUD drawn inside
the component (see `render/static/viewer.html`), not Streamlit widgets, so this
file arranges almost nothing: a sidebar for the load-time run choice, and one
full-width component below it.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# Spec 1 wants the selector collapsed -- it is a load-time choice that must not
# eat render area. But collapsed-by-default on a fresh session hides the only
# control that does anything, so it starts open until a run is chosen.
_HAS_RUN = bool(st.session_state.get("run_stem"))

st.set_page_config(
    page_title="Rendezvous viewer",
    layout="wide",
    initial_sidebar_state="collapsed" if _HAS_RUN else "expanded",
)

# The project is a package tree, not a pile of files. Downloading the modules
# individually flattens it, and the only symptom is "No module named 'panels'"
# -- which says nothing about the actual cause. Check first and say so plainly.
_HERE = Path(__file__).resolve().parent
_REQUIRED = (
    "config.py", "state.py",
    "panels/__init__.py", "panels/run_selector.py",
    "render/__init__.py", "render/component.py", "render/payload.py",
    "render/static/viewer.html", "render/static/hud.css", "render/static/js",
)
_missing = [p for p in _REQUIRED if not (_HERE / p).exists()]
if _missing:
    st.error(
        "The project tree is incomplete, so the local packages cannot be "
        "imported. Missing from `" + str(_HERE) + "`:\n\n"
        + "\n".join(f"- `{m}`" for m in _missing)
        + "\n\nThese are directories, not loose files -- keep the folder "
        "structure intact when copying the project."
    )
    st.stop()

import config  # noqa: E402
import state  # noqa: E402
from data import loader
from data import run as run_module  # noqa: E402
from panels import run_selector  # noqa: E402
from render import component, payload  # noqa: E402

state.init_state()

# Reclaim the page gutters, clear Streamlit's toolbar, and fill the viewport.
#
# Two things this has to fix. Streamlit's header is a fixed overlay, so zero top
# padding puts the HUD's top row under the Deploy button. And components.html
# takes a fixed pixel height, so the iframe cannot fill the window on its own --
# the height is forced here instead, and the component's own `resize` handler
# picks up the change because 100vh inside an iframe means the iframe's height.
st.markdown(
    f"""
    <style>
      .block-container, [data-testid="stMainBlockContainer"] {{
        padding: {config.HEADER_CLEARANCE_REM}rem 0.8rem 0 !important;
        max-width: 100% !important;
      }}
      .block-container iframe,
      [data-testid="stMainBlockContainer"] iframe {{
        height: max({config.RENDER_MIN_HEIGHT_PX}px,
                    calc(100vh - {config.HEADER_CLEARANCE_REM + 0.9}rem)) !important;
        width: 100% !important;
        border: 1px solid rgba(120, 150, 180, .22);
        border-radius: 6px;
      }}
      /* No page scrollbar: the component owns the viewport. */
      [data-testid="stAppViewContainer"] {{ overflow: hidden; }}
    </style>
    """,
    unsafe_allow_html=True,
)

record = run_selector.render()

if record is None:
    payload_b64, meta = payload.empty(None)
else:
    try:
        loaded = run_module.build(
            loader.load_run(record.stem, record.mtime, record.mtime)
        )
        payload_b64, meta = payload.pack(loaded)
    except loader.LoadError as exc:
        # A load failure is the run's problem, not the app's: say what went
        # wrong, keep the viewer up, and leave the sidebar usable.
        with st.sidebar:
            st.error(f"Could not load `{record.stem}`\n\n{exc}")
        payload_b64, meta = payload.empty(record)

component.render(payload_b64, meta, height=config.RENDER_HEIGHT_PX)
