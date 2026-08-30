/******************************* TRICK HEADER ****************************
PURPOSE: (Satellite truth dynamics, sensor drive, and filter plumbing)
*************************************************************************/

#include <cmath>
#include <cstdio>
#include <eigen3/Eigen/Dense>
#include "trick/exec_proto.h"
#include "trick/integrator_c_intf.h"
#include "../include/satellite.hh"
#include "../include/misc_util.hh"
#include "../include/orbit_util.hh"

using namespace std;
using namespace Eigen;

/* true anomaly -> mean anomaly, via eccentric anomaly */
static double trueToMeanAnomaly(double trueAnom, double ecc) {
    const double E = 2.0 * atan2(sqrt(1.0 - ecc) * sin(trueAnom / 2.0),
                                 sqrt(1.0 + ecc) * cos(trueAnom / 2.0));
    return E - ecc * sin(E);
}

/* mean anomaly -> true anomaly, Newton-Raphson on Kepler's equation */
static double meanToTrueAnomaly(double M, double ecc) {
    double E = M;
    for (int i = 0; i < 20; i++) {
        const double dE = (E - ecc * sin(E) - M) / (1.0 - ecc * cos(E));
        E -= dE;
        if (fabs(dE) < 1e-12) break;
    }
    return 2.0 * atan2(sqrt(1.0 + ecc) * sin(E / 2.0),
                       sqrt(1.0 - ecc) * cos(E / 2.0));
}

Satellite::Satellite() {}

/*========================================================================
 * default_data -- runs BEFORE the input file.
 * Independent nominal values only. Anything that must stay consistent
 * with another value belongs in initialize().
 *=======================================================================*/
int Satellite::default_data() {
    sma = 500.0e3 + R_EARTH;
    ecc = 0.0;
    inc = 0.0;
    raan = 0.0;
    argp = 0.0;
    trueAnom = 0.0;
    n = calculateN(sma);

    j2Enabled = true;

    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            posHistory[i][j] = 0.0;
    posHistorySeeded = false;

    q_eci2body_truth[0] = 1.0;
    q_eci2body_truth[1] = 0.0;
    q_eci2body_truth[2] = 0.0;
    q_eci2body_truth[3] = 0.0;

    imu.default_data(j2Enabled);
    rangefinder.default_data();
    relNav.default_data();
    guidance.default_data();
    thruster.default_data();
    attSensor.default_data();
    attNav.default_data();
    targetEph.default_data();

    return 0;
}

/*========================================================================
 * initialize -- runs AFTER the input file. Derives everything that must
 * stay consistent with whatever overrides landed.
 *=======================================================================*/
int Satellite::initialize() {
    if (elementsToCartesian(sma, ecc, inc, raan, argp, trueAnom,
                            pos_eci, vel_eci) != 0) {
        fprintf(stderr, "ERROR: elementsToCartesian failed: need sma > 0 and "
                        "0 <= ecc < 1 (got sma=%.3f m, ecc=%.6f)\n", sma, ecc);
        return -1;
    }

    const double r = sqrt(pos_eci[0]*pos_eci[0]
                        + pos_eci[1]*pos_eci[1]
                        + pos_eci[2]*pos_eci[2]);
    if (r < R_EARTH) {
        fprintf(stderr, "ERROR: initial position is inside Earth "
                        "(r = %.1f km, R_EARTH = %.1f km)\n",
                        r/1000.0, R_EARTH/1000.0);
        return -1;
    }

    n = calculateN(sma);

    /* The IMU subtracts gravity to report specific force, so its gravity
       model must match derivative()'s. */
    imu.j2Enabled = j2Enabled;

    /* Seed posHistory with true previous points via backward Kepler
       propagation, so the first IMU sample has real history to
       differentiate instead of duplicate positions. */
    const double M0 = trueToMeanAnomaly(trueAnom, ecc);
    double dummyVel[3];

    const double ta1 = meanToTrueAnomaly(M0 - n * imu.dTime, ecc);
    elementsToCartesian(sma, ecc, inc, raan, argp, ta1, posHistory[1], dummyVel);

    const double ta2 = meanToTrueAnomaly(M0 - 2.0 * n * imu.dTime, ecc);
    elementsToCartesian(sma, ecc, inc, raan, argp, ta2, posHistory[2], dummyVel);

    for (int i = 0; i < 3; i++)
        posHistory[0][i] = pos_eci[i];

    /* Mirror the sensor error model so the filter can rebuild R at the current range on every update. */
    relNav.rangeSigmaBase  = rangefinder.rangeSigmaBase;
    relNav.rangeSigmaSlope = rangefinder.rangeSigmaSlope;
    relNav.angleSigma      = rangefinder.angleSigma;

    relNav.initialize();
    att_initialize();
    targetEph.initialize();
    return 0;
}

