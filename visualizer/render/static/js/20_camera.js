/* 20_camera.js — per-view cameras and the constraint locks of spec 9.
 *
 * Each view anchors somewhere different: the plane views sit off the orbit
 * normal looking at Earth, the local views sit 25 m off a satellite looking
 * back down it, and the sat-to-sat views sit *at* one satellite aimed at the
 * other. So the camera is derived from the view and the current sample every
 * frame, with the user's freedoms applied on top — and only the freedoms that
 * view's policy grants.
 *
 * Stage 0 established that Plotly could not enforce these constraints:
 * scene.dragmode governs the left mouse button only, and right-drag pan is
 * hardwired. Owning the input handling is what makes acceptance criterion 7
 * exact — a blocked gesture is blocked because the branch that would move the
 * camera is not taken.
 */

const POLICY = {
  pan_zoom:    { rotate: false, pan: true,  zoom: true },   // 9a orbit plane
  rotate_zoom: { rotate: true,  pan: false, zoom: true },   // 9b local
  free:        { rotate: true,  pan: true,  zoom: true },   // relative-motion
};

/* Drag convention: dragging right pushes the scene right. Named rather than
 * left as a bare sign, because a flipped axis is invisible in review and
 * obvious in one second of use. */
//: Scene units of pan per pixel of drag, before zoom scaling.
const PAN_SENSITIVITY = 0.004;

const ROTATE_SENSITIVITY = 0.006;
const AZ_SIGN = +1;
const EL_SIGN = +1;
const EL_LIMIT = 1.45;

const LOCAL_STANDOFF_KM = 0.05;    // 50 m behind the anchored vehicle

//: How far the camera is lifted off the sight line, as a fraction of the
//: standoff. Without it the anchored vehicle sits exactly on top of the other
//: one and hides it; this is the "tilt".
const LOCAL_TILT_FRACTION = 0.32;

//: Default standoff for the relative-motion view, in multiples of the widest
//: separation in the run, so the whole track is in frame on arrival.
const REL_FRAME_FACTOR = 1.4;
//: Half-height of the orthographic frustum, in orbit radii. 1.35 leaves the
//: orbit comfortably inside the frame with room for the corridor circles.
const PLANE_FRAME_FACTOR = 1.35;

/* Zoom bounds per policy, not one global pair. The local view's standoff is
 * 25 m, so a shared lower bound that suits the plane view stops you pulling
 * back further than half a kilometre -- close enough to feel like a wall. The
 * bounds exist only to keep the camera out of degenerate arithmetic. */
const ZOOM_LIMITS = {
  pan_zoom:    [0.01, 2000],
  rotate_zoom: [1e-6, 5000],   // 50 m in, 50 000 km out
  free:        [1e-4, 5000],
};

/* Keyboard rates, per second. The mouse is fiddly for small adjustments and
 * impossible for a repeatable one, so every freedom has a key. */
const KEY_ROTATE_RATE = 1.3;   // rad/s
const KEY_PAN_RATE = 0.55;     // fraction of the view per second
const KEY_ZOOM_RATE = 2.6;     // multiplicative per second
const KEY_FAST = 3.0;          // shift multiplier

/* User freedoms, reset per view by recentre(). Kept separate from the derived
 * camera so switching views never inherits another view's offsets. */
const CAM = { az: 0, el: 0, panU: 0, panV: 0, zoom: 1 };

/* Where each view starts. Most open square-on to their home axis; the
 * relative-motion view opens at 45 degrees in both, so all three of R, V and H
 * are visible at once instead of the H axis pointing straight at the camera. */
const VIEW_HOME_ORIENTATION = {
  rel_target: { az: Math.PI / 4, el: Math.PI / 4 },
  rel_chaser: { az: Math.PI / 4, el: Math.PI / 4 },
};

/* Mutated in place rather than reassigned, so anything holding a reference --
 * a test, a future HUD readout -- keeps seeing the live values. */
