"""Sidebar run list -- spec 1, 10.

The only panel still in Python. It is a load-time choice, so it belongs on the
Streamlit side: selecting a run rebuilds the payload and remounts the
component, which is exactly what should happen here and exactly why every
*other* control moved into the HUD.

Unavailable runs are listed with their reason rather than hidden, and the
resolved runs folder is always shown -- when nothing appears, the first
question is invariably "which folder is it actually looking at?".
"""

from __future__ import annotations

import streamlit as st

import config
import state
from data import discovery


def _fmt_utc(record: discovery.RunRecord) -> str:
    if record.utc_start is None:
        return "—"
    return record.utc_start.strftime("%Y-%m-%d %H:%M:%S") + "Z"


def render() -> discovery.RunRecord | None:
    """Draw the sidebar list and return the selected record, if any."""
    with st.sidebar:
        st.subheader("Runs")

        records = discovery.scan()
        available = [r for r in records if r.available]

        top = st.columns([3, 1])
        top[0].caption(f"`{config.RUNS_DIR}`")
        if top[1].button("↻", help="Rescan the folder", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

        if not config.RUNS_DIR.is_dir():
            st.error(
                f"The runs folder does not exist.\n\nCreate `{config.RUNS_DIR}` "
                "or point `RUNS_DIR` in `config.py` somewhere else."
            )
            return None

        if not records:
            st.warning(
                "No `.csv` / `.json` pairs found. Drop a matching pair into the "
                "folder above and press ↻."
            )
            return None

        selected_stem = st.session_state["run_stem"]

        for record in records:
            if record.available:
                is_current = record.stem == selected_stem
                if st.button(
                    ("● " if is_current else "") + record.stem,
                    key=f"run_{record.stem}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary",
                ):
                    state.select_run(record.stem)
                    st.rerun()
                st.caption(
                    f"{_fmt_utc(record)}  ·  {record.size_label}\n\n"
                    f"corridor {record.corridor_label}\n\n"
                    f"tolerance {record.tolerance_label}"
                )
            else:
                st.button(
                    record.stem,
                    key=f"run_{record.stem}",
                    use_container_width=True,
                    disabled=True,
                )
                st.caption(f":red[unavailable] — {record.reason}")

        if selected_stem and not any(r.stem == selected_stem for r in available):
            # The selected run was renamed or deleted while it was open.
            st.warning(f"`{selected_stem}` is no longer available.")
            state.select_run(None)
            selected_stem = None

        return next((r for r in available if r.stem == selected_stem), None)
