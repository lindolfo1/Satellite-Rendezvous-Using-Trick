/* 07_arrows.js — vector arrows and coordinate triads.
 *
 * Arrow scaling, from spec 9b: velocity is ~7.6e3 m/s, thrust ~1e-1 m/s^2 and
 * IMU delta-V ~3e-2 m/s. Nothing sensible can put those on one scale, so the
 * default is **fixed length, direction only**, with the magnitudes read off the
 * view options panel. The second policy, "relative magnitude", scales each
 * arrow against its own peak over the run, so growth and decay are legible
 * without inviting a comparison between quantities that share no units.
 *
 * Arrows are built pointing along +Y (three.js cones point that way) and
 * rotated onto their direction, so a unit arrow is built once and reused.
 */

const AXIS_COLOURS = [0xff5252, 0x69f0ae, 0x448aff];   // x, y, z

/* Frames are the same three colours; they are told apart by length, listed in
 * the panel legend. Colouring the frames differently instead would break the
 * x-red/y-green/z-blue convention, which is the one thing a reader already
 * knows without being told. */
const TRIAD_SCALE = { eci: 1.55, lvlh: 1.15, body: 0.8 };

/* Per-vector length multipliers under the fixed policy.
 *
 * Fixed length encodes direction only, so differing lengths carry no meaning
 * and are free to serve legibility. Thrust is the shortest-lived and most
 * interesting arrow in the scene, and at parity with velocity it was easy to
 * miss; it gets the extra length. */
const ARROW_EMPHASIS = { velocity: 1.0, thrust: 1.7, imu: 1.25, rangefinder: 1.0 };

const _up = new THREE.Vector3(0, 1, 0);

function makeArrow(colour, headFraction = 0.16, label = null, dashed = false) {
  const group = new THREE.Group();
  const material = dashed
    ? new THREE.LineDashedMaterial({ color: colour, dashSize: 0.07, gapSize: 0.05 })
    : new THREE.LineBasicMaterial({ color: colour });
  const shaft = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 1 - headFraction, 0)]),
    material
  );
  if (dashed) shaft.computeLineDistances();
  const head = new THREE.Mesh(
    new THREE.ConeGeometry(headFraction * 0.38, headFraction, 12),
    new THREE.MeshBasicMaterial({ color: colour })
  );
  head.position.y = 1 - headFraction / 2;
  group.add(shaft);
  group.add(head);

  /* The label is *not* a child of the arrow. The arrow is scaled to its length
   * and a screen-space sprite inside it would be scaled with it, which is
   * precisely what sizeAttenuation is meant to prevent. The caller adds it to
   * the same parent; `aimArrow` keeps it at the tip. */
  group.userData.label = label ? makeLabel(label[0], label[1], colour) : null;
  return group;
}

/** Add an arrow and its detached label to the same parent. */
function addArrow(parent, arrow) {
  parent.add(arrow);
  if (arrow.userData.label) parent.add(arrow.userData.label);
  return arrow;
}

/* Point an arrow along `direction` from `origin`, `length` scene units long.
 * A zero-length or zero-direction arrow is hidden rather than drawn as a dot. */
const _labelTip = new THREE.Vector3();

function aimArrow(arrow, origin, direction, length) {
  const label = arrow.userData.label;
  if (!length || !isFinite(length) || direction.lengthSq() === 0) {
    arrow.visible = false;
    if (label) label.visible = false;
    return;
  }
  arrow.visible = true;
  arrow.position.copy(origin);
  arrow.quaternion.setFromUnitVectors(_up, direction.clone().normalize());
  arrow.scale.setScalar(length);
  if (label) {
    label.visible = true;
    _labelTip.copy(origin)
      .addScaledVector(direction.clone().normalize(), length * 1.06);
    label.position.copy(_labelTip);
  }
}

/* An axis label as a screen-space sprite.
 *
 * `sizeAttenuation: false` keeps it the same size however far the camera is,
 * which is what a label wants and what a 3D-scaled one cannot do across a scene
 * holding a 1 m satellite and a 6378 km Earth. Returns null where there is no
 * 2D canvas -- headless -- so the caller degrades to unlabelled axes rather
 * than failing to build a scene.
 */