/* One camera per cinematic pane.
 *
 * `CAM` stays the single live camera the rest of the module reads and writes;
 * these are its saved states. Entering a pane loads its state, leaving saves it
 * back, so dragging in one quadrant does not move the other two. Rendering does
 * the same swap per pass.
 *
 * The alternative -- three CAM objects threaded through every camera function --
 * would touch every view and every input handler to serve one mode.
 */
const paneCams = [0, 1, 2].map(() => ({ az: 0, el: 0, panU: 0, panV: 0, zoom: 1 }));
let activePane = 0;

function homeFor(view) {
  const home = VIEW_HOME_ORIENTATION[view] || {};
  return { az: home.az || 0, el: home.el || 0, panU: 0, panV: 0, zoom: 1 };
}

function resetPaneCam(pane) {
  Object.assign(paneCams[pane], homeFor(S.panes[pane]));
}

/** Which pane a client-space point falls in, or -1 for the stats quadrant. */
function paneAtPoint(x, y) {
  const rect = canvas.getBoundingClientRect();
  // Fall back to the window when the canvas reports no size, which is what a
  // headless DOM does and what a canvas does before its first layout.
  const width = rect.width || window.innerWidth;
  const height = rect.height || window.innerHeight;
  const left = (x - rect.left) < width / 2;
  const top = (y - rect.top) < height / 2;
  if (top) return left ? 0 : 1;
  return left ? 2 : -1;
}

/** Make `pane` the one CAM refers to, saving whatever it referred to before. */
function focusPane(pane) {
  if (pane < 0 || pane === activePane) return;
  Object.assign(paneCams[activePane], CAM);
  activePane = pane;
  Object.assign(CAM, paneCams[pane]);
}

function recentre() {
  // In cinematic mode this recentres the pane under the cursor, not all three.
  const view = S.cinematic ? S.panes[activePane] : S.view;
  Object.assign(CAM, homeFor(view));
  if (S.cinematic) Object.assign(paneCams[activePane], CAM);
}

/** Load a pane's saved camera, render-side. Pure load: the caller saves the
 * live camera once before the pass, because saving inside the loop writes each
 * pane's state into the *next* pane's slot. */
function usePaneCam(pane) {
  Object.assign(CAM, paneCams[pane]);
}

/** Save the live camera into the pane the user is driving. */
function stashActivePaneCam() {
  Object.assign(paneCams[activePane], CAM);
}

/** Put CAM back on the pane the user is driving. */
function restoreActivePaneCam() {
  Object.assign(CAM, paneCams[activePane]);
}

/* An up vector guaranteed not to be parallel to the view direction.
 *
 * Returning a fixed axis works until the camera is tilted onto it: at the
 * 83 degree elevation limit the preferred up sits 7 degrees off the view
 * direction, where `lookAt` produces a degenerate basis and the image rolls or
 * collapses. Projecting out the component along the view fixes it everywhere,
 * and at low elevation changes nothing. */
function stableUp(preferred, viewDirection, fallback) {
  const up = preferred.clone()
    .addScaledVector(viewDirection, -preferred.dot(viewDirection));
  if (up.lengthSq() > 1e-8) return up.normalize();
  return fallback.clone()
    .addScaledVector(viewDirection, -fallback.dot(viewDirection))
    .normalize();
}

function clampZoom(value) {
  const [lo, hi] = ZOOM_LIMITS[viewDef(S.view)[3]];
  return Math.max(lo, Math.min(hi, value));
}

/* Defensive: an id that is not in the view table would otherwise throw inside
 * the input handlers, on every mouse move, with the scene already drawn. */
function policy() {
  const view = viewDef(S.cinematic ? S.panes[activePane] : S.view);
  return (view && POLICY[view[3]]) || POLICY.rotate_zoom;
}

const _q = new THREE.Quaternion();

/* Clip planes from the working distance rather than fixed multiples of the
 * Earth's radius. Fixed planes clip the moment the zoom range widens, and the
 * log depth buffer copes with the span this opens up. */