int Satellite::navigate_initialize() {
    double relPos[3], relVel[3];
    eciToLvlh(targetEph.pos_eci, targetEph.vel_eci, pos_eci, vel_eci, relPos, relVel);

    /* eciToLvlh(target, chaser) returns chaser-relative-to-target. The
       rangefinder measures the opposite sense -- chaser looking AT the
       target -- so xHat holds the negation to agree with hx(). */
    for (int i = 0; i < 3; i++) {
        relNav.xHat[i]   = -relPos[i];
        relNav.xHat[i+3] = -relVel[i];
    }
    relNav.isInitialized = true;
    return 0;
}

int Satellite::derivative() {
    const double r2 = pos_eci[0]*pos_eci[0]
                    + pos_eci[1]*pos_eci[1]
                    + pos_eci[2]*pos_eci[2];
    const double r  = sqrt(r2);
    const double r3 = r2 * r;

    const double muR = -MU_EARTH / r3;
    const double ag[3] = { muR*pos_eci[0], muR*pos_eci[1], muR*pos_eci[2] };

    /* J2. The coefficient must multiply each component, and 1/r^5 already
       supplies the normalization, so position enters directly.
       MUST stay consistent with gravityAccel() in imu.cpp. */
    double aj2[3] = {0.0, 0.0, 0.0};
    if (j2Enabled) {
        const double j2   = 1.5 * J2_EARTH * MU_EARTH * (R_EARTH*R_EARTH) / pow(r, 5);
        const double z2r2 = pos_eci[2]*pos_eci[2] / r2;
        aj2[0] = j2 * pos_eci[0] * (5.0*z2r2 - 1.0);
        aj2[1] = j2 * pos_eci[1] * (5.0*z2r2 - 1.0);
        aj2[2] = j2 * pos_eci[2] * (5.0*z2r2 - 3.0);
    }

    /* update accelerations on satellite */
    for (int i = 0; i < 3; i++) 
        acc_eci[i] = ag[i] + aj2[i] + thruster.thrustAcc_eci[i];

    return 0;
}

int Satellite::integ() {
    load_state(&pos_eci[0], &pos_eci[1], &pos_eci[2],
               &vel_eci[0], &vel_eci[1], &vel_eci[2], (double*) NULL);
    load_deriv(&vel_eci[0], &vel_eci[1], &vel_eci[2],
               &acc_eci[0], &acc_eci[1], &acc_eci[2], (double*) NULL);

    const int ipass = integrate();

    unload_state(&pos_eci[0], &pos_eci[1], &pos_eci[2],
                 &vel_eci[0], &vel_eci[1], &vel_eci[2], (double*) NULL);

    return ipass;
}

/* Truth attitude: perfect LVLH pointing, derived from the truth state.
   Drives sensor models only. */
int Satellite::update_truth_attitude() {
    Matrix3d R;
    Vector3d p(pos_eci), v(vel_eci);
    buildSatFrame(p, v, R);
    Quaterniond q(R);
    q.normalize();
    q_eci2body_truth[0] = q.w();
    q_eci2body_truth[1] = q.x();
    q_eci2body_truth[2] = q.y();
    q_eci2body_truth[3] = q.z();
    return 0;
}

int Satellite::update_pos_history() {
    /* Skip this vehicle's first call: initialize() already seeded the
       buffer, and the first scheduled call lands at t=0 before any
       integration, so shifting here would replace good history with a
       duplicate of the unmoved current position. */
    if (!posHistorySeeded) {
        posHistorySeeded = true;
        return 0;
    }
    for (int i = 2; i > 0; i--)
        for (int j = 0; j < 3; j++)
            posHistory[i][j] = posHistory[i-1][j];

    for (int i = 0; i < 3; i++)
        posHistory[0][i] = pos_eci[i];

    return 0;
}

