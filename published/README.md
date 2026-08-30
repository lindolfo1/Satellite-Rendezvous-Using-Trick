# Published runs

Runs in here are **tracked by git and built into the public site** by
`.github/workflows/pages.yml`. Everything in `runs/` is ignored.

The split is deliberate. `runs/` is your working folder — whatever you happen to
be looking at, private by default. This folder is a decision: putting a run here
says you intend the world to see it, because a published page carries the whole
trajectory and GitHub Pages serves to anyone with the URL even from a private
repository.

Same pairing as `runs/`: `<stem>.csv` and `<stem>.json` with matching stems.