function clipPlanes(dist) {
  return {
    near: Math.max(1e-6, dist * 1e-5),
    far: Math.max(dist * 60, EARTH_R_KM * 12),
  };
}

function readVec3(run, i, offset) {
  const b = i * run.stride + offset;
  return new THREE.Vector3(run.flat[b], run.flat[b + 1], run.flat[b + 2]);
}

/* Body axes from the packed quaternion. The triad is authoritative in
 * core/frames.py; this only turns it back into three vectors for aiming. */
/* Body axes for the camera, through the shared `readQuaternion` in
 * 07_arrows.js so they are interpolated between samples like everything else.
 *
 * This used to read the packed quaternion directly, a second copy of four lines
 * that looked harmless. When interpolation was added to the other copy, the
 * camera kept stepping on sample boundaries -- the plane view aims down these
 * axes, so the entire frame snapped 0.063 deg once a second while the scene
 * slid smoothly. Two implementations of one thing, drifting apart. */
function bodyAxes(run, i, offset) {
  readQuaternion(run, i, offset, _q);
  return {
    ex: new THREE.Vector3(1, 0, 0).applyQuaternion(_q),  // along-track
    ey: new THREE.Vector3(0, 1, 0).applyQuaternion(_q),  // orbit normal
    ez: new THREE.Vector3(0, 0, 1).applyQuaternion(_q),  // zenith
  };
}

const isTargetView = () => S.view === 'plane_target' || S.view === 'local_target'
                        || S.view === 'rel_target';

/* The camera for the current view and sample: {eye, look, up, fov, near, far}.
 * Pure — it reads state and returns a description, it does not move anything. */
