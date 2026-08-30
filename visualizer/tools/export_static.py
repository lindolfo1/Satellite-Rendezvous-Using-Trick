"""Build the viewer as flat files for a static host such as GitHub Pages.

    python3 tools/export_static.py --out site

The viewer is already a self-contained document: `render/component.build_html`
inlines the stylesheet, the scripts, three.js, the Earth texture and the whole
run payload into one HTML file with no network calls. Only the Streamlit shell
around it -- scanning the runs folder, the sidebar -- is Python, and that is the
part a static host cannot run. So the export does that scanning once, at build
time, and writes what it found: one page per run, plus an index linking them.

The trade is that the run list is frozen when you publish. Adding a run means
running this again, which is the honest version of "no server".

**The published site is public.** GitHub Pages on a free account serves to
anyone with the URL even from a private repository, and each page carries the
full trajectory. That is a decision about the data, not about the tool.
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from data import discovery, loader, run as run_module  # noqa: E402
from render import component, payload  # noqa: E402

#: Kept deliberately plain: this page exists to get you into a run, and any
#: styling here competes with the viewer it links to.
INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rendezvous runs</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0; padding: 8vh 6vw; background: oklch(0.145 0.012 240);
    color: oklch(0.96 0.008 230);
    font: 16px/1.5 ui-monospace, "SF Mono", Menlo, monospace;
  }}
  h1 {{ font-size: 1.1rem; font-weight: 500; letter-spacing: 0.22em;
       text-transform: uppercase; color: oklch(0.60 0.018 230); margin: 0 0 3rem; }}
  ul {{ list-style: none; margin: 0; padding: 0; max-width: 60ch; }}
  li {{ border-top: 1px solid oklch(0.29 0.018 240); }}
  a {{ display: flex; justify-content: space-between; gap: 2rem;
      padding: 1.4rem 0; color: inherit; text-decoration: none; }}
  a:hover {{ color: oklch(0.80 0.15 152); }}
  .meta {{ color: oklch(0.60 0.018 230); font-size: 0.85rem; text-align: right; }}
</style>
<h1>Rendezvous runs</h1>
<ul>
{items}
</ul>
"""

ITEM_TEMPLATE = """  <li><a href="{href}">
    <span>{stem}</span>
    <span class="meta">{meta}</span>
  </a></li>"""


def export(runs_dir: Path, out_dir: Path) -> int:
    records = [r for r in discovery.scan(runs_dir) if r.available]
    if not records:
        print(f"no complete runs in {runs_dir}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    items = []

    for record in records:
        built = run_module.build(loader.load_raw(record))
        encoded, meta = payload.pack(built)
        document = component.build_html(encoded, meta)

        page = out_dir / f"{record.stem}.html"
        page.write_text(document, encoding="utf-8")
        size_mb = len(document.encode("utf-8")) / 1048576

        minutes = built.duration_s / 60
        summary = (f"{meta['n']:,} samples · {minutes:.0f} min · "
                   f"{len(built.burns)} burns · {size_mb:.1f} MB")
        items.append(ITEM_TEMPLATE.format(
            href=html.escape(page.name),
            stem=html.escape(record.stem),
            meta=html.escape(summary),
        ))
        print(f"  {page.name:38} {size_mb:5.1f} MB  {meta['n']:,} samples")

    (out_dir / "index.html").write_text(
        INDEX_TEMPLATE.format(items="\n".join(items)), encoding="utf-8")

    # Without this, GitHub Pages runs the output through Jekyll, which ignores
    # files beginning with an underscore and can rewrite what it thinks is
    # templating. The viewer is finished HTML and wants passing through.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    total = sum(p.stat().st_size for p in out_dir.glob("*.html")) / 1048576
    print(f"\n{len(records)} run(s) -> {out_dir}  ({total:.1f} MB total)")
    print("Publish by pointing GitHub Pages at this folder.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=Path(config.RUNS_DIR),
                        help="folder of <stem>.csv + <stem>.json pairs")
    parser.add_argument("--out", type=Path, default=ROOT / "site",
                        help="where to write the static site")
    args = parser.parse_args()
    return export(args.runs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
