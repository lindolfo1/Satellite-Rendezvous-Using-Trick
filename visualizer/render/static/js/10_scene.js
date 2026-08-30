/* 10_scene.js — renderer, scene graph, and the empty state.
 *
 * Unlit and flat throughout: no sun vector, no terminator, no specular
 * (spec 5). Wireframe outlines carry the shape reading.
 *
 * Scene units are KILOMETRES. WebGL vertex attributes are float32, which
 * resolves 0.49 mm at a 6800 km orbit radius in km, against 0.5 m if the same
 * geometry arrived in metres. Nothing here may convert to metres.
 */

/* THREE is bound by the preamble in viewer.html, which imports the vendored
 * copy from a blob URL. No bare import here: the modules are concatenated into
 * one script, so an import statement would have to be hoisted above code that
 * is already using it. */

const canvas = document.getElementById('gl');
/* Logarithmic depth: one scene holds a 1 m satellite and a 6378 km Earth, and
 * a linear depth buffer cannot resolve both.
 *
 * Constructing the renderer is the only line in this project that node cannot
 * test -- the harness stubs WebGLRenderer -- so it degrades rather than
 * throwing. A driver that refuses the log depth buffer should cost some depth
 * precision in the local view, not the entire viewer. */
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true,
                                       logarithmicDepthBuffer: true });
} catch (err) {
  console.warn('log depth buffer unavailable, falling back:', err);
  renderer = new THREE.WebGLRenderer({ canvas });
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setClearColor(0x0b0f14, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.5, 400000);

/* The orbit-plane view is orthographic, and that is not a style choice.
 *
 * A 500 km orbit sits 7.8% above the surface. Under perspective, looking down
 * the orbit normal, the sphere's silhouette is *nearer* than the ring, so the
 * limb is foreshortened less: at 3.2 orbit radii the gap collapses to 3% of the
 * disc, and closer than 2.68 radii the ring projects INSIDE the limb and the
 * solid globe occludes an orbit that is genuinely above it. Zooming in made the
 * track disappear into the Earth.
 *
 * Orthographic has no foreshortening, so the ring is a constant 7.8% outside
 * the disc at every zoom and nothing occludes it. Spec 9a asked for a 2D
 * projection onto the orbit plane; this is that, and it is why. */
const orthoCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 1e7);
orthoCamera.up.set(0, 0, 1);

//: Whichever camera the current view uses. Set by applyCamera.
let activeCamera = camera;
/* ECI is +Z-up. Rather than permuting axes on the way in -- the obvious swap
 * (x, z, y) is a mirror, not a rotation, and quietly flips the handedness of
 * every orientation -- the scene simply uses ECI axes and tells the camera
 * which way is up. Views override this per frame. */
camera.up.set(0, 0, 1);

/* Earth.
 *
 * Two groups, both spun about ECI +Z, because they need different angles:
 *
 *   earthFrame  rotates by GMST exactly, and carries anything defined in
 *               ECEF -- the prime meridian and the equator.
 *   earthSpin   rotates by GMST plus a texture offset, and carries the mapped
 *               sphere.
 *
 * Keeping them apart means the graticule is drawn from the *computed* rotation
 * with no texture assumptions in it. If the map's Greenwich sits on the drawn
 * prime meridian, the seam constant is right; if it does not, the offset is
 * wrong and the graticule is still trustworthy.
 */
const earthFrame = new THREE.Group();
const earthSpin = new THREE.Group();
scene.add(earthFrame);
scene.add(earthSpin);

const earthWire = new THREE.LineSegments(
  new THREE.WireframeGeometry(new THREE.SphereGeometry(EARTH_R_KM, 24, 16)),
  new THREE.LineBasicMaterial({ color: 0x2b4055 })
);
earthSpin.add(earthWire);

/* The mapped globe. three.js builds a sphere with +Y at the pole and u = 0
 * facing -X; ECI has +Z at the pole. The inner mesh tips the sphere onto the
 * ECI axis and the outer group carries the spin, so the two rotations stay
 * separable and neither has to know about the other. */
/* The globe exists whether or not there is a map to put on it. A solid sphere
 * also occludes: with only a wireframe, a satellite on the far side showed
 * through the Earth, which is wrong in every view and actively misleading in
 * the sat-to-sat one, where occlusion is the thing being demonstrated. */
const earthMaterial = new THREE.MeshBasicMaterial({ color: 0x0f1a26 });
const earthMesh = new THREE.Mesh(
  new THREE.SphereGeometry(EARTH_R_KM, 96, 48),
  earthMaterial                                     // unlit, per spec 5
);
earthMesh.rotation.x = Math.PI / 2;
earthSpin.add(earthMesh);

if (EARTH_TEXTURE) {
  new THREE.TextureLoader().load(
    EARTH_TEXTURE,
    tex => {
      if ('colorSpace' in tex) tex.colorSpace = THREE.SRGBColorSpace;
      earthMaterial.map = tex;
      earthMaterial.color.set(0xffffff);
      earthMaterial.needsUpdate = true;
      earthWire.visible = false;      // the map carries the shape now
    },
    undefined,
    err => console.warn('Earth texture failed to decode, keeping wireframe:', err)
  );
}

/* Prime meridian and equator, in ECEF, so they ride `earthFrame`. These are the
 * check on the texture alignment, and on GMST itself. */
function ring(points, colour) {
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color: colour })
  );
}
const meridianPoints = [];
for (let i = 0; i <= 180; i++) {
  const lat = (-90 + i) * Math.PI / 180;
  meridianPoints.push(new THREE.Vector3(
    EARTH_R_KM * Math.cos(lat) * 1.001, 0, EARTH_R_KM * Math.sin(lat) * 1.001));
}
const equatorPoints = [];
for (let i = 0; i <= 360; i++) {
  const lon = i * Math.PI / 180;
  equatorPoints.push(new THREE.Vector3(
    EARTH_R_KM * Math.cos(lon) * 1.001, EARTH_R_KM * Math.sin(lon) * 1.001, 0));
}
const graticule = new THREE.Group();
graticule.add(ring(meridianPoints, 0xe0c060));   // prime meridian
graticule.add(ring(equatorPoints, 0x3d5a75));
earthFrame.add(graticule);

/* Earth turns at the *sidereal* rate: 360.9856 degrees per solar day, not 360.
 * theta comes from core/earth.py per sample, so playback and scrubbing show the
 * same orientation for the same instant. */
function updateEarth(run, i) {
  // Interpolated: a raw read steps the Earth 500 m of surface per sample.
  const gmst = run ? readAngle(run, i, OFF.gmst) : 0;
  earthFrame.rotation.z = gmst;
  // u = 0 on the map is TEXTURE_SEAM_LON_DEG, and the tipped sphere puts u = 0
  // at right ascension pi, hence the offset.
  earthSpin.rotation.z = gmst + TEXTURE_SEAM_LON_DEG * Math.PI / 180 - Math.PI;
  graticule.visible = S.graticule;
}