int Satellite::track(Satellite& other) {
    return rangefinder.track(pos_eci, q_eci2body_truth, other.pos_eci);
}

int Satellite::navigate_propagate() {
    /* Feed the commanded thrust acceleration into the filter's dynamics.

       THRUST SEAM: this uses the commanded acceleration, which is truth.
       The flight-like source is imu.dVel/imu.dTime rotated body->ECI;
       swap it in once the IMU output is consumed. */
    Matrix3d CLvlhEci;
    Vector3d pt(targetEph.pos_eci), vt(targetEph.vel_eci);
    buildSatFrame(pt, vt, CLvlhEci);

    const Vector3d aEci(thruster.thrustAcc_eci);
    const Vector3d aLvlh = CLvlhEci.transpose() * aEci;

    const double a[3] = { aLvlh(0), aLvlh(1), aLvlh(2) };
    relNav.navigate_propagate(imu.dTime, n, a, thruster.isFiring);
    return 0;
}

int Satellite::navigate_update() {
    if (!relNav.isInitialized) {
        fprintf(stderr, "WARNING: navigate_update called before navigate_initialize\n");
        return -1;
    }

    double rfAttitude[3] = { rangefinder.range,
                             rangefinder.azimuth,
                             rangefinder.elevation };

    relNav.navigate_update(targetEph.pos_eci, targetEph.vel_eci, rfAttitude, attNav.qHat);

    return 0;
}


int Satellite::att_propagate() {
    attNav.propagate(imu.dTheta, imu.dTime, imu.arw, imu.rrw);
    return 0;
}


int Satellite::att_update() {
    attSensor.sample(pos_eci, vel_eci);

    if (!attSensor.isValid)
        return 0;

    if (!attNav.isInitialized)
        return attNav.initialize(imu.arw, imu.rrw, attSensor.qMeas);
    
    attNav.update(attSensor.qMeas, attSensor.Ratt);
    return 0;
}

int Satellite::att_initialize() {
    attSensor.sample(pos_eci, vel_eci);

    attNav.initialize(imu.arw, imu.rrw, attSensor.qMeas);
    return 0;
}

int Satellite::guide() {

    double posLVLH[3], velLVLH[3];
    /* xHat holds TARGET-relative-to-CHASER (the sensor line-of-sight sense). Guidance waypoints are {0, -range, 0} (chaser trailing the target) which is CHASER-relative-to-TARGET. Negate, or every waypoint error comes out at twice the separation and pointing the wrong way. */
    for (int i = 0;  i < 3; ++ i) {
        posLVLH[i] = -relNav.xHat[i];
        velLVLH[i] = -relNav.xHat[i+3];
    }

    double n = calculateN(sma); 
    bool isBusy = thruster.isBusy(exec_get_sim_time());
    double dVel[3] = {0.0, 0.0, 0.0};
    
    /* calculate the needed dVel (if any) */
    guidance.guide(posLVLH, velLVLH, exec_get_sim_time(), n, thruster.thrustForce / thruster.satMass, isBusy, dVel);

    /* add burn to queue */
    double dVelMag = sqrt(dVel[0]*dVel[0] + dVel[1]*dVel[1] + dVel[2]*dVel[2]);
    if (dVelMag != 0.0) {
        double dVel_eci[3] = {0.0, 0.0, 0.0};
        lvlhToEci(targetEph.pos_eci, targetEph.vel_eci, dVel, dVel_eci);
        thruster.addBurn(exec_get_sim_time(), dVel_eci);
    }

    return 0;
}

int Satellite::update_target_ephemeris(Satellite& other) {
    return targetEph.update(other.pos_eci, other.vel_eci);
}

int Satellite::thrustUpdate() {
   return thruster.update(exec_get_sim_time());
}

int Satellite::shutdown() {
    const double r = sqrt(pos_eci[0]*pos_eci[0]
                        + pos_eci[1]*pos_eci[1]
                        + pos_eci[2]*pos_eci[2]);
    printf("t = %.1f s, r = %.1f m (sma = %.1f m)\n",
           exec_get_sim_time(), r, sma);
    return 0;
}
