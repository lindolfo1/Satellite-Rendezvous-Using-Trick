/* 05_cubesat.js — the satellite mesh, at true 1 m scale.
 *
 * Scene units are kilometres, so a 1 m bus is 0.001 units across. The geometry
 * below is written in **metres** and the group is scaled once on the way out,
 * because dimensions like `0.0007` are unreadable and easy to fat-finger.
 *
 * Unlit and flat throughout: no lights exist in this scene (spec 5), so
 * MeshBasicMaterial is the only material that shows anything. Edge lines carry
 * the shape reading, exactly as the old raylib viewer did.
 *
 * Body axes, from spec 3.4: +X along-track, +Y orbit normal, +Z zenith. The
 * wings extend along ±Y so they never occlude the along-track sight line, which
 * is the direction the rangefinder looks down.
 */

const M_TO_KM = 1e-3;

const BUS_M = 1.0;          // 1 x 1 x 1 m
const WING_SPAN_M = 1.4;    // each wing, root to tip
const WING_CHORD_M = 0.6;
const WING_THICK_M = 0.02;
const WING_GAP_M = 0.05;    // short boom between bus face and wing root

/* Real scale is the point, so the mesh is only drawn when it would cover at
 * least this many pixels. Below that it is sub-pixel and the marker stands in.
 */
const MESH_MIN_PIXELS = 1.0;
const MARKER_PIXELS = 8.0;
const MARKER_MAX_PIXELS = 10.0;

/* `ghost` builds the same vehicle as a dashed skeleton: no solid faces, every
 * edge dashed. It is how the navigation estimate is drawn -- an outline where
 * the chaser *believes* it is, against the solid vehicle where it actually is.
 * Solid means measured, dashed means believed, the same distinction the
 * transported LVLH frame uses. */
function buildCubesat(colour, ghost = false) {
  const edgeMaterial = () => ghost
    ? new THREE.LineDashedMaterial({ color: colour, dashSize: 0.16, gapSize: 0.12 })
    : new THREE.LineBasicMaterial({ color: colour });
  const addEdges = (parent, geometry, offsetY = 0) => {
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry),
                                         edgeMaterial());
    if (ghost) edges.computeLineDistances();
    edges.position.y = offsetY;
    parent.add(edges);
    return edges;
  };

  const group = new THREE.Group();
  const parts = new THREE.Group();   // built in metres
  group.add(parts);

  const bus = new THREE.Mesh(
    new THREE.BoxGeometry(BUS_M, BUS_M, BUS_M),
    new THREE.MeshBasicMaterial({ color: 0x1d2733 })
  );
  if (!ghost) parts.add(bus);
  addEdges(parts, bus.geometry);

  // A short mark on the +X face, so the along-track direction is readable and
  // the vehicle's attitude is not a guess.
  const nose = addEdges(parts,
    new THREE.BoxGeometry(BUS_M * 0.25, BUS_M * 0.25, BUS_M * 0.25));
  nose.position.x = BUS_M * 0.62;

  for (const side of [-1, 1]) {
    const wing = new THREE.Mesh(
      new THREE.BoxGeometry(WING_CHORD_M, WING_SPAN_M, WING_THICK_M),
      new THREE.MeshBasicMaterial({ color: 0x16324a })
    );
    wing.position.y = side * (BUS_M / 2 + WING_GAP_M + WING_SPAN_M / 2);
    if (!ghost) parts.add(wing);
    addEdges(parts, wing.geometry, wing.position.y);

    const boom = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, side * BUS_M / 2, 0),
        new THREE.Vector3(0, side * (BUS_M / 2 + WING_GAP_M), 0),
      ]),
      new THREE.LineBasicMaterial({ color: 0x4a7fa5 })
    );
    parts.add(boom);
  }

  parts.scale.setScalar(M_TO_KM);

  /* Stand-in for when the real mesh would be sub-pixel. A unit cube, rescaled
   * every frame to hold a constant on-screen size -- it is a symbol at that
   * point, not a depiction, so it must not shrink away to nothing. */
  const marker = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), edgeMaterial()
  );
  if (ghost) marker.computeLineDistances();
  group.add(marker);

  group.userData = { parts, marker };
  return group;
}

/* Kilometres per screen pixel at `distKm`, for whichever camera is active.
 * Under an orthographic projection the distance is irrelevant -- scale comes
 * from the frustum -- which is exactly why the plane view can zoom without the
 * satellites growing. */
function kmPerPixel(distKm) {
  const height = viewportHeight();
  if (activeCamera.isOrthographicCamera) {
    return (activeCamera.top - activeCamera.bottom) / height;
  }
  const halfFov = (activeCamera.fov * Math.PI) / 360;
  return (2 * distKm * Math.tan(halfFov)) / height;
}

/* Switch between the true-scale mesh and the marker, and keep the marker at a
 * fixed pixel size. Called per frame, per vehicle. */
function applyLod(group) {
  const { parts, marker } = group.userData;
  const dist = activeCamera.position.distanceTo(group.position);
  const perPixel = kmPerPixel(dist);
  const meshPixels = (BUS_M * M_TO_KM) / perPixel;

  if (meshPixels >= MESH_MIN_PIXELS) {
    parts.visible = true;
    marker.visible = false;
  } else {
    parts.visible = false;
    marker.visible = true;
    const px = Math.min(MARKER_PIXELS, MARKER_MAX_PIXELS);
    marker.scale.setScalar(px * perPixel);
  }
  return meshPixels;
}