/* Reference grid, shown only while no run is loaded, so the camera policies can
 * be exercised against something before there is geometry to draw. */
const grid = new THREE.GridHelper(EARTH_R_KM * 6, 24, 0x2b4055, 0x1a2530);
grid.rotation.x = Math.PI / 2;
scene.add(grid);

/* Run geometry. Built once per load, never per frame -- the traversed portion
 * of the path is expressed with setDrawRange, which costs nothing, rather than
 * by rebuilding a growing buffer (spec 9a).
 *
 * `runGroup` holds **only the path lines**, because it carries the reference
 * offset those lines are measured from. Anything positioned in absolute world
 * coordinates must live elsewhere, or it inherits that offset and lands at
 * twice the orbit radius. */
const runGroup = new THREE.Group();
scene.add(runGroup);

/* The vehicles, in absolute coordinates and therefore not in `runGroup`. */
const vehicleGroup = new THREE.Group();
scene.add(vehicleGroup);

let mChaser = null, mTarget = null, mNavGhost = null, gTraversed = null;
const pathLines = [];
const orbitLines = { chaser: null, target: null, traversed: null };

/* The chaser's track in the **target's LVLH** -- the shape a rangefinder plot
 * has, and the reason the relative-motion view exists.
 *
 * Vertices are the packed relative position resolved in the target's frame, so
 * they are metre-scale numbers and exact in float32, unlike the orbit tracks
 * which sit on a 0.49 m grid. They are stored in body-axis order
 * (along-track, normal, radial) so the target's own quaternion orients them --
 * no permutation quaternion needed, since that quaternion already maps
 * x to along-track, y to normal, z to radial.
 *
 * The group is rotated by that quaternion every frame, so the track turns with
 * the target's frame exactly as the plot should. */
const relLvlhGroup = new THREE.Group();
scene.add(relLvlhGroup);
let relLvlhFull = null, relLvlhTraversed = null, relLvlhEstimate = null;
let relLvlhSource = null;
const relBurnArrows = [];

/* Points along each drawn orbit.
 *
 * Odd on purpose: with an even count the centre falls between two samples and
 * the line passes 118 km from the vehicle it belongs to. Odd puts a vertex
 * exactly on the present state.
 *
 * 513 across 1.4 revolutions is a vertex per degree, so the chord cuts the
 * corner by 260 m on a 6878 km orbit -- invisible where this line is drawn, and
 * the accurate recorded track is drawn over it near the vehicle anyway.
 */
const ORBIT_POINTS = 513;
const _orbitPos = new THREE.Vector3();
const _orbitVel = new THREE.Vector3();

//: Longest relative-view burn arrow, as a fraction of the framed separation.
const REL_BURN_MAX_FRAC = 0.22;

function buildRelativeTrack(run) {
  relLvlhGroup.clear();
  relLvlhFull = relLvlhTraversed = relLvlhEstimate = null;
  relLvlhSource = null;
  relBurnArrows.length = 0;
  if (!run) return;

  const pos = new Float32Array(run.n * 3);
  for (let i = 0; i < run.n; i++) {
    const b = i * run.stride + OFF.rel_lvlh;   // R, V, H
    pos[i * 3] = run.flat[b + 1] * M_TO_KM;    // along-track -> local x
    pos[i * 3 + 1] = run.flat[b + 2] * M_TO_KM; // normal      -> local y
    pos[i * 3 + 2] = run.flat[b] * M_TO_KM;     // radial      -> local z
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3));

  /* The estimated track, dashed, beside the true one: in the relative-motion
   * view this is where navigation error actually reads, because you watch the
   * belief wander off the truth and come back. */
  if (META.has_relnav) {
    const est = new Float32Array(run.n * 3);
    for (let i = 0; i < run.n; i++) {
      const b = i * run.stride + OFF.nav_est_lvlh;
      est[i * 3] = run.flat[b + 1] * M_TO_KM;      // V -> local x
      est[i * 3 + 1] = run.flat[b + 2] * M_TO_KM;  // H -> local y
      est[i * 3 + 2] = run.flat[b] * M_TO_KM;      // R -> local z
    }
    const estGeometry = new THREE.BufferGeometry();
    estGeometry.setAttribute('position', new THREE.BufferAttribute(est, 3));
    relLvlhEstimate = new THREE.Line(estGeometry,
      new THREE.LineDashedMaterial({ color: 0xff6b9d, dashSize: 0.004, gapSize: 0.003 }));
    relLvlhEstimate.computeLineDistances();
    relLvlhGroup.add(relLvlhEstimate);
  }

  relLvlhSource = pos;

  /* Burn arrows on the relative track.
   *
   * The plane view marks each ignition on the orbit; the relative views need
   * the same information in the frame they are drawn in, because "a burn
   * happened here" is only useful next to the track it changed. Position and
   * direction are both resolved into the target's LVLH at the ignition sample,
   * so the arrow sits in the group and inherits its motion.
   *
   * Length is proportional to that segment's delta-V, with the largest burn in
   * the run drawn at REL_BURN_MAX_FRAC of the frame -- the same policy the
   * plane view uses against the Earth's radius.
   */
  relBurnArrows.length = 0;
  const peakDv = META.burn_dv_max || 1;
  const span = ((META.arrow_max && META.arrow_max.range) || 1000) * M_TO_KM;
  for (const burn of (META.burns || [])) {
    const arrow = makeArrow(0xffca28, 0.22);
    // Axes at the ignition sample. The clock sits at sample 0 during build, so
    // this reads the sample rather than an interpolated pose.
    const axes = lvlhAxes(run, burn.i0, OFF.target_quat);
    const dir = new THREE.Vector3(burn.dir[0], burn.dir[1], burn.dir[2]);
    const local = new THREE.Vector3(
      dir.dot(axes[1]),                       // along-track -> local x
      dir.dot(axes[2]),                       // normal      -> local y
      dir.dot(axes[0])                        // radial      -> local z
    );
    const b = burn.i0 * run.stride + OFF.rel_lvlh;
    const root = new THREE.Vector3(run.flat[b + 1] * M_TO_KM,
                                   run.flat[b + 2] * M_TO_KM,
                                   run.flat[b] * M_TO_KM);
    aimArrow(arrow, root, local, span * REL_BURN_MAX_FRAC * (burn.dv / peakDv));
    relLvlhGroup.add(arrow);
    relBurnArrows.push({ arrow, burn });
  }
  relLvlhFull = new THREE.Line(geometry,
                               new THREE.LineBasicMaterial({ color: 0x6b83a0 }));
  relLvlhTraversed = new THREE.Line(geometry.clone(),
                                    new THREE.LineBasicMaterial({ color: 0xd6e6f5 }));
  relLvlhGroup.add(relLvlhFull);
  relLvlhGroup.add(relLvlhTraversed);
}