function makeLabel(main, sub, colour) {
  const canvas = document.createElement('canvas');
  canvas.width = LABEL_PX_W;
  canvas.height = LABEL_PX_H;
  const ctx = canvas.getContext('2d');
  if (!ctx || typeof ctx.fillText !== 'function') return null;

  ctx.fillStyle = '#' + colour.toString(16).padStart(6, '0');
  ctx.textBaseline = 'alphabetic';
  ctx.textAlign = 'left';
  ctx.font = `bold ${MAIN_PX}px ui-monospace, "SF Mono", monospace`;
  ctx.fillText(main, 4, LABEL_PX_H * 0.62);
  if (sub) {
    const width = ctx.measureText ? ctx.measureText(main).width : MAIN_PX * main.length;
    ctx.font = `bold ${SUB_PX}px ui-monospace, "SF Mono", monospace`;
    ctx.fillText(sub, 6 + width, LABEL_PX_H * 0.86);
  }

  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(canvas),
    sizeAttenuation: false,
    depthTest: false,
    transparent: true,
  }));
  // Keep the canvas aspect, or the glyphs stretch.
  sprite.scale.set(LABEL_SCREEN_SIZE * (LABEL_PX_W / LABEL_PX_H),
                   LABEL_SCREEN_SIZE, 1);
  sprite.center.set(0.08, 0.5);
  sprite.userData.text = sub ? `${main}_${sub}` : main;
  return sprite;
}

/* Labels are drawn on a canvas and shown as screen-space sprites. The subscript
 * is a second, smaller draw rather than a separate sprite: the frames are the
 * same triad under different names, so "x" alone identifies nothing and
 * "x ECI" against "x LVLH" is the whole point of showing them together. */
const LABEL_PX_W = 192;
const LABEL_PX_H = 64;
const MAIN_PX = 42;
const SUB_PX = 24;

//: Label height as a fraction of the viewport (sizeAttenuation off).
const LABEL_SCREEN_SIZE = 0.03;

/* `frame` is the subscript: x_ECI, x_LVLH, x_IMU.
 *
 * Two of these frames are not merely similar, they are the same construction.
 * Spec 3.4 defines the chaser's sensor frame as its own LVLH triad -- radial,
 * along-track, orbit normal, built from the chaser's own state, because the
 * data carries no attitude quaternion. So the chaser's sensor axes and *any*
 * LVLH triad drawn at the chaser lie along the same three lines, and the
 * target's LVLH is parallel to the chaser's to 145 urad.
 *
 * `dashed` is for a frame transported from elsewhere: it is how the target's
 * LVLH, drawn at the chaser, says it is not the chaser's own.
 */
function makeTriad(frame, dashed = false) {
  const group = new THREE.Group();
  group.userData.frame = frame;
  group.userData.dashed = dashed;
  group.userData.axes = ['x', 'y', 'z'].map((axis, k) =>
    addArrow(group, makeArrow(AXIS_COLOURS[k], 0.2, [axis, frame], dashed)));
  return group;
}

function aimTriad(triad, origin, axes, length) {
  triad.visible = true;
  triad.userData.axes.forEach((arrow, k) => aimArrow(arrow, origin, axes[k], length));
}

/* The three body axes in world coordinates, from a packed quaternion.
 *
 * The sensor frame and LVLH use the **same** axis naming -- x radial, y
 * along-track, z orbit normal -- so the only difference between them is which
 * vehicle's state defines the triad. Azimuth is atan2(along-track, radial),
 * which is what reproduces the recorded rangefinder bearings: on real output it
 * reads 1.5694 rad where an x-along-track reading predicts 0.
 */
const _q3 = new THREE.Quaternion();

/* Read a packed quaternion, interpolated between samples like the positions.
 *
 * Skipping this was a mistake I made deliberately: the triad turns 0.063 deg
 * per second, which is invisible on a 1 m satellite. But the *camera* is built
 * from these axes -- the plane view aims down the orbit normal with radial as
 * up -- so leaving them on sample boundaries snapped the whole view 0.063 deg
 * once a second while the scene slid smoothly underneath. Small on a vehicle,
 * a visible jolt across a full frame.
 *
 * Normalised lerp rather than slerp: over 0.063 deg the two agree to about
 * 1e-9 rad, and nlerp is four multiplies and a normalise.
 */
