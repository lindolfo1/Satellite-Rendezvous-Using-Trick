/* 45_cinepanel.js -- the cinematic stats card.
 *
 * Numbered before 50_main.js on purpose: main builds the panel at load, and a
 * `const` in a later file is still in its temporal dead zone when that runs.
 *
 * Its own module because it answers to a different reader. The engineering HUD
 * is for someone scrubbing their own run, who wants ECI components and validity
 * flags. This is for someone watching a twenty-second video on a phone with the
 * sound off, deciding in about a second whether to keep watching.
 *
 * That difference drives every choice here: one hero number rather than a
 * column of equals, a corridor rail that shows the shape of the approach
 * without being read, and a transport that exists because a capture is useless
 * if you cannot start it.
 */

//: Playback rates worth offering here. The full ladder belongs on the
//: engineering panel; a 1800 s run wants 100x to land near twenty seconds.
const CINE_RATES = [1, 25, 100, 250, 400, 500];

//: Rebuilt when the run changes, not every frame.
let timelineStem = null;

/* The settings menu. Everything that is a *choice* lives behind one control, so
 * the recorded frame carries data rather than switches. */
function buildCineMenu() {
  const bind = (id, key) => {
    const box = document.getElementById(id);
    box.checked = !!S[key];
    box.onchange = () => { S[key] = box.checked; };
  };
  bind('m_nav', 'showNav');
  bind('m_att', 'showAttNav');
  bind('m_track', 'showNavTrack');
  bind('m_ease', 'easeNearWaypoints');
  bind('m_flash', 'flashMinorBurns');

  const range = document.getElementById('m_range');
  const rangeOut = document.getElementById('m_range_out');
  range.value = S.easeRange;
  const showRange = () => { rangeOut.value = `${range.value} m`; };
  range.oninput = () => { S.easeRange = Number(range.value); showRange(); };
  showRange();

  const floor = document.getElementById('m_floor');
  const floorOut = document.getElementById('m_floor_out');
  floor.value = Math.round(S.easeFloor * 100);
  const showFloor = () => { floorOut.value = `${floor.value}%`; };
  floor.oninput = () => { S.easeFloor = Number(floor.value) / 100; showFloor(); };
  showFloor();

  document.getElementById('c_exit').onclick = () => {
    S.cinematic = false;
    document.body.classList.remove('cinematic');
    resize();
    HUD.all();
  };
}

/* Burns and arrivals, laid out once against the run's own clock. Burn spans
 * are drawn at their true duration, which on a 1800 s run makes a 12 s burn a
 * sliver -- so each is given a floor width, or the very thing the timeline
 * exists to show would be invisible. */
function buildCineTimeline() {
  const run = S.run;
  const track = document.getElementById('c_track');
  if (!run || !track) return;
  const span = run.time[run.n - 1] - run.time[0];
  if (span <= 0) return;

  const at = index => (run.time[index] - run.time[0]) / span * 100;
  /* Burns and arrivals are different kinds of event and are drawn as different
   * marks: a burn has a duration, so it is a bar; an arrival is an instant, so
   * it is a tick with a head. Drawing both as coloured bars made the arrivals
   * read as very short burns. */
  const peak = META.burn_dv_max || 1;
  const marks = (META.burns || []).map(burn => {
    const left = at(burn.i0);
    const width = Math.max(0.8, at(burn.i1) - left);
    // Station-keeping corrections are marked, but thinner: they belong on the
    // record without crowding out the burns that shaped the approach.
    // Station-keeping corrections are texture, not events: dozens of
    // full-strength marks turned the strip into a thicket over exactly the part
    // of the run worth watching.
    const minor = burn.dv < peak * S.burnMinorFraction ? ' minor' : '';
    return `<div class="burn${minor}" style="left:${left}%;width:${width}%"
                 title="burn ${burn.dv.toFixed(2)} m/s"></div>`;
  });
  marks.push(...(META.events || [])
    .filter(event => event.kind === 'waypoint')
    .map(event => `<div class="arrival" style="left:${at(event.index)}%"
                        title="${event.label || 'waypoint'}"></div>`));
  track.innerHTML = marks.join('');
}

function buildCinePanel() {
  buildCineMenu();
  const rates = document.getElementById('c_rates');
  rates.innerHTML = CINE_RATES
    .map(r => `<button data-rate="${r}" aria-pressed="false">${r}\u00d7</button>`)
    .join('');
  rates.querySelectorAll('button').forEach(button => {
    button.onclick = () => {
      S.rate = Number(button.dataset.rate);
      HUD.cinematic();
      HUD.time();
    };
  });

  document.getElementById('c_play').onclick = () => {
    togglePlay();
    HUD.cinematic();
  };

  /* Restart without leaving the mode. A take that goes wrong needs another
   * take, and dropping out to the engineering transport to get one loses the
   * pane framing along with the moment. Keeps playing if it was playing, so
   * the next take starts immediately. */
  document.getElementById('c_restart').onclick = () => {
    const wasPlaying = S.playing;
    setIdx(0);
    if (wasPlaying) startPlayback();
    HUD.all();
  };
}

/* A phase name, so the viewer knows what they are looking at without a caption.
 * Taken from what the run is doing, not from a script. */