/* The relative track: where the *other* vehicle has been, as seen from the one
 * the view is anchored on.
 *
 * The absolute orbit paths are useless close up. A 25 m local scene spans 3 ms
 * of flight along the orbit, so the track through it is a straight line with no
 * structure -- and seen from on the orbit it runs off toward the horizon and
 * appears to lie on the Earth, which is correct and completely uninformative.
 * The relative track spans the entire approach, 1000 m down to 1 m, and is what
 * a rendezvous view is actually for.
 *
 * Its vertices are the packed relative vector, so they are exact rather than
 * the difference of two 0.49 m-quantised absolutes. The group is moved to the
 * anchor vehicle each frame -- one translation, no per-frame vertex work -- and
 * flipped by scale for the target-anchored views, where the chaser's position
 * relative to the target is simply the negative. */

/* Vector arrows and coordinate frames, all anchored on a vehicle. Built once
 * and re-aimed each frame; nothing here allocates during playback. */
const vectorGroup = new THREE.Group();
scene.add(vectorGroup);

const arrows = {
  velocity: makeArrow(0x9ccc65, 0.16, ['v', 'ECI']),
  thrust: makeArrow(0xffca28, 0.16, ['a', 'thrust']),
  imu: makeArrow(0xba68c8, 0.16, ['\u0394v', 'IMU']),
  rangefinder: makeArrow(0x4dd0e1, 0.16, ['LOS', 'rf']),
};
Object.values(arrows).forEach(a => addArrow(vectorGroup, a));

/* Three frames, three subscripts. Two of them are the same triad under
 * different axis names, so the labels are what tell them apart -- see the note
 * in 07_arrows.js. `lvlhChaser` carries the *target's* LVLH: LVLH is the
 * target's frame, and a rendezvous is flown in it. */
const triads = {
  /* Where the chaser believes its body frame points, from attNav.qHat. Drawn
   * as a frame rather than as a position-error arrow: an attitude estimate is
   * an orientation, and three labelled axes say which way each body axis is
   * believed to point, which a single vector cannot. */
  attnav: makeTriad('qHat'),
  eci: makeTriad('ECI'),
  body: makeTriad('IMU'),
  lvlhTarget: makeTriad('LVLH'),
  /* Drawn dashed, labelled with its provenance, and tied back to the target by
   * a line. It *is* the target's frame -- 0.00 urad from the target's radial
   * against 145.50 urad from the chaser's -- but it cannot look different from
   * the chaser's sensor triad, because spec 3.4 builds that triad the same way
   * and the two vehicles' frames are parallel to 0.008 degrees. Solid means
   * "this vehicle's own"; dashed with a tether means "carried from there". */
  lvlhChaser: makeTriad('LVLH(tgt)', true),
  /* The believed body frame, on the ghost. Dashed like everything else the
   * filter believes rather than measures. */
  navBody: makeTriad('est', true),
};

/* The tether: chaser to target, so the transported frame has a visible source. */
const lvlhTether = new THREE.Line(
  new THREE.BufferGeometry().setFromPoints(
    [new THREE.Vector3(), new THREE.Vector3()]),
  new THREE.LineDashedMaterial({ color: 0x6f7f8f, dashSize: 0.02, gapSize: 0.02 })
);
vectorGroup.add(lvlhTether);
Object.values(triads).forEach(t => vectorGroup.add(t));

const _dir = new THREE.Vector3();
const _unitX = new THREE.Vector3(1, 0, 0);

//: Fractional tolerance on each standoff, from the sidecar.
const tolerance = META.tolerance || 0.02;

/* The drawn sphere is a little wider than the tolerance it stands for, so a
 * vehicle sitting exactly on the limit is inside a visible shell rather than
 * embedded in the wireframe.
 *
 * Display only. Entry is still decided against the true tolerance in
 * data/waypoints.py -- inflating that instead would quietly redefine what green
 * means, and the panel and the spheres would be answering different questions.
 */
const WAYPOINT_SPHERE_MARGIN = 1.1;

const COLOR_WAYPOINT_TODO = 0x2f4858;   // still ahead
const COLOR_WAYPOINT_DONE = 0x4caf50;   // guidance has moved past it

/* Hiding a triad has to hide its labels too: they are siblings of the arrows,
 * not children, so that a screen-space sprite is not scaled by the arrow's
 * length. Setting `visible` on the group alone would leave three glyphs
 * floating where the axes used to be. */
function hideTriad(triad) {
  triad.visible = false;
  triad.userData.axes.forEach(arrow => {
    arrow.visible = false;
    if (arrow.userData.label) arrow.userData.label.visible = false;
  });
}

/* Burn arrows and the waypoint corridor, both for the orbit-plane view.
 *
 * Burn arrows are rooted at each ignition point, along that segment's mean
 * thrust direction, with length proportional to its delta-V and the largest
 * burn in the run drawn at 8% of the Earth's radius (spec 9a). Burns later than
 * the current time are hidden: a plot that shows you a manoeuvre before it has
 * happened is telling you the answer. */
const burnGroup = new THREE.Group();
scene.add(burnGroup);
const burnArrows = [];

const corridorGroup = new THREE.Group();
scene.add(corridorGroup);

function buildPlaneFurniture(run) {
  burnGroup.clear();
  burnArrows.length = 0;
  corridorGroup.clear();
  if (!run) return;

  for (const burn of (META.burns || [])) {
    const arrow = makeArrow(0xffca28, 0.22);
    burnGroup.add(arrow);
    burnArrows.push({ arrow, burn });
  }

  /* Each waypoint is a **place**, not a range.
   *
   * It sits on the V-bar at its standoff behind the target -- along the
   * target's velocity, in the opposite direction -- and the ball around it is
   * the position tolerance, |tolerance x standoff|. Drawing shells at the
   * standoff radius instead, as this did first, put the surface everywhere
   * around the target including in front of it and out of plane, which is not
   * where the chaser is ever asked to be.
   *
   * The group is oriented so its local +X is the target's velocity, so each
   * waypoint sits at local (-standoff, 0, 0) and needs no per-frame work.
   * Coarse on purpose: a dense wireframe at four radii is a net. */
  for (const metres of (META.waypoint_range_m || [])) {
    const ball = new THREE.LineSegments(
      new THREE.WireframeGeometry(
        new THREE.SphereGeometry(
          Math.abs(tolerance * metres) * WAYPOINT_SPHERE_MARGIN * M_TO_KM, 16, 8)),
      new THREE.LineBasicMaterial({
        color: 0x2f4858, transparent: true, opacity: 0.55,
      })
    );
    ball.position.x = -metres * M_TO_KM;
    ball.userData.standoff = metres;
    corridorGroup.add(ball);
  }
}

const _burnDir = new THREE.Vector3();
const _burnPos = new THREE.Vector3();