function cameraForView(run, i) {
  if (!run) {
    return { eye: new THREE.Vector3(1, 0.6, 1).multiplyScalar(EARTH_R_KM * 3),
             look: new THREE.Vector3(), up: new THREE.Vector3(0, 0, 1),
             fov: 50, near: 10, far: 4e6 };
  }

  /* Positions come from the same helper the scene uses, so the camera and the
   * geometry cannot disagree. Reading the target's own packed absolute position
   * here would put the camera up to half a metre off the vehicle it is supposed
   * to be sitting on, which at a 1 m separation is most of the picture. */
  const at = vehiclePositions(run, i);
  const selfQuat = isTargetView() ? OFF.target_quat : OFF.chaser_quat;
  const pos = (isTargetView() ? at.target : at.chaser).clone();
  const other = (isTargetView() ? at.chaser : at.target).clone();
  const { ex, ey, ez } = bodyAxes(run, i, selfQuat);
  const zoom = CAM.zoom;

  if (S.view.startsWith('plane')) {
    // 9a: Earth-centred, viewed down the orbit normal so the plane fills the
    // screen. The normal is ey of the selected satellite, recomputed each
    // frame, so the projection tracks the plane through a plane-changing burn.
    const radius = pos.length();
    const look = new THREE.Vector3()
      .addScaledVector(ez, CAM.panU * radius)
      .addScaledVector(new THREE.Vector3().crossVectors(ey, ez), CAM.panV * radius);
    // Stand well back and project orthographically; the standoff only has to
    // clear the scene, since it no longer affects the framing.
    return {
      ortho: true,
      halfHeight: radius * PLANE_FRAME_FACTOR / zoom,
      eye: look.clone().addScaledVector(ey, radius * 8),
      look, up: ez.clone(),
      near: 1, far: radius * 20,
    };
  }

  if (S.view.startsWith('local')) {
    /* Over the shoulder: 50 m *behind* the anchored vehicle along the line to
     * the other one, lifted off that line so the near vehicle does not hide the
     * far one. Both are then in frame whenever the Earth is not between them --
     * which is what the LOS flag reports.
     *
     * The old view looked nadir from a fixed +ez standoff, which put the other
     * vehicle somewhere off-screen for most of the approach. */
    const toOther = other.clone().sub(pos);
    const sight = toOther.lengthSq() > 0 ? toOther.normalize() : ex.clone();

    // Lift direction: radial, with any component along the sight line removed.
    let lift = ez.clone().addScaledVector(sight, -ez.dot(sight));
    if (lift.lengthSq() < 1e-12) lift = ey.clone();
    lift.normalize();

    // Default eye direction from the vehicle, then the user's az/el on top.
    const home = sight.clone().multiplyScalar(-1)
      .addScaledVector(lift, LOCAL_TILT_FRACTION).normalize();
    const right = new THREE.Vector3().crossVectors(home, lift).normalize();
    const upward = new THREE.Vector3().crossVectors(right, home).normalize();
    const dir = new THREE.Vector3()
      .addScaledVector(home, Math.cos(CAM.el) * Math.cos(CAM.az))
      .addScaledVector(right, Math.cos(CAM.el) * Math.sin(CAM.az))
      .addScaledVector(upward, Math.sin(CAM.el))
      .normalize();

    const dist = LOCAL_STANDOFF_KM / zoom;
    return {
      eye: pos.clone().addScaledVector(dir, dist),
      look: pos.clone(), up: stableUp(upward, dir, right), fov: 50,
      ...clipPlanes(dist),
    };
  }

  if (S.view === 'rel_target' || S.view === 'rel_chaser') {
    /* The relative-motion view: the chaser's track in the target's rotating
     * frame, which is the shape a rangefinder plot has. Opened at 45 degrees in
     * azimuth and elevation, so R, V and H are all foreshortened rather than
     * one of them pointing at the camera. Every freedom is allowed; `recentre`
     * returns to this orientation, not to zero.
     *
     * Two framings of the same track. Centred on the **target**, the chaser
     * runs in along the plot and the frame holds still. Centred on the
     * **chaser**, the camera rides the estimate and the target closes in --
     * which is what the approach looks like from the vehicle flying it. The
     * axes stay the target's either way: it is the target's frame that the
     * track is drawn in, and re-plotting it in the chaser's would be a
     * different quantity, not a different view.
     */
    const axes = lvlhAxes(run, i, OFF.target_quat);   // radial, along-track, normal
    const span = ((META.arrow_max && META.arrow_max.range) || 1000) * 1e-3;
    const dist = span * REL_FRAME_FACTOR / zoom;

    // `pos` is already the anchored vehicle -- the target for rel_target, the
    // chaser for rel_chaser -- via isTargetView.
    const look = pos.clone()
      .addScaledVector(axes[0], CAM.panU * span)
      .addScaledVector(axes[1], CAM.panV * span);

    const home = axes[2];                              // orbit normal
    const right = axes[1];                             // along-track
    const upward = axes[0];                            // radial: R-bar up
    const dir = new THREE.Vector3()
      .addScaledVector(home, Math.cos(CAM.el) * Math.cos(CAM.az))
      .addScaledVector(right, Math.cos(CAM.el) * Math.sin(CAM.az))
      .addScaledVector(upward, Math.sin(CAM.el))
      .normalize();

    return {
      eye: look.clone().addScaledVector(dir, dist),
      look, up: stableUp(upward, dir, right), fov: 50,
      ...clipPlanes(dist),
    };
  }

  /* Unreachable: every id in the view table is handled above. Kept as a loud
   * fallback so a view added without a camera shows the vehicle rather than
   * throwing mid-frame. */
  return {
    eye: pos.clone().addScaledVector(ez, 0.05), look: pos.clone(),
    up: ex.clone(), fov: 50, ...clipPlanes(0.05),
  };
}

function applyCamera(run, i) {
  const c = cameraForView(run, i);
  const cam = c.ortho ? orthoCamera : camera;

  cam.up.copy(c.up);
  cam.position.copy(c.eye);
  cam.lookAt(c.look);

  if (c.ortho) {
    const halfWidth = c.halfHeight * viewportAspect();
    cam.left = -halfWidth; cam.right = halfWidth;
    cam.top = c.halfHeight; cam.bottom = -c.halfHeight;
    cam.near = c.near; cam.far = c.far;
    cam.updateProjectionMatrix();
  } else if (cam.fov !== c.fov || cam.near !== c.near || cam.far !== c.far) {
    cam.fov = c.fov; cam.near = c.near; cam.far = c.far;
    cam.updateProjectionMatrix();
  }
  activeCamera = cam;
}