function approachPhase(run, i, range) {
  const f = run.flat;
  if (f[i * run.stride + OFF.thrusting] > 0.5) return 'burn';
  if ((f[i * run.stride + OFF.wp_target] | 0) < 0) return 'station keeping';
  if (range < 25) return 'terminal approach';
  return 'approach';
}

function updateCinePanel() {
  const card = document.getElementById('cine');
  card.hidden = !S.cinematic;
  if (!S.cinematic || !S.run) return;

  // The menu reflects state rather than owning it: entering the mode turns
  // easing on, and the boxes have to agree with that.
  for (const [id, key] of [['m_nav', 'showNav'], ['m_att', 'showAttNav'],
                           ['m_track', 'showNavTrack'], ['m_ease', 'easeNearWaypoints'],
                           ['m_flash', 'flashMinorBurns']]) {
    document.getElementById(id).checked = !!S[key];
  }

  const run = S.run, b = S.idx * run.stride, f = run.flat;
  const range = f[b + OFF.true_range];

  const elapsed = run.time[S.idx] - run.time[0];
  /* Hours when there are hours. mm:ss with an unbounded minutes field reads
   * "378:27" six hours into a run, which is not a duration anyone parses. */
  const hh = Math.floor(elapsed / 3600);
  const mm = Math.floor((elapsed % 3600) / 60);
  const ss = Math.floor(elapsed % 60);
  const pad = n => String(n).padStart(2, '0');
  document.getElementById('c_elapsed').textContent =
    hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${mm}:${pad(ss)}`;
  document.getElementById('c_phase').textContent = approachPhase(run, S.idx, range);

  /* Range without its unit in the hero, because the unit belongs to the label
   * and a number that gains a character mid-approach shifts everything after
   * it. */
  const inKm = range >= 1000;
  document.getElementById('c_range').textContent =
    inKm ? `${(range / 1000).toFixed(3)} km` : `${range.toFixed(1)} m`;

  const closing = f[b + OFF.closing_rate];
  const rate = document.querySelector('#cine_card .hero .under');
  const holding = Math.abs(closing) < 0.005;
  rate.className = `under${holding ? ' holding' : closing < 0 ? ' opening' : ''}`;
  document.getElementById('c_arrow').textContent =
    holding ? '\u25cf' : closing > 0 ? '\u25bc' : '\u25b2';
  document.getElementById('c_closing').textContent =
    `${Math.abs(closing).toFixed(2)} m/s`;

  document.getElementById('c_dv').textContent = `${f[b + OFF.dv].toFixed(2)} m/s`;
  document.getElementById('c_nav').textContent = META.has_relnav
    ? `${Math.hypot(f[b + OFF.nav_err], f[b + OFF.nav_err + 1],
                    f[b + OFF.nav_err + 2]).toFixed(2)} m`
    : '\u2014';

  /* The rail: one segment per waypoint, widths proportional to the leg each
   * covers, so the shape of the corridor is visible rather than implied. */
  const corridor = META.waypoint_range_m || [];
  const entered = f[b + OFF.wp_entered_mask] | 0;
  const flying = f[b + OFF.wp_target] | 0;
  const rail = document.getElementById('c_rail');
  if (rail.childElementCount !== corridor.length) {
    rail.innerHTML = corridor
      .map((m, k) => `<i data-label="${m}m" style="flex:${k === 0 ? 3 : 2}"></i>`)
      .join('');
  }
  [...rail.children].forEach((pip, k) => {
    pip.className = (entered & (1 << k)) ? 'done' : (k === flying ? 'active' : '');
  });

  /* The timeline is laid out once per run, and only the playhead moves. */
  if (timelineStem !== META.stem) { buildCineTimeline(); timelineStem = META.stem; }
  const span = run.time[run.n - 1] - run.time[0];
  document.getElementById('c_head').style.left =
    `${span > 0 ? (elapsed / span) * 100 : 0}%`;

  /* The chosen rate is already shown by the pressed button, so repeating it as
   * a large number said the same thing twice at two sizes. Only the difference
   * is worth words: what it has been eased *to*. */
  const playing = effectiveRate();
  document.getElementById('c_speed_note').textContent =
    Math.abs(playing - S.rate) < 0.05
      ? ''
      : `eased to ${playing >= 10 ? Math.round(playing) : playing.toFixed(1)}\u00d7`;

  document.getElementById('c_play').textContent = S.playing ? '\u275a\u275a' : '\u25b6';
  document.querySelectorAll('#c_rates button').forEach(button => {
    button.setAttribute('aria-pressed', String(Number(button.dataset.rate) === S.rate));
  });

  /* The wall-clock stamp is optional furniture -- the redesign dropped it in
   * favour of the elapsed timer, which is what a viewer actually reads. Guard
   * both the element and the epoch: a missing element threw and took the whole
   * frame with it, and a sidecar without an epoch would throw on toISOString. */
  const stamp = document.getElementById('c_utc');
  if (stamp) {
    stamp.textContent = META.utc_start_ms
      ? `${new Date(META.utc_start_ms + elapsed * 1000).toISOString().slice(11, 19)}Z`
      : '';
  }
}
