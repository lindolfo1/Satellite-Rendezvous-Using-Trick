/* 50_main.js — payload decode, wiring, and the render loop.
 *
 * Concatenated last. This is the only module that runs anything at load; the
 * others define.
 */

/* Decode. The obvious one-liner --
 *   Uint8Array.from(atob(s), c => c.charCodeAt(0))
 * -- routes every byte through a generic iterator and a JS callback, and
 * measured 856 ms at 100k samples and 2208 ms at 250k. The indexed loop below
 * is byte-identical and 20-70x faster (61 ms at 250k in the browser). Native
 * base64 via fetch('data:...') was tested and came third, because parsing a
 * 12 MB data URL costs more than the decode saves, and it would force this
 * module async. Do not "simplify" this back.
 */
function decodePayload(b64) {
  if (!b64) return null;
  const t0 = performance.now();
  const s = atob(b64);
  const bytes = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i);
  const flat = new Float32Array(bytes.buffer);
  const n = META.n;
  const stride = META.stride;
  // Column views over the interleaved block. Strided reads, no copies.
  const col = k => ({ get: i => flat[i * stride + k] });
  return {
    n, stride, flat,
    time: { length: n, ...col(0) },
    decodeMs: performance.now() - t0,
    events: META.events || [],
  };
}

/* time[] is read as an array in 40_clock.js, so give it real indexing rather
 * than a getter object. A typed copy of one column is cheap and makes the
 * clock's binary search a plain array access. */
function hydrate(b64) {
  const p = decodePayload(b64);
  if (!p) return null;
  const time = new Float64Array(p.n);
  for (let i = 0; i < p.n; i++) time[i] = p.flat[i * p.stride];
  return { n: p.n, stride: p.stride, flat: p.flat, time, events: p.events,
           decodeMs: p.decodeMs };
}

S.run = hydrate(PAYLOAD);

/* Empty state. A selected-but-unloaded run is a different situation from no
 * selection at all, and saying so avoids "I picked a run and nothing happened". */
const emptyEl = document.getElementById('empty');
emptyEl.hidden = !!S.run;
if (!S.run && META.pending) {
  emptyEl.innerHTML =
    `<strong>${META.stem}</strong><div>Sidecar read. The CSV loader arrives in Stage 3.</div>`;
}

buildRunGeometry(S.run);
buildTimeline(S.run);

// ---- wiring -------------------------------------------------------------
buildViewButtons();
buildRateButtons();

document.getElementById('b_play').onclick = togglePlay;
document.getElementById('b_start').onclick = () => { stopPlayback(); setIdx(0); };
document.getElementById('b_end').onclick = () => { stopPlayback(); setIdx(S.run ? S.run.n - 1 : 0); };
document.getElementById('b_prev').onclick = () => { stopPlayback(); setIdx(S.idx - 1); };
document.getElementById('b_next').onclick = () => { stopPlayback(); setIdx(S.idx + 1); };
document.getElementById('b_prevev').onclick = () => { stopPlayback(); seekEvent(-1); };
document.getElementById('b_nextev').onclick = () => { stopPlayback(); seekEvent(+1); };

document.getElementById('scrub').oninput = e => { stopPlayback(); setIdx(+e.target.value); };

/* Fine rate slider, spec 7. Geometric so the low end stays usable: the
 * presets are 1..500, and a linear slider would spend most of its travel above
 * 100x where nothing is readable anyway. */
document.getElementById('rate_fine').oninput = e => {
  S.rate = Math.round(Math.pow(10, (+e.target.value / 100) * Math.log10(500)) * 10) / 10;
  syncRateButtons();
};