function readQuaternion(run, i, quatOffset, target) {
  const b = i * run.stride + quatOffset;
  target.set(run.flat[b], run.flat[b + 1], run.flat[b + 2], run.flat[b + 3]);

  const f = interpFraction();
  if (f <= 0 || i >= run.n - 1) return target;

  const c = (i + 1) * run.stride + quatOffset;
  // Take the shorter arc: q and -q are the same rotation, and lerping across
  // the long way would spin the view through a half turn.
  const dot = target.x * run.flat[c] + target.y * run.flat[c + 1]
            + target.z * run.flat[c + 2] + target.w * run.flat[c + 3];
  const sign = dot < 0 ? -1 : 1;
  target.set(
    target.x + (sign * run.flat[c] - target.x) * f,
    target.y + (sign * run.flat[c + 1] - target.y) * f,
    target.z + (sign * run.flat[c + 2] - target.z) * f,
    target.w + (sign * run.flat[c + 3] - target.w) * f
  );
  return target.normalize();
}

/* Interpolated reads for **geometry** -- where something is and which way it
 * points. Measurements are deliberately left on their samples: smoothing a
 * rangefinder range or a thrust command would misrepresent the data, and a
 * commanded thrust that steps on and off is meant to step.
 *
 * Everything geometric has to be interpolated or it steps once a sample while
 * the rest of the scene slides. The waypoint balls did exactly that: their axis
 * came from the raw target velocity, so they jumped 1.3 px per sample against a
 * satellite that was moving smoothly.
 */
function readScalar(run, i, offset) {
  const here = run.flat[i * run.stride + offset];
  const f = interpFraction();
  if (f <= 0 || i >= run.n - 1) return here;
  return here + (run.flat[(i + 1) * run.stride + offset] - here) * f;
}

/** Like `readScalar`, for an angle that wraps at 2 pi. */
function readAngle(run, i, offset) {
  const here = run.flat[i * run.stride + offset];
  const f = interpFraction();
  if (f <= 0 || i >= run.n - 1) return here;
  let delta = run.flat[(i + 1) * run.stride + offset] - here;
  // Cross the wrap the short way, or the Earth spins backwards once an orbit.
  if (delta > Math.PI) delta -= 2 * Math.PI;
  else if (delta < -Math.PI) delta += 2 * Math.PI;
  return here + delta * f;
}

function readVec3Interp(run, i, offset, target) {
  const a = i * run.stride + offset;
  const f = interpFraction();
  if (f <= 0 || i >= run.n - 1) {
    return target.set(run.flat[a], run.flat[a + 1], run.flat[a + 2]);
  }
  const b = (i + 1) * run.stride + offset;
  return target.set(
    run.flat[a] + (run.flat[b] - run.flat[a]) * f,
    run.flat[a + 1] + (run.flat[b + 1] - run.flat[a + 1]) * f,
    run.flat[a + 2] + (run.flat[b + 2] - run.flat[a + 2]) * f
  );
}

function bodyAxesFromQuat(run, i, quatOffset) {
  readQuaternion(run, i, quatOffset, _q3);
  return {
    alongTrack: new THREE.Vector3(1, 0, 0).applyQuaternion(_q3),
    normal: new THREE.Vector3(0, 1, 0).applyQuaternion(_q3),
    radial: new THREE.Vector3(0, 0, 1).applyQuaternion(_q3),
  };
}

/** Sensor frame axes in (x, y, z) order: radial, along-track, orbit normal. */
function sensorFrameAxes(run, i, quatOffset) {
  const a = bodyAxesFromQuat(run, i, quatOffset);
  return [a.radial, a.alongTrack, a.normal];
}

/** LVLH axes in (x, y, z) order: radial, along-track, orbit normal. */
function lvlhAxes(run, i, quatOffset) {
  const a = bodyAxesFromQuat(run, i, quatOffset);
  return [a.radial, a.alongTrack, a.normal];
}

/** A unit vector in world coordinates from a body-frame bearing. */
function bearingToWorld(axes, azimuth, elevation) {
  const cosEl = Math.cos(elevation);
  return new THREE.Vector3()
    .addScaledVector(axes[0], cosEl * Math.cos(azimuth))
    .addScaledVector(axes[1], cosEl * Math.sin(azimuth))
    .addScaledVector(axes[2], Math.sin(elevation));
}