// ---- input --------------------------------------------------------------
let drag = null;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('mousedown', e => {
  // The pane you press in is the pane you are driving, and stays so until you
  // press in another. Following the cursor instead would hand the drag to a
  // neighbour the moment it crossed the divider.
  if (S.cinematic) focusPane(paneAtPoint(e.clientX, e.clientY));
  drag = { b: e.button, x: e.clientX, y: e.clientY };
});
addEventListener('mouseup', () => { drag = null; });
addEventListener('mousemove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  const p = policy();
  if (drag.b === 0 && p.rotate) {
    CAM.az += AZ_SIGN * dx * ROTATE_SENSITIVITY;
    CAM.el = Math.max(-EL_LIMIT, Math.min(EL_LIMIT, CAM.el + EL_SIGN * dy * ROTATE_SENSITIVITY));
  } else if (drag.b === 2 && p.pan) {
    /* Drag-to-grab: the scene follows the cursor, so dragging right moves the
     * scene right, which means moving the *look point* left. `panU` is the up
     * axis and `panV` the right axis of the view, so both take the drag
     * directly. Negating them, as this did, made the scene run away from the
     * cursor. */
    CAM.panU += dy * PAN_SENSITIVITY / CAM.zoom;
    CAM.panV += dx * PAN_SENSITIVITY / CAM.zoom;
  }
});
canvas.addEventListener('wheel', e => {
  if (S.cinematic) focusPane(paneAtPoint(e.clientX, e.clientY));
  e.preventDefault();
  if (!policy().zoom) return;
  CAM.zoom = clampZoom(CAM.zoom * (1 - Math.sign(e.deltaY) * 0.1));
}, { passive: false });

// ---- keyboard -----------------------------------------------------------
/* Held keys are applied per frame and scaled by the frame time, rather than
 * acted on in keydown. Key auto-repeat is coarse and machine-dependent; this
 * moves at the same rate on every machine and stays smooth. */
const held = new Set();

/* Never steal keys from a focused control -- the scrubber is an <input>, and
 * arrow keys belong to it while it has focus. */
function typingTarget() {
  const el = document.activeElement;
  return !!el && ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName);
}

addEventListener('keydown', e => {
  if (typingTarget()) return;
  if (e.code === 'KeyR') recentre();
  held.add(e.code);
});
addEventListener('keyup', e => held.delete(e.code));
addEventListener('blur', () => held.clear());

function applyKeyboard(dt) {
  if (!held.size || typingTarget()) return;
  const p = policy();
  const fast = (held.has('ShiftLeft') || held.has('ShiftRight')) ? KEY_FAST : 1;
  const step = dt * fast;
  const down = code => held.has(code);

  if (p.rotate) {
    const rate = KEY_ROTATE_RATE * step;
    if (down('KeyA')) CAM.az -= rate;
    if (down('KeyD')) CAM.az += rate;
    if (down('KeyW')) CAM.el = Math.min(EL_LIMIT, CAM.el + rate);
    if (down('KeyS')) CAM.el = Math.max(-EL_LIMIT, CAM.el - rate);
  }
  if (p.pan) {
    const rate = KEY_PAN_RATE * step / CAM.zoom;
    if (down('KeyW')) CAM.panU += rate;
    if (down('KeyS')) CAM.panU -= rate;
    if (down('KeyA')) CAM.panV += rate;
    if (down('KeyD')) CAM.panV -= rate;
  }
  if (p.zoom) {
    const factor = Math.pow(KEY_ZOOM_RATE, step);
    if (down('KeyE')) CAM.zoom = clampZoom(CAM.zoom * factor);
    if (down('KeyQ')) CAM.zoom = clampZoom(CAM.zoom / factor);
  }
}
