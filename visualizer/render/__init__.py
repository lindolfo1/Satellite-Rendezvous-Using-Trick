"""The render layer: packing a `Run` into a browser-side viewer component.

Stage 0 replaced the spec's Plotly render layer with a three.js component that
owns its own render loop. `payload.py` packs, `component.py` assembles and
injects, `static/` is the viewer itself.
"""
