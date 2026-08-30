"""Assemble the viewer HTML and hand it to Streamlit.

Two constraints shape this module, and both are consequences of Stage 0's
architecture decision rather than preferences.

**Everything must be inlined.** `st.components.v1.html` renders into a `srcdoc`
iframe, which has an opaque origin and no base URL, so relative paths do not
resolve. The stylesheet, every JS module, and three.js itself are read from disk
and substituted into the shell.

Three.js used to come from a CDN. It is vendored now because a failed import
inside a `srcdoc` iframe is invisible -- no listeners bind, nothing renders, and
the empty state stays up because the code that hides it never ran, which reads
as "the app is broken" rather than "a request failed".

**Re-injecting remounts the component.** Streamlit re-sends the HTML whenever
the string changes, and the iframe remounts when it does -- resetting the
camera, the clock and every toggle. So this must be called with a string that
depends *only* on the selected run. Anything the user changes during a session
belongs in browser state (`js/00_state.js`), not in a Python widget that would
rebuild this string.

That second point is why spec 10's panel toggles live in the HUD rather than in
the Streamlit sidebar.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import config

import streamlit as st
import streamlit.components.v1 as components

STATIC = Path(__file__).parent / "static"
JS_DIR = STATIC / "js"


def _js_sources() -> list[Path]:
    """The JS modules, in concatenation order.

    There is no bundler, so the numeric filename prefix *is* the dependency
    order and the files must not import from one another. Sorting by name is
    what enforces it; a new module picks a number that places it correctly.
    """
    return sorted(JS_DIR.glob("*.js"))


#: Extensions tried for the Earth map, in order.
_TEXTURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".png": "image/png", ".webp": "image/webp"}


def earth_texture_path() -> Path | None:
    """The Earth map on disk, or None. Missing is not an error."""
    directory = STATIC / "textures"
    stem = Path(config.EARTH_TEXTURE_NAME).stem
    for suffix in _TEXTURE_SUFFIXES:
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _earth_texture_data_uri() -> str:
    """The Earth map as a data URI, or "" when there is none.

    Inlined for the same reason three.js is: a relative URL cannot resolve
    inside a `srcdoc` iframe, and a failed fetch there is invisible. The cost is
    that the encoded image rides along with every run load, so a 2 MB map adds
    2.7 MB to the document -- worth downscaling to 2048x1024 if it is larger.
    """
    path = earth_texture_path()
    if path is None:
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{_MIME[path.suffix.lower()]};base64,{encoded}"


def build_html(payload_b64: str, meta: dict) -> str:
    """Substitute the four slots in the shell and return the full document."""
    shell = (STATIC / "viewer.html").read_text()
    css = (STATIC / "hud.css").read_text()
    js = "\n".join(p.read_text() for p in _js_sources())

    texture = _earth_texture_data_uri()

    three_path = STATIC / "vendor" / "three.module.min.js"
    if not three_path.is_file():
        raise RuntimeError(
            f"vendored three.js is missing at {three_path}. "
            "See render/static/vendor/README.md for how to restore it."
        )
    three = three_path.read_text()

    # Order matters: JS is substituted last so that a stray placeholder in the
    # CSS or the payload can never be interpreted as a slot. Stage 0 lost an
    # hour to a placeholder that appeared twice, which doubled the payload.
    for slot, value in (("__CSS__", css), ("__META__", json.dumps(meta)),
                        ("__THREE__", three), ("__EARTH_TEXTURE__", texture),
                        ("__PAYLOAD__", payload_b64), ("__JS__", js)):
        if shell.count(slot) != 1:
            raise RuntimeError(
                f"{slot} appears {shell.count(slot)} times in viewer.html; "
                "expected exactly 1"
            )
        shell = shell.replace(slot, value)
    return shell


def render(payload_b64: str, meta: dict, height: int) -> None:
    """Draw the viewer. Call once per rerun, with a run-dependent payload.

    `st.components.v1.html` is deprecated and slated for removal, so `st.iframe`
    is used where available. The two render iframes with different `title`
    attributes, which is why app.py's height CSS matches on the container rather
    than the title -- a title-based selector would break silently on this swap,
    leaving a correctly-working viewer at the wrong size.
    """
    html = build_html(payload_b64, meta)
    if hasattr(st, "iframe"):
        st.iframe(html, height=height, width="stretch")
    else:
        components.html(html, height=height, scrolling=False)