document.getElementById('t_imu').onclick = () => { S.imu = !S.imu; HUD.options(); };
document.getElementById('t_rf').onclick = () => { S.rangefinder = !S.rangefinder; HUD.options(); };
for (const [id, key] of [['t_eci', 'showEci'], ['t_body', 'showBody'],
                         ['t_lvlh', 'showLvlh'], ['t_navframe', 'showNavFrame']]) {
  document.getElementById(id).onclick = () => { S[key] = !S[key]; HUD.options(); };
}
document.getElementById('t_nav').onclick = () => { S.showNav = !S.showNav; HUD.options(); };
document.getElementById('t_attnav').onclick = () => {
  S.showAttNav = !S.showAttNav; HUD.options();
};
/* Cinematic mode. The ordinary panels go away with it: the point is a clean
 * frame to record, and the engineering HUD is unreadable at video size. */
for (let pane = 0; pane < 3; pane++) {
  const select = document.getElementById(`pane${pane}`);
  select.innerHTML = VIEWS.map(([id, label]) =>
    `<option value="${id}">${label}</option>`).join('');
  select.value = S.panes[pane];
  select.onchange = () => {
    S.panes[pane] = select.value;
    resetPaneCam(pane);          // a new view starts at its own home framing
  };
}

buildCinePanel();

document.getElementById('t_cine').onclick = () => {
  S.cinematic = !S.cinematic;
  if (S.cinematic) {
    [0, 1, 2].forEach(resetPaneCam);
    S.easeNearWaypoints = true;      // the menu can turn it off again
  }
  document.body.classList.toggle('cinematic', S.cinematic);
  resize();
  HUD.all();
};

document.getElementById('t_graticule').onclick = () => {
  S.graticule = !S.graticule; HUD.options();
};
document.getElementById('t_arrowscale').onclick = () => {
  S.arrowScale = S.arrowScale === 'fixed' ? 'relative' : 'fixed';
  HUD.options();
};
document.getElementById('t_units').onclick = () => {
  S.units = { auto: 'm', m: 'km', km: 'auto' }[S.units];
  HUD.status();
};

addEventListener('keydown', e => {
  if (typingTarget()) return;
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  if (e.code === 'ArrowLeft') { stopPlayback(); setIdx(S.idx - 1); }
  if (e.code === 'ArrowRight') { stopPlayback(); setIdx(S.idx + 1); }
  if (e.code === 'Home') { stopPlayback(); setIdx(0); }
  if (e.code === 'End') { stopPlayback(); setIdx(S.run ? S.run.n - 1 : 0); }
});

// ---- loop ---------------------------------------------------------------
let frames = [], lastFrame = performance.now();

function tick(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  frames.push(now - lastFrame);
  if (frames.length > 60) frames.shift();
  lastFrame = now;

  advance(now);
  applyKeyboard(dt);
  /* Camera first, geometry second. The level-of-detail switch measures the
   * distance from the camera to each vehicle, so computing it against last
   * frame's camera made the satellites appear a full frame of orbital motion
   * away -- ~127 m at 60 fps, far more at 500x. A 1 m bus at 127 m is
   * sub-pixel, so they dropped to markers the instant playback started and
   * looked correct again the instant it stopped. */
  applyCamera(S.run, S.idx);
  updateRunGeometry(S.run, S.idx);
  if (S.cinematic && S.run) {
    renderCinematic(S.run, S.idx);
  } else {
    renderer.render(scene, activeCamera);
  }
  HUD.all();

  const mean = frames.reduce((a, b) => a + b, 0) / frames.length;
  document.getElementById('fps').textContent =
    `${(1000 / mean).toFixed(0)} fps · ${mean.toFixed(1)} ms` +
    (S.run ? ` · decode ${S.run.decodeMs.toFixed(0)} ms` : '');

  requestAnimationFrame(tick);
}

resize();
HUD.all();
requestAnimationFrame(tick);

// Tells the watchdog in viewer.html that everything above ran.
window.__viewerBooted = true;
console.info('viewer booted · three.js r' + (THREE.REVISION || '?') +
             ' · samples ' + (S.run ? S.run.n : 0));
