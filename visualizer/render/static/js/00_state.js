/* 00_state.js — browser-side state. The single source of truth during a session.
 *
 * Why this lives here and not in Python: any change to the injected HTML
 * remounts the iframe and resets the scene, so every per-frame and
 * per-interaction control must be owned by the browser. Python owns only the
 * load-time choice of which run to inject. See render/component.py.
 *
 * Concatenated first; nothing below it may be referenced above it.
 */

const S = {
  // Decoded run. Null until Stage 3 wires the loader through payload.py.
  run: null,

  // Playback — spec 7.
  idx: 0,
  playing: false,
  rate: 1,

  // Views — spec 9. `view` drives `policy`; see 20_camera.js.
  view: 'plane_chaser',

  // View options — spec 9b.
  imu: false,
  rangefinder: false,
  arrowScale: 'fixed',      // 'fixed' | 'relative'

  /* Coordinate frames. All three are drawn from the same packed quaternions;
   * see the note in 07_arrows.js on why the sensor frame and LVLH share a
   * triad but not a set of axis names. */
  showEci: false,
  showBody: false,          // chaser sensor frame: x along-track, y normal, z radial
  showLvlh: false,          // target's LVLH, drawn on both vehicles

  //: The relative-navigation estimate: ghost and estimated track.
  showNav: false,

  /* Cinematic mode: three views in a 2x2 grid with a stats card in the fourth
   * quadrant, panels hidden. Built for screen capture, so the panes are not
   * individually steerable -- each sits at its view's home camera. */
  cinematic: false,
  panes: ['plane_target', 'rel_target', 'local_chaser'],

  /* How much orbit to draw either side of now, in revolutions.
   *
   * The whole track is rarely the useful picture: on a multi-orbit run the
   * orbits overlay themselves into a band, and where the vehicle is going next
   * is buried in where it went two revolutions ago. A window keeps the line
   * about the present pass. */
  orbitWindow: 0.7,

  /* Station-keeping burns flash rather than accumulate.
   *
   * Holding at the innermost waypoint takes a long string of small corrections.
   * Drawn like the trajectory burns they pile up into a thicket at exactly the
   * point of the run a viewer is meant to be watching. Anything below
   * `burnMinorFraction` of the run's largest burn is shown for
   * `burnFlashSeconds` of sim time after it fires and then clears; the burns
   * that actually shaped the approach stay.
   */
  flashMinorBurns: true,
  burnFlashSeconds: 1.0,
  burnMinorFraction: 0.05,

  //: The estimated track in the relative views, separate from the ghost: the
  //: history of what the filter believed, rather than what it believes now.
  showNavTrack: false,

  /* Ease the clock down near a waypoint.
   *
   * A rendezvous is mostly waiting punctuated by arrivals. At the one rate that
   * makes the transits watchable, every arrival -- the part worth seeing -- is
   * over in a few frames. This trades that back. */
  //: Off by default: easing is a presentation choice, and someone scrubbing
  //: their own run should get the rate they asked for. Cinematic mode turns it
  //: on when entered, and the menu can turn it off again.
  easeNearWaypoints: false,
  //: Distance at which easing begins, metres, and the slowest fraction of the
  //: chosen rate it will fall to.
  easeRange: 60,
  easeFloor: 0.12,
  /* How quickly the applied rate chases the geometry, in wall seconds. Braking
   * has to be quick or a fast run crosses the whole ease band before the clock
   * reacts; recovering is gentle, because entering a waypoint is a step and
   * this is what turns it into a ramp. */
  easeBrakeSeconds: 0.12,
  easeSettleSeconds: 1.4,

  //: The attitude estimate: a triad where the chaser believes its body frame
  //: points. Separate from showNav -- position and pointing are estimated by
  //: different filters and go wrong independently.
  showAttNav: false,
  //: The believed body frame, drawn on the ghost.
  showNavFrame: false,

  // Chrome — spec 10.
  units: 'auto',            // 'auto' | 'm' | 'km'
  /* Prime meridian and equator, in the ECEF frame. Off by default: it exists to
   * check the texture seam against the computed rotation, and left on it just
   * looks like a stray line lying on the Earth. */
  graticule: false,

  /* Note: spec 10 asks for independently show/hide-able panels. The toggle bar
   * that provided it has been removed -- it sat across the top centre, in the
   * render area, to hide panels that are small and useful. The panels are
   * always shown. */
  panels: { stats: true, views: true, options: true, status: true, time: true },
};

/* Spec 9. Each view names the satellite it is anchored to and the camera
 * policy it enforces, so selecting a view sets the constraint automatically
 * rather than leaving them to drift apart. */
const VIEWS = [
  ['plane_chaser', 'Plane · chaser', 'Orbit plane defined by the chaser, centred on Earth', 'pan_zoom'],
  ['plane_target', 'Plane · target', 'Orbit plane defined by the target, centred on Earth', 'pan_zoom'],
  ['local_chaser', 'Local · chaser',
   'Over the chaser\u2019s shoulder, 50 m back, with the target in frame', 'rotate_zoom'],
  ['local_target', 'Local · target',
   'Over the target\u2019s shoulder, 50 m back, with the chaser in frame', 'rotate_zoom'],
  ['rel_target', 'Relative · on target',
   'The chaser\u2019s track in the target\u2019s rotating frame \u2014 what the rangefinder plots',
   'free'],
  ['rel_chaser', 'Relative · on chaser',
   'The same track, framed on the chaser: the target closes in as the approach runs',
   'free'],
];

const RATES = [1, 5, 25, 100, 500];

/* Offsets into a packed sample. Mirrors render/payload.py's OFFSETS; the two
 * must change together. Read from META when present so a mismatch shows up as
 * wrong data rather than silently reading the wrong column. */
/* Earth constants arrive with the payload. They live in core/earth.py and
 * nowhere else (spec 6.4); the 6371 km that used to be hard-coded here
 * disagreed with the simulation, which is built on WGS84, by 7 km. */
const EARTH_R_KM = META.earth_r_km || 6378.137;
const TEXTURE_SEAM_LON_DEG = (META.texture_seam_lon_deg === undefined)
  ? -180 : META.texture_seam_lon_deg;

//: Fixed-policy arrow length as a fraction of the visible scene, from config.py.
const ARROW_FIXED_FRAC = META.arrow_fixed_frac || 0.35;

//: See config.IMU_DVEL_FLOOR_FRACTION.
const IMU_DVEL_FLOOR_FRACTION = META.imu_dvel_floor_fraction || 1e-3;

const OFF = META.offsets || {
  time: 0, chaser_pos: 1, target_pos: 4,
  chaser_quat: 7, target_quat: 11, dv: 15, wp: 16, thrusting: 17,
};

const viewDef = id => VIEWS.find(v => v[0] === id);

/* Sensor toggles are chaser-only: the target carries no sensors in this data
 * (spec 9b), so the buttons grey out rather than lying. */
const isChaserView = () => S.view.endsWith('chaser');
