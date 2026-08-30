/* 40_clock.js — playback. Spec 7, unchanged in substance, now running in the
 * browser rather than round-tripping to Python for every frame.
 *
 * Advance sim time by rate * wall_dt, then snap to the nearest sample at or
 * before the new time. Sample skipping, never interpolation. Playback stops at
 * the last sample.
 */

let lastWall = null;

/* The playback clock, in sim seconds, kept continuously.
 *
 * It has to be its own value rather than being read back from the current
 * sample. Advancing from `time[S.idx]` throws away the remainder every frame:
 * at 60 fps and a 1 s sample spacing, 1x gains 0.017 s, snaps to the sample it
 * started on, and discards the gain -- so playback sat still at 1x, 5x and 25x
 * and only moved at 100x, where one frame finally exceeded one sample.
 *
 * `frac` is where the clock sits between `S.idx` and the next sample, which is
 * what lets the scene interpolate instead of stepping once a second. */
let simTime = 0;
let frac = 0;

function setSimTime(seconds) {
  if (!S.run) return;
  const first = S.run.time[0], last = S.run.time[S.run.n - 1];
  simTime = Math.max(first, Math.min(last, seconds));
  S.idx = snapIndex(simTime);
  const next = Math.min(S.idx + 1, S.run.n - 1);
  const span = S.run.time[next] - S.run.time[S.idx];
  frac = span > 0 ? Math.max(0, Math.min(1, (simTime - S.run.time[S.idx]) / span)) : 0;
}

/* Binary search rather than a scan: spec 3.2 allows variable dt, so the sample
 * times cannot be assumed uniform and index arithmetic would be wrong. */
function snapIndex(tTarget) {
  const T = S.run.time;
  let lo = 0, hi = S.run.n - 1;
  if (tTarget <= T[0]) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (T[mid] <= tTarget) lo = mid; else hi = mid - 1;
  }
  return lo;
}

function setIdx(i) {
  if (!S.run) return;
  // Landing on a sample means landing exactly on it: stepping, scrubbing and
  // event seeking all pin the clock rather than leaving it mid-interval.
  const clamped = Math.max(0, Math.min(S.run.n - 1, i | 0));
  simTime = S.run.time[clamped];
  S.idx = clamped;
  frac = 0;
  snapEase();          // a scrub should read the rate for where it landed
}

/* The rate actually being played, after easing near a waypoint.
 *
 * The chosen rate is what the run cruises at; approaches are slowed towards
 * `easeFloor` of it as the chaser comes within `easeRange` of a waypoint.
 *
 * Distance to the **nearest** waypoint, not to the one being flown to. Those
 * differ at exactly the wrong moment: on arrival the target index advances and
 * the gap to it jumps from nothing to the whole next leg, so the clock leapt
 * from eased back to full speed in a single frame. The distance to the nearest
 * waypoint passes through that arrival smoothly -- it is small on the way in,
 * small on the way out, and large in between.
 *
 * Distance to the waypoint *centre*, not the range to the target, because that
 * is the gap actually closing.
 *
 * Reported as well as applied -- a clip that silently changes speed is a clip
 * whose numbers cannot be trusted, so the card shows both.
 */
/* The rate the geometry asks for, as a fraction of the chosen one.
 *
 * Measured to the nearest waypoint **not yet entered**. Once the chaser has
 * arrived there is nothing left to watch at that waypoint -- station keeping is
 * a vehicle holding still -- so the target returns to full speed.
 *
 * Using the nearest waypoint of any kind, as this did, left the terminal hold
 * eased for the rest of the run: parked a few metres from the innermost
 * waypoint's centre, the gap stays small forever.
 */
function easeTarget() {
  if (!S.easeNearWaypoints || !S.run) return 1;
  const gap = S.run.flat[S.idx * S.run.stride + OFF.wp_pending];
  if (!isFinite(gap)) return 1;                    // corridor complete
  const nearness = Math.min(1, Math.max(0, gap / S.easeRange));
  return S.easeFloor + (1 - S.easeFloor) * nearness;
}

/* The factor actually applied, chasing the target rather than snapping to it.
 *
 * Entry is a step: the instant a waypoint is entered it stops being pending and
 * the target jumps back to 1. Smoothing turns that into a ramp, which is the
 * same reason the approach is eased in the first place -- a clip whose speed
 * changes in a single frame reads as a glitch. Wall time, not sim time,
 * because this is a presentation control and the viewer counts in seconds.
 */
let easeFactor = 1;

function settleEase(wallDt) {
  const target = easeTarget();
  /* Asymmetric, like an audio envelope: quick to slow down, slow to speed up.
   *
   * A single time constant cannot serve both ends. At 100x the whole ease band
   * is crossed in a fraction of a wall second, so a gentle one misses the
   * approach entirely -- measured, the rate was still at 65x with the chaser
   * 6 m from the waypoint. A quick one would then snap back to full the instant
   * the waypoint is entered, which is the step this exists to remove. Braking
   * is the urgent direction; recovering is not.
   */
  const tau = target < easeFactor
    ? Math.max(0.02, S.easeBrakeSeconds)
    : Math.max(0.05, S.easeSettleSeconds);
  easeFactor += (target - easeFactor) * (1 - Math.exp(-wallDt / tau));
}

/** Snap the factor to where the geometry wants it, for scrubs and steps. */
function snapEase() { easeFactor = easeTarget(); }

function effectiveRate() {
  return S.rate * (S.easeNearWaypoints ? easeFactor : 1);
}

/** Where the clock sits between S.idx and the next sample, 0 to 1. */
const interpFraction = () => frac;

function togglePlay() {
  if (!S.run) return;
  S.playing = !S.playing;
  lastWall = null;
  document.getElementById('b_play').textContent = S.playing ? '⏸' : '▶';
}

/* Start the clock, whatever it was doing. `togglePlay` cannot serve here: a
 * restart that was already playing would pause instead of replaying. */
function startPlayback() {
  if (!S.run) return;
  S.playing = true;
  lastWall = null;
  document.getElementById('b_play').textContent = '\u23f8';
}

function stopPlayback() {
  S.playing = false;
  lastWall = null;
  document.getElementById('b_play').textContent = '▶';
}

function advance(nowMs) {
  if (!S.playing || !S.run) return;
  const wallDt = lastWall === null ? 0 : (nowMs - lastWall) / 1000;
  lastWall = nowMs;

  settleEase(wallDt);
  const last = S.run.time[S.run.n - 1];
  const wanted = simTime + effectiveRate() * wallDt;
  if (wanted >= last) {
    setIdx(S.run.n - 1);
    stopPlayback();
    return;
  }
  setSimTime(wanted);
}

/* Event seeking (spec 7). Events carry a sample INDEX, not a time.
 *
 * This is not incidental. Sample times cross into the browser as float32,
 * while an event time computed in Python is float64, so the two never compare
 * equal: seeking to an event lands on a sample whose stored time is a hair
 * below the event's, `e.t > time[idx]` is still true for the event you just
 * arrived at, and next-event seeking sticks on it forever. Comparing integer
 * indices removes the class of bug rather than papering it with an epsilon.
 *
 * It is also more faithful to the spec: every event in section 4.5/4.6 is
 * defined *at a sample* -- a waypoint arrival is the sample where wp_current
 * changes -- so the index is the primary fact and the time is derived.
 */
function seekEvent(dir) {
  if (!S.run || !S.run.events || !S.run.events.length) return;
  const ev = dir > 0
    ? S.run.events.find(e => e.i > S.idx)
    : [...S.run.events].reverse().find(e => e.i < S.idx);
  if (ev) setIdx(ev.i);
}
