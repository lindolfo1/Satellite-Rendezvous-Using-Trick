/* 08_kepler.js -- the orbit a state vector is on.
 *
 * The drawn orbit was the recorded track, windowed. That works everywhere
 * except where it matters most: at the start of a run there is nothing behind
 * the vehicle, because nothing was recorded yet, and at the end nothing ahead.
 * Asking for "0.7 orbits either side" and getting an arc that stops dead at the
 * vehicle is the wrong answer to the right question.
 *
 * So the line is propagated instead of remembered: classical elements from the
 * current position and velocity, then positions sampled across the window. Two
 * bodies, no J2 -- over 0.7 of a revolution the difference is a few kilometres
 * of ground track on a line drawn at 6878 km, and the *recorded* track is still
 * drawn over it, so anything the propagation misses is visible as the gap
 * between them rather than hidden.
 */

//: Earth's gravitational parameter in scene units, km^3/s^2.
const MU_KM = 3.986004418e5;

/** Solve Kepler's equation for the eccentric anomaly. Newton, from M. */
function eccentricAnomaly(meanAnomaly, e) {
  let E = e < 0.8 ? meanAnomaly : Math.PI;
  for (let k = 0; k < 12; k++) {
    const f = E - e * Math.sin(E) - meanAnomaly;
    const df = 1 - e * Math.cos(E);
    const step = f / df;
    E -= step;
    if (Math.abs(step) < 1e-12) break;
  }
  return E;
}

/* Fill `out` with `count` positions along the orbit through (position,
 * velocity), spanning `revolutions` either side of the present. Positions are
 * written relative to `reference`, like every other path in the scene.
 */
function sampleOrbit(position, velocity, revolutions, count, reference, out) {
  const r = position.length();
  const v2 = velocity.lengthSq();
  const inverseA = 2 / r - v2 / MU_KM;
  if (!(inverseA > 0)) return 0;                 // parabolic or hyperbolic
  const a = 1 / inverseA;

  // Eccentricity vector, and the frame it defines.
  const rDotV = position.dot(velocity);
  const eVec = position.clone().multiplyScalar(v2 / MU_KM - 1 / r)
    .addScaledVector(velocity, -rDotV / MU_KM);
  const e = Math.min(eVec.length(), 0.999);

  // Perifocal basis: P toward periapsis, W along angular momentum, Q = W x P.
  const W = new THREE.Vector3().crossVectors(position, velocity).normalize();
  const P = e > 1e-9
    ? eVec.clone().normalize()
    : position.clone().normalize();              // circular: any P will do
  const Q = new THREE.Vector3().crossVectors(W, P);

  // Where we are now, as a mean anomaly.
  const cosNu = P.dot(position) / r;
  const sinNu = Q.dot(position) / r;
  const nu = Math.atan2(sinNu, cosNu);
  const E0 = Math.atan2(Math.sqrt(1 - e * e) * Math.sin(nu), e + Math.cos(nu));
  const M0 = E0 - e * Math.sin(E0);

  const span = revolutions * 2 * Math.PI;
  for (let k = 0; k < count; k++) {
    const M = M0 - span + (2 * span * k) / (count - 1);
    const E = eccentricAnomaly(M, e);
    // Perifocal coordinates, then into ECI.
    const px = a * (Math.cos(E) - e);
    const py = a * Math.sqrt(1 - e * e) * Math.sin(E);
    out[k * 3] = P.x * px + Q.x * py - reference.x;
    out[k * 3 + 1] = P.y * px + Q.y * py - reference.y;
    out[k * 3 + 2] = P.z * px + Q.z * py - reference.z;
  }
  return count;
}