function updatePlaneFurniture(run, i) {
  const planeView = S.view.startsWith('plane');
  burnGroup.visible = planeView && !!run;
  // The corridor is shown everywhere: it is where the chaser is going, which
  // is as relevant 25 m out as it is from orbit.
  corridorGroup.visible = !!run;
  if (run) {
    const where = vehiclePositions(run, i);
    corridorGroup.position.copy(where.target);

    /* Point local +X along the target's velocity, so the waypoints laid out at
     * negative local X land behind it on the V-bar. Taken from the velocity
     * itself rather than from the body quaternion's along-track axis: those
     * differ by the radial component of velocity, which is zero only on a
     * circular orbit, and the sidecar means the velocity vector. Roll about
     * that axis is unconstrained and irrelevant -- these are spheres. */
    readVec3Interp(run, i, OFF.target_vel, _dir);
    if (_dir.lengthSq() > 0) {
      corridorGroup.quaternion.setFromUnitVectors(_unitX, _dir.normalize());
    }

    /* Green once the chaser has actually been *inside* the ball.
     *
     * Not when it reaches that range: the chaser can sit at 751 m and still be
     * 40 m from the 750 m waypoint's centre, because the waypoint is a place on
     * the V-bar and the chaser can be off it. Range alone turned balls green
     * before the vehicle arrived in them.
     *
     * Not from `currentWaypoint` either -- its index base and naming convention
     * are not always separable. Measured in data/run.py and packed as a mask,
     * so the balls and the stats panel cannot disagree. */
    const entered = run.flat[i * run.stride + OFF.wp_entered_mask] | 0;
    corridorGroup.children.forEach((ball, k) => {
      ball.material.color.setHex((entered & (1 << k))
        ? COLOR_WAYPOINT_DONE : COLOR_WAYPOINT_TODO);
    });
  }
  if (!burnGroup.visible) return;

  // Longest arrow = 8% of the Earth's radius, everything else linear from it.
  const peak = META.burn_dv_max || 1;
  const longest = EARTH_R_KM * (META.burn_arrow_max_frac || 0.08);

  for (const { arrow, burn } of burnArrows) {
    if (!burnMarkerVisible(run, i, burn)) { arrow.visible = false; continue; }
    _burnPos.set(burn.pos[0], burn.pos[1], burn.pos[2]);
    _burnDir.set(burn.dir[0], burn.dir[1], burn.dir[2]);
    aimArrow(arrow, _burnPos, _burnDir, longest * (burn.dv / peak));
  }

}

/* Arrow length: a fixed fraction of the visible scene, so it stays legible at
 * any zoom rather than being a fixed number of kilometres that vanishes or
 * swallows the view.
 *
 * `reference` is the point whose distance sets the scale, and it is not always
 * the anchor. In the sat-to-sat views the camera sits *on* the anchor vehicle,
 * so the distance is zero, the length came out zero, and every arrow -- not
 * just the thrust one -- was hidden. There the other vehicle sets the scale. */
function arrowBaseLength(reference) {
  const dist = activeCamera.position.distanceTo(reference);
  return kmPerPixel(dist) * viewportHeight() * ARROW_FIXED_FRAC * 0.5;
}

function scaledLength(base, magnitude, peak) {
  if (S.arrowScale !== 'relative') return base;
  if (!peak || !isFinite(peak)) return base;
  return base * Math.min(1, Math.abs(magnitude) / peak);
}

function updateVectors(run, i) {
  const anchored = !S.view.startsWith('plane');
  vectorGroup.visible = anchored && !!run;
  if (!vectorGroup.visible) return;

  const at = vehiclePositions(run, i);
  const onTarget = S.view === 'local_target' || S.view === 't2c';
  const anchor = onTarget ? at.target : at.chaser;
  const other = onTarget ? at.chaser : at.target;
  const atCamera = S.view === 'c2t' || S.view === 't2c';
  const base = arrowBaseLength(atCamera ? other : anchor);
  const b = i * run.stride;
  const f = run.flat;
  const peaks = META.arrow_max || {};

  // Velocity: always, per spec 9b.
  const velOff = b + (onTarget ? OFF.target_vel : OFF.chaser_vel);
  _dir.set(f[velOff], f[velOff + 1], f[velOff + 2]);
  aimArrow(arrows.velocity, anchor, _dir,
           scaledLength(base, _dir.length(), peaks.speed) * ARROW_EMPHASIS.velocity);

  // Thrust: only while thrusting, and only on the chaser -- the target has no
  // propulsion in this data.
  const thrusting = f[b + OFF.thrusting] > 0.5;
  const ta = b + OFF.thrust_acc;
  _dir.set(f[ta], f[ta + 1], f[ta + 2]);
  if (thrusting && !onTarget) {
    aimArrow(arrows.thrust, anchor, _dir,
             scaledLength(base, _dir.length(), peaks.thrust) * ARROW_EMPHASIS.thrust);
  } else {
    aimArrow(arrows.thrust, anchor, _dir, 0);
  }

  /* Sensors are chaser-only, and an invalid reading is not drawn at all --
   * a stale measurement must never appear as a current one (criterion 8). */
  const sensorsHere = !onTarget;
  const sensorAxes = sensorFrameAxes(run, i, OFF.chaser_quat);

  const imuValid = f[b + OFF.imu_valid] > 0.5;
  const d = b + OFF.imu_dvel;
  _dir.copy(sensorAxes[0]).multiplyScalar(f[d])
      .addScaledVector(sensorAxes[1], f[d + 1])
      .addScaledVector(sensorAxes[2], f[d + 2]);
  /* Below the noise floor there is no direction to draw. Under the
   * direction-only policy the arrow is full length whatever the magnitude, so a
   * 1e-6 m/s coasting reading -- pure sensor noise -- was thrown across the
   * scene and span 75 to 146 degrees between frames. The panel still reports
   * the measurement; it is the arrow that is meaningless, not the number. */
  const imuFloor = (peaks.imu_dv || 0) * IMU_DVEL_FLOOR_FRACTION;
  if (S.imu && sensorsHere && imuValid && _dir.length() > imuFloor) {
    aimArrow(arrows.imu, anchor, _dir,
             scaledLength(base, _dir.length(), peaks.imu_dv) * ARROW_EMPHASIS.imu);
  } else {
    aimArrow(arrows.imu, anchor, _dir, 0);
  }

  const rfValid = f[b + OFF.rf_valid] > 0.5;
  if (S.rangefinder && sensorsHere && rfValid) {
    const los = bearingToWorld(sensorAxes, f[b + OFF.rf_az], f[b + OFF.rf_el]);
    aimArrow(arrows.rangefinder, anchor, los,
             scaledLength(base, f[b + OFF.rf_range], peaks.range)
             * ARROW_EMPHASIS.rangefinder);
  } else {
    aimArrow(arrows.rangefinder, anchor, _dir, 0);
  }

  /* Navigation estimate: ghost, error arrow, and the estimated track. Hidden
   * unless the run carries a filter state whose frame was identified. */
  const navShown = S.showNav && META.has_relnav && !!mNavGhost;
  if (navShown) {
    const e = b + OFF.nav_err;
    const ghostAt = at.chaser.clone().add(
      new THREE.Vector3(f[e], f[e + 1], f[e + 2]).multiplyScalar(M_TO_KM));
    mNavGhost.position.copy(ghostAt);
    /* Rotated by the believed attitude, not copied from the true one: a
     * position ghost that always faces the right way would hide half of what
     * the navigation is getting wrong. From `attNav.qHat` where the run has
     * it, and otherwise from the filter's leftover attitude error. */
    if (META.has_attnav) {
      readQuaternion(run, i, OFF.att_quat, _attQuat);
      mNavGhost.quaternion.copy(_attQuat).multiply(MESH_FROM_BODY);
    } else {
      readQuaternion(run, i, OFF.nav_quat, mNavGhost.quaternion);
    }
    mNavGhost.visible = true;
    applyLod(mNavGhost);
  } else if (mNavGhost) {
    mNavGhost.visible = false;
  }

  /* The believed body frame, on its own toggle.
   *
   * This replaces a pink arrow from true position to believed position. An
   * attitude estimate is an orientation, and three labelled axes say which way
   * each body axis is believed to point; a single vector cannot. Position and
   * pointing also come from different filters and go wrong independently, so
   * seeing one should not require showing the other. */
  if (S.showAttNav && META.has_attnav && sensorsHere) {
    readQuaternion(run, i, OFF.att_quat, _attQuat);
    aimTriad(triads.attnav, anchor, [
      new THREE.Vector3(1, 0, 0).applyQuaternion(_attQuat),
      new THREE.Vector3(0, 1, 0).applyQuaternion(_attQuat),
      new THREE.Vector3(0, 0, 1).applyQuaternion(_attQuat),
    ], base * TRIAD_SCALE.lvlh);
  } else {
    hideTriad(triads.attnav);
  }

  // ---- coordinate frames ------------------------------------------------
  if (S.showEci) {
    aimTriad(triads.eci, anchor,
             [new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 1, 0),
              new THREE.Vector3(0, 0, 1)],
             base * TRIAD_SCALE.eci);
  } else hideTriad(triads.eci);

  if (S.showBody && sensorsHere) {
    aimTriad(triads.body, anchor, sensorAxes, base * TRIAD_SCALE.body);
  } else hideTriad(triads.body);

  /* One LVLH, the target's, drawn at both vehicles: a rendezvous is flown in
   * the target's frame, so the chaser carries a copy of it rather than its own.
   * At 1000 m the two differ by 1.5e-4 rad and would look identical anyway. */
  /* The believed body frame: the sensor frame's axes as the filter has them,
   * so it can be held against the solid `sensor` triad and the difference read
   * off directly. */
  if (S.showNavFrame && navShown) {
    aimTriad(triads.navBody, mNavGhost.position,
             sensorFrameAxes(run, i, OFF.nav_quat), base * TRIAD_SCALE.body);
  } else hideTriad(triads.navBody);

  if (S.showLvlh) {
    const axes = lvlhAxes(run, i, OFF.target_quat);
    aimTriad(triads.lvlhTarget, at.target, axes, base * TRIAD_SCALE.lvlh);
    aimTriad(triads.lvlhChaser, at.chaser, axes, base * TRIAD_SCALE.lvlh);

    // Redraw the tether: two points, so rebuilding beats transforming.
    const positions = lvlhTether.geometry.attributes.position;
    positions.setXYZ(0, at.chaser.x, at.chaser.y, at.chaser.z);
    positions.setXYZ(1, at.target.x, at.target.y, at.target.z);
    positions.needsUpdate = true;
    lvlhTether.computeLineDistances();
    lvlhTether.visible = true;
  } else {
    hideTriad(triads.lvlhTarget);
    hideTriad(triads.lvlhChaser);
    lvlhTether.visible = false;
  }
}

