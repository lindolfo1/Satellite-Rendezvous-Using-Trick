/* 35_timeline.js — the event strip on the scrubber's time axis (spec 7).
 *
 * Built once per run, not per frame: the bars and ticks do not move, only the
 * playhead does. Positions are fractions of elapsed sim time, so a burn's bar
 * is as wide as the burn was long.
 *
 * This is what makes short events findable at high playback rates. At 500x a
 * two-second burn falls entirely between two frames, so the only way to see it
 * is that it is drawn here regardless.
 */

function timelineFraction(run, index) {
  const span = run.time[run.n - 1] - run.time[0];
  return span > 0 ? (run.time[index] - run.time[0]) / span : 0;
}

function buildTimeline(run) {
  const strip = document.getElementById('timeline');
  const playhead = document.getElementById('playhead');
  [...strip.querySelectorAll('.burn, .wp')].forEach(el => el.remove());
  if (!run) return;

  for (const burn of (META.burns || [])) {
    const a = timelineFraction(run, burn.i0);
    const b = timelineFraction(run, burn.i1);
    const bar = document.createElement('div');
    bar.className = 'burn';
    bar.style.left = (a * 100) + '%';
    bar.style.width = Math.max(0.35, (b - a) * 100) + '%';
    bar.title = `Burn · ${burn.dur.toFixed(1)} s · ${burn.dv.toFixed(3)} m/s`;
    strip.appendChild(bar);
  }

  for (const ev of (META.events || [])) {
    if (ev.kind !== 'waypoint') continue;
    const tick = document.createElement('div');
    tick.className = 'wp';
    tick.style.left = (timelineFraction(run, ev.i) * 100) + '%';
    tick.title = ev.label;
    strip.appendChild(tick);
  }

  strip.appendChild(playhead);   // keep the playhead on top

  /* Click to seek. The strip is a time axis, so the click maps to a time and
   * then snaps to a sample -- not to an index directly, which would be wrong
   * wherever dt varies. */
  strip.onclick = e => {
    const box = strip.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - box.left) / box.width));
    stopPlayback();
    setIdx(snapIndex(run.time[0] + frac * (run.time[run.n - 1] - run.time[0])));
  };
}