/* Absolute positions in double precision, reconstructed once at load.
 *
 * The payload carries the chaser position split across two float32s -- see the
 * note on `chaser_lo_x` in render/payload.py -- because float32 alone resolves
 * only 0.49 m at orbit radius. JS numbers are float64, so adding the halves
 * here recovers the true position to picometres. The target is that plus the
 * exact relative vector.
 *
 * Everything downstream reads these, not the packed float32s. */
let absChaser = null, absTarget = null;
let fineChaser = null, fineTarget = null;

/* Sub-samples per interval when drawing a path.
 *
 * The samples are a *curve*, not a polygon. Joining them with straight segments
 * cuts the corner: at 1 Hz the chord falls 1053 mm short of the arc, peaking
 * exactly mid-interval and vanishing at each sample -- a sawtooth with a period
 * of one data point, which is what makes the orbit appear to jump against
 * anything that follows the true trajectory.
 *
 * Eight sub-samples leaves 1053 / 8^2 = 16 mm, which is nothing at any scale
 * this tool draws at. */
const PATH_SUBDIVISIONS = 8;

/* Cubic Hermite between two samples, using the logged velocities as the end
 * tangents. That is not a smoothing spline fitted to the points -- it is the
 * trajectory the state vectors describe, so over one interval it reproduces the
 * orbit to the micron where a straight line is a metre out. */
function hermite(p0, v0, p1, v1, dt, f, out, at) {
  const f2 = f * f, f3 = f2 * f;
  const h00 = 2 * f3 - 3 * f2 + 1;
  const h10 = f3 - 2 * f2 + f;
  const h01 = -2 * f3 + 3 * f2;
  const h11 = f3 - f2;
  for (let k = 0; k < 3; k++) {
    out[at + k] = h00 * p0[k] + h10 * dt * v0[k]
                + h01 * p1[k] + h11 * dt * v1[k];
  }
}

function decodeAbsolutePositions(run) {
  absChaser = absTarget = fineChaser = fineTarget = null;
  if (!run) return;
  absChaser = new Float64Array(run.n * 3);
  absTarget = new Float64Array(run.n * 3);
  for (let i = 0; i < run.n; i++) {
    const b = i * run.stride;
    const hi = b + OFF.chaser_pos, lo = b + OFF.chaser_pos_lo, r = b + OFF.rel_pos;
    for (let k = 0; k < 3; k++) {
      const value = run.flat[hi + k] + run.flat[lo + k];
      absChaser[i * 3 + k] = value;
      absTarget[i * 3 + k] = value + run.flat[r + k] * M_TO_KM;
    }
  }

  // The drawn paths, subdivided along the Hermite curve rather than chorded.
  const fineCount = (run.n - 1) * PATH_SUBDIVISIONS + 1;
  fineChaser = new Float64Array(fineCount * 3);
  fineTarget = new Float64Array(fineCount * 3);
  const p0 = [0, 0, 0], p1 = [0, 0, 0], v0 = [0, 0, 0], v1 = [0, 0, 0];

  for (const [coarse, fine, velOffset] of
       [[absChaser, fineChaser, OFF.chaser_vel], [absTarget, fineTarget, OFF.target_vel]]) {
    for (let i = 0; i < run.n - 1; i++) {
      const dt = run.time[i + 1] - run.time[i];
      for (let k = 0; k < 3; k++) {
        p0[k] = coarse[i * 3 + k];
        p1[k] = coarse[(i + 1) * 3 + k];
        // Velocities are m/s; the scene is kilometres.
        v0[k] = run.flat[i * run.stride + velOffset + k] * M_TO_KM;
        v1[k] = run.flat[(i + 1) * run.stride + velOffset + k] * M_TO_KM;
      }
      for (let s = 0; s < PATH_SUBDIVISIONS; s++) {
        hermite(p0, v0, p1, v1, dt, s / PATH_SUBDIVISIONS, fine,
                (i * PATH_SUBDIVISIONS + s) * 3);
      }
    }
    const last = (run.n - 1) * 3;
    for (let k = 0; k < 3; k++) fine[(fineCount - 1) * 3 + k] = coarse[last + k];
  }
}

const _chaserPos = new THREE.Vector3();
const _targetPos = new THREE.Vector3();

/* Straight-line interpolation between the sample either side of the clock.
 *
 * A 1 s sample spacing against a 60 Hz display means 59 frames out of 60 have
 * nothing new to show, and the vehicles jump once a second. Over one interval a
 * straight line is close enough: the chord across 1 s at orbital rate falls
 * 1.05 m short of the arc, against a 7.6 km step -- 0.014%, and both vehicles
 * are cut the same way, so the separation between them is unaffected. That is
 * the number that matters here, and it is why nothing more elaborate is worth
 * the effort.
 *
 * Positions only. Attitude is left at the sample: the body frame turns 0.06
 * degrees per second, which no one can see, and slerping it would be effort
 * spent on nothing. */
const _hermiteOut = new Float64Array(3);
const _p0 = [0, 0, 0], _p1 = [0, 0, 0], _v0 = [0, 0, 0], _v1 = [0, 0, 0];

function hermiteAt(run, coarse, velOffset, i, f, target) {
  const j = i * 3;
  if (f <= 0 || i >= run.n - 1) {
    return target.set(coarse[j], coarse[j + 1], coarse[j + 2]);
  }
  const dt = run.time[i + 1] - run.time[i];
  for (let k = 0; k < 3; k++) {
    _p0[k] = coarse[j + k];
    _p1[k] = coarse[j + 3 + k];
    _v0[k] = run.flat[i * run.stride + velOffset + k] * M_TO_KM;
    _v1[k] = run.flat[(i + 1) * run.stride + velOffset + k] * M_TO_KM;
  }
  hermite(_p0, _v0, _p1, _v1, dt, f, _hermiteOut, 0);
  return target.set(_hermiteOut[0], _hermiteOut[1], _hermiteOut[2]);
}

function vehiclePositions(run, i) {
  const f = interpFraction();
  hermiteAt(run, absChaser, OFF.chaser_vel, i, f, _chaserPos);
  hermiteAt(run, absTarget, OFF.target_vel, i, f, _targetPos);
  return { chaser: _chaserPos, target: _targetPos };
}

function buildRunGeometry(run) {
  decodeAbsolutePositions(run);
  grid.visible = !run;
  runGroup.clear();
  runGroup.position.set(0, 0, 0);
  vehicleGroup.clear();
  mChaser = mTarget = gTraversed = null;
  if (!run) return;

  /* Vertices are stored **relative to a reference point**, and the group is
   * translated to it. Absolute float32 vertices are on a 0.49 m grid at orbit
   * radius, which is what made the tracks shimmer; relative to a nearby
   * reference the magnitudes are small and the error scales with distance from
   * it -- 0.12 mm at 1 km out, 61 mm at 1000 km, 1 m at the far side of the
   * orbit, i.e. it grows exactly where it stops being visible.
   *
   * The subtraction happens in float64 against the reconstructed positions, so
   * nothing inherits the packed grid. `refreshPaths` moves the reference as the
   * camera travels. */
  /* A propagated orbit: its own buffer, rewritten each frame from the state. */
  const orbitLine = colour => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position',
                   new THREE.BufferAttribute(new Float32Array(ORBIT_POINTS * 3), 3));
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: colour }));
    runGroup.add(line);
    return { geometry: g, line };
  };

  const path = (source, colour) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position',
                   new THREE.BufferAttribute(new Float32Array(source.length), 3));
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: colour }));
    line.userData.source = source;
    runGroup.add(line);
    return { geometry: g, line };
  };

  /* Brightened rather than thickened: WebGL ignores `linewidth`, so every
   * THREE.Line is one pixel wide whatever the material says. Getting real
   * thickness means vendoring three's Line2, which builds each segment as
   * screen-space quads -- a much larger change than these tracks warrant.
   * Contrast is the lever that is actually available. */
  /* The dim line is the *orbit*, propagated from the current state, not the
   * recorded track. See js/08_kepler.js: a recorded track has nothing behind
   * the vehicle at the start of a run and nothing ahead at the end, which is
   * exactly where "0.7 orbits either side" has to mean something. */
  const chaserPath = orbitLine(0x6b83a0);
  const targetPath = orbitLine(0xa87d5c);

  /* The track the chaser actually flew, brighter, drawn over the propagated
   * orbit. Built from the recorded samples -- not cloned from the conic, which
   * has a different vertex count entirely and would leave this holding 513
   * points where the history needs one per sub-sample.
   *
   * Keeping both is the point: the conic says where the orbit goes, the record
   * says where the vehicle went, and any disagreement between them is visible
   * as the gap rather than hidden by drawing only one. */
  const recorded = path(fineChaser, 0xd6e6f5);
  gTraversed = recorded.geometry;

  // Named rather than indexed: the relative-motion view shows the target's
  // orbit and hides the chaser's, which an anonymous list cannot express.
  orbitLines.chaser = chaserPath.line;
  orbitLines.target = targetPath.line;
  orbitLines.traversed = recorded.line;
  pathLines.length = 0;
  // Only the recorded track is written relative to the moving reference; the
  // conics are rebuilt from the state every frame.
  pathLines.push(recorded.line);

  pathReferenceValid = false;
  buildRelativeTrack(run);

  const vehicle = colour => {
    const g = buildCubesat(colour);
    vehicleGroup.add(g);
    return g;
  };
  mChaser = vehicle(0x4fc3f7);
  mTarget = vehicle(0xff8a65);

  /* The navigation estimate: the chaser drawn as a dashed skeleton where it
   * believes it is. Only built when the run carries a filter state whose frame
   * was identified -- see data/relnav.py. */
  if (META.has_relnav) {
    mNavGhost = buildCubesat(0xff6b9d, true);
    vehicleGroup.add(mNavGhost);
  }

  buildPlaneFurniture(run);

}

/* The reference the path vertices are measured from, and how far the anchor may
 * drift before they are rewritten. The threshold is scaled by the visible scene
 * so that a zoomed-out view -- where the error could not be seen anyway -- does
 * not pay for rebuilds it does not need. */
const pathReference = new THREE.Vector3();
let pathReferenceValid = false;
const PATH_REBUILD_MIN_KM = 25;

function rewritePaths(reference) {
  pathReference.copy(reference);
  pathReferenceValid = true;
  for (const line of pathLines) {
    const source = line.userData.source;
    const attribute = line.geometry
                   && line.geometry.attributes
                   && line.geometry.attributes.position;
    // A line with no source, or none of the buffer this rewrites, is simply
    // not one of the tracks -- skip it rather than assuming the list is pure.
    if (!source || !attribute) continue;
    const out = attribute.array;
    for (let k = 0; k < source.length; k += 3) {
      out[k] = source[k] - reference.x;
      out[k + 1] = source[k + 1] - reference.y;
      out[k + 2] = source[k + 2] - reference.z;
    }
    attribute.needsUpdate = true;
    line.geometry.computeBoundingSphere();
  }
  runGroup.position.copy(reference);
}

function refreshPaths(anchor, sceneKm) {
  const threshold = Math.max(PATH_REBUILD_MIN_KM, sceneKm);
  if (!pathReferenceValid || pathReference.distanceTo(anchor) > threshold) {
    rewritePaths(anchor);
  }
}

const _attQuat = new THREE.Quaternion();

/* Mesh axes to simulation body axes.
 *
 * The cubesat is authored with its nose on +x and its wings on +/-y, which
 * matches the internal triad order (along-track, normal, radial) the true
 * vehicle is drawn with. `attNav.qHat` is in the *sim's* body frame, whose axes
 * are (radial, along-track, normal) -- the sensor convention the rangefinder
 * bearings confirm.
 *
 * Applying qHat straight to the mesh therefore lands the nose on radial, so the
 * ghost points up, with the wings on along-track, a 90 degree roll about that
 * nose. This permutation is the difference:
 *
 *     mesh x (nose)  -> body y (along-track)
 *     mesh y (wings) -> body z (normal)
 *     mesh z         -> body x (radial)
 *
 * which is a 120 degree turn about (1, 1, 1). The *triad* needs no such fix --
 * its axes are labelled x_qHat and so on, and those are the body axes
 * themselves. */
const MESH_FROM_BODY = new THREE.Quaternion().setFromAxisAngle(
  new THREE.Vector3(1, 1, 1).normalize(), 2 * Math.PI / 3);
const _relTip = new THREE.Vector3();
const _origin = new THREE.Vector3();

/* Should a burn's marker be on screen at this moment?
 *
 * Trajectory burns persist once fired -- the arrow is a record of the manoeuvre
 * and where it happened. Station-keeping corrections do not: holding at the
 * innermost waypoint fires a long string of small burns, and left on screen
 * they become a thicket over the part of the run worth watching.
 */
function burnMarkerVisible(run, i, burn) {
  if (burn.i0 > i) return false;                      // not fired yet
  if (!S.flashMinorBurns) return true;
  const peak = META.burn_dv_max || 1;
  if (burn.dv >= peak * S.burnMinorFraction) return true;
  return (run.time[i] - run.time[burn.i0]) <= S.burnFlashSeconds;
}

/* Draw a track up to the *present* position rather than the last sample.
 *
 * The bright portion used to stop at sample `i`, while the vehicle it belongs
 * to was drawn at the interpolated position between `i` and `i + 1`. At 1 Hz
 * that left the tip trailing by up to 7.5 km, snapping forward once a second --
 * which reads as the line juddering against the satellite. It is the same
 * sample-versus-interpolated split that made the camera jump, not floating
 * point.
 *
 * The tip is written into the *next* sample's slot, which is not drawn yet, and
 * restored from the source before the clock reaches it. Appending a spare
 * vertex at the end of the buffer does not work: `setDrawRange` is a contiguous
 * span, so it would draw the next sample rather than the spare. */
/* The sample range within `orbitWindow` revolutions either side of now.
 *
 * Time-based rather than a fixed number of samples, because dt varies and a
 * sample count would mean different amounts of orbit on different runs. */
function orbitWindowSamples(run, i) {
  const period = META.orbit_period_s || 0;
  if (!period || !S.orbitWindow) return [0, run.n - 1];

  const span = S.orbitWindow * period;
  const now = run.time[i];
  const find = target => {
    let lo = 0, hi = run.n - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (run.time[mid] < target) lo = mid + 1; else hi = mid;
    }
    return lo;
  };
  return [find(now - span), Math.min(run.n - 1, find(now + span))];
}

function drawTrackTo(geometry, source, from, i, tipWorld, reference) {
  const attribute = geometry.attributes && geometry.attributes.position;
  if (!attribute || !source) {
    // No buffer to write into: still advance the drawn span, so the length of
    // the track stays correct even where the vertices cannot be touched.
    geometry.setDrawRange(from, Math.max(0, i - from + 1));
    return;
  }
  const array = attribute.array;

  const borrowed = geometry.userData.borrowed;
  if (borrowed !== undefined && borrowed !== null) {
    const b = borrowed * 3;
    array[b] = source[b] - reference.x;
    array[b + 1] = source[b + 1] - reference.y;
    array[b + 2] = source[b + 2] - reference.z;
  }

  const last = source.length / 3 - 1;
  /* Borrow the next slot only when the clock is actually between samples. On a
   * sample the tip coincides with the vertex already there, and writing it into
   * the next slot leaves a zero-length segment -- invisible, but a degenerate
   * the geometry should not carry, and enough to make any direction taken from
   * it undefined. */
  const onSample = Math.abs(tipWorld.x - (source[i * 3] - reference.x)) < 1e-9
                && Math.abs(tipWorld.y - (source[i * 3 + 1] - reference.y)) < 1e-9
                && Math.abs(tipWorld.z - (source[i * 3 + 2] - reference.z)) < 1e-9;
  const tipIndex = onSample ? i : Math.min(i + 1, last);
  const t = tipIndex * 3;
  array[t] = tipWorld.x - reference.x;
  array[t + 1] = tipWorld.y - reference.y;
  array[t + 2] = tipWorld.z - reference.z;
  geometry.userData.borrowed = tipIndex > i ? tipIndex : null;

  attribute.needsUpdate = true;
  const start = Math.min(from, tipIndex);
  geometry.setDrawRange(start, tipIndex - start + 1);
}

function orient(object, run, i, quatOff) {
  readQuaternion(run, i, quatOff, object.quaternion);
}

function updateRunGeometry(run, i) {
  updateEarth(run, i);
  if (!run || !mChaser) return;
  const at = vehiclePositions(run, i);

  /* Keep the path vertices referenced near whatever the view is looking at. */
  const anchorForPaths = (S.view === 'plane_chaser' || S.view === 'local_chaser')
    ? at.chaser : at.target;
  refreshPaths(anchorForPaths,
               kmPerPixel(activeCamera.position.distanceTo(anchorForPaths))
               * viewportHeight());

  mChaser.position.copy(at.chaser);
  mTarget.position.copy(at.target);
  orient(mChaser, run, i, OFF.chaser_quat);
  orient(mTarget, run, i, OFF.target_quat);

  /* Which tracks belong in which view. The relative views show the target's
   * orbit for orientation and drop the chaser's, whose absolute track says
   * nothing in a frame that is entirely about relative motion. */
  const relView = S.view === 'rel_target' || S.view === 'rel_chaser';
  if (orbitLines.chaser) {
    orbitLines.chaser.visible = !relView;
    orbitLines.traversed.visible = !relView;
    orbitLines.target.visible = true;
  }

  if (relLvlhFull) {
    relLvlhGroup.visible = relView;
    if (relView) {
      relLvlhGroup.position.copy(at.target);
      readQuaternion(run, i, OFF.target_quat, relLvlhGroup.quaternion);

      /* Burns later than now stay hidden, as in the plane view: showing a
       * manoeuvre before it happens gives away the answer. */
      for (const { arrow, burn } of relBurnArrows) {
        const shown = burnMarkerVisible(run, i, burn);
        arrow.visible = shown;
        if (arrow.userData.label) arrow.userData.label.visible = shown;
      }
      /* Same treatment in the target's frame: the tip is the interpolated
       * relative position, in the local axis order the samples use. */
      const a = i * run.stride + OFF.rel_lvlh;
      const nextRel = Math.min(i + 1, run.n - 1) * run.stride + OFF.rel_lvlh;
      const f = interpFraction();
      const mix = k => (run.flat[a + k]
                        + (run.flat[nextRel + k] - run.flat[a + k]) * f) * M_TO_KM;
      _relTip.set(mix(1), mix(2), mix(0));
      // The relative track is not an orbit and is not windowed: its whole
      // shape is the point of the view it appears in.
      drawTrackTo(relLvlhTraversed.geometry, relLvlhSource, 0, i, _relTip, _origin);
      if (relLvlhEstimate) {
        relLvlhEstimate.visible = S.showNavTrack;
        relLvlhEstimate.geometry.setDrawRange(0, i + 1);
      }
    }
  }

  /* In the sat-to-sat views the camera sits *at* one satellite, so drawing that
   * vehicle puts the near clip plane inside its own bus -- at best a flicker of
   * back faces filling the screen. Hide whichever one we are looking out of. */
  mChaser.visible = S.view !== 'c2t';
  mTarget.visible = S.view !== 't2c';

  if (mChaser.visible) applyLod(mChaser);
  if (mTarget.visible) applyLod(mTarget);
  /* Which sub-sample the clock has reached: the drawn path has
   * PATH_SUBDIVISIONS vertices per interval, so the traversed portion has to
   * count in those, not in samples. */
  const fineIndex = Math.min(
    Math.round((i + interpFraction()) * PATH_SUBDIVISIONS),
    (run.n - 1) * PATH_SUBDIVISIONS);

  /* The orbits are propagated from the present state, so `orbitWindow`
   * revolutions exist either side of the vehicle wherever it is in the run --
   * including the first sample, where the recording has no past. */
  for (const [line, position, velOffset] of
       [[orbitLines.chaser, at.chaser, OFF.chaser_vel],
        [orbitLines.target, at.target, OFF.target_vel]]) {
    if (!line || !line.geometry || !line.geometry.attributes) continue;
    readVec3Interp(run, i, velOffset, _orbitVel).multiplyScalar(M_TO_KM);
    const attribute = line.geometry.attributes.position;
    const drawn = sampleOrbit(position, _orbitVel, S.orbitWindow || 0.5,
                              ORBIT_POINTS, pathReference, attribute.array);
    attribute.needsUpdate = true;
    line.geometry.setDrawRange(0, drawn);
  }

  // The recorded track keeps its own window: it is history, and history has
  // ends.
  const [firstSample] = orbitWindowSamples(run, i);
  const firstVertex = firstSample * PATH_SUBDIVISIONS;
  drawTrackTo(gTraversed, fineChaser, firstVertex, fineIndex, at.chaser, pathReference);
  updateVectors(run, i);
  updatePlaneFurniture(run, i);
}

/* Viewport height in pixels, needed by the level-of-detail switch. Cached
 * rather than read per frame, and floored so a zero-height canvas (jsdom, or a
 * hidden tab) cannot divide by zero. */
/* In cinematic mode each pane is a quadrant, so anything sized against the
 * viewport -- arrow lengths, the level-of-detail switch -- has to measure the
 * pane, not the window. The aspect is unchanged, since a quadrant halves both
 * dimensions. */
const paneScale = () => (S.cinematic ? 0.5 : 1);

let _viewportHeight = 800;
let _viewportAspect = 16 / 9;
const viewportHeight = () => _viewportHeight * paneScale();
const viewportAspect = () => _viewportAspect;

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  _viewportHeight = h;
  _viewportAspect = w / h;
  renderer.setSize(w, h, false);
  camera.aspect = _viewportAspect;
  camera.updateProjectionMatrix();
}
addEventListener('resize', resize);


/* The three panes, as fractions of the canvas: top-left, top-right,
 * bottom-left. The fourth quadrant is left to the stats card. */
const PANE_RECTS = [[0, 0.5], [0.5, 0.5], [0, 0]];

/* Draw the scene once per pane, each with its own view and camera.
 *
 * Geometry is view-dependent -- which tracks show, where the vectors are
 * anchored, which vehicle the corridor follows -- so `S.view` is set and the
 * geometry rebuilt before each pass rather than once for the whole frame.
 *
 * The panes are deliberately not steerable: this mode exists to be recorded,
 * and three independently draggable cameras would be three things to get wrong
 * in a single take. Each sits at its view's home orientation.
 */
function renderCinematic(run, i) {
  const ratio = window.devicePixelRatio || 1;
  const width = renderer.domElement.width / ratio;
  const height = renderer.domElement.height / ratio;
  const halfW = width / 2, halfH = height / 2;
  const saved = S.view;

  /* Each pass clears only its own scissor rectangle. With autoClear left on,
   * the second pane would wipe the first. */
  renderer.autoClear = false;
  renderer.setScissorTest(true);
  stashActivePaneCam();          // once, before the loop borrows CAM
  for (let pane = 0; pane < 3; pane++) {
    const [fx, fy] = PANE_RECTS[pane];
    S.view = S.panes[pane] || saved;
    // Each pane keeps its own camera, so it holds whatever the user dragged it
    // to. Recentring here every frame -- as this did -- made the panes
    // unsteerable by design rather than by choice.
    usePaneCam(pane);
    applyCamera(run, i);
    updateRunGeometry(run, i);

    renderer.setViewport(fx * width, fy * height, halfW, halfH);
    renderer.setScissor(fx * width, fy * height, halfW, halfH);
    renderer.clear();
    renderer.render(scene, activeCamera);
  }
  renderer.setScissorTest(false);
  renderer.setViewport(0, 0, width, height);
  renderer.autoClear = true;
  restoreActivePaneCam();
  S.view = saved;
}
