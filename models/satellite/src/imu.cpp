#include "../include/satellite.hh"
#include "../include/imu.hh"
#include "../include/misc_util.hh"
#include <cmath>
#include <eigen3/Eigen/Dense>
#include "trick/exec_proto.h"

using namespace Eigen;
using namespace std;

/*
 * Gravitational acceleration at an ECI position (m/s2).
 * MUST match Satellite::derivative(). Any difference shows up in dVel as
 * a phantom thrust the filter cannot explain.
 */
static void gravityAccel(const Vector3d& pos, bool useJ2, Vector3d& ag) {
    const double r2 = pos.squaredNorm();
    const double r  = sqrt(r2);
    const double r3 = r2 * r;

    ag = -(MU_EARTH / r3) * pos;

    if (useJ2) {
        const double j2   = 1.5 * J2_EARTH * MU_EARTH * (R_EARTH*R_EARTH) / pow(r, 5);
        const double z2r2 = pos(2)*pos(2) / r2;
        ag(0) += j2 * pos(0) * (5.0*z2r2 - 1.0);
        ag(1) += j2 * pos(1) * (5.0*z2r2 - 1.0);
        ag(2) += j2 * pos(2) * (5.0*z2r2 - 3.0);
    }
}

/*
 * Angular rate from the rotation between two body frames, via the
 * skew-symmetric part of R. Returns a RATE (rad/s).
 */
static void wFromR(const Matrix3d& R, double dTime, Vector3d& w) {
    const Vector3d axis = { R(2,1) - R(1,2),
                            R(0,2) - R(2,0),
                            R(1,0) - R(0,1) };
    w = axis / (2.0 * dTime);
}

static void simulateGyroNoise(double arw, double dTime,
                              const Vector3d& gyroBias, Vector3d& w) {
    Vector3d noise;
    generateGaussianNoise3d(arw / sqrt(dTime), noise);
    w += gyroBias + noise;
}

static void simulateAccelNoise(double vrw, double dTime,
                               const Vector3d& accelBias, Vector3d& dv) {
    Vector3d noise;
    generateGaussianNoise3d(vrw / sqrt(dTime), noise);
    dv += accelBias + noise;
}

IMU::IMU() {}

int IMU::default_data(bool enableJ2) {
   dTime = 0.5;
   vrw   = 1.0e-3;
   arw   = 1.0e-4;
   rrw   = 1.0e-5;
    for (int i = 0; i < 3; i++) {
       accelBias[i] = 0.0;
       gyroBias[i]  = 0.0;
       dVel[i]      = 0.0;
       dTheta[i]    = 0.0;
    }
   timestamp = 0.0;
   isValid   = false;
   addNoise  = true;
   j2Enabled = enableJ2;

   return 0;
}

/*
 * Called with (posHistory[0], posHistory[1], posHistory[2]), so x1 is the
 * NEWEST sample and x3 the oldest.
 */
int IMU::sample_imu(double x1[3], double x2[3], double x3[3]) {
    const double now = exec_get_sim_time();
    if (now > timestamp)
        dTime = now - timestamp;
    timestamp = now;

    const Vector3d x1v(x1), x2v(x2), x3v(x3);
    const Vector3d v1 = (x2v - x1v) / dTime;
    const Vector3d v2 = (x3v - x2v) / dTime;
    Vector3d dv = v2 - v1;

    /* The centered second difference gives TOTAL acceleration * dTime
       (gravity + thrust). An accelerometer senses specific force only, so
       remove the modeled gravitational delta-velocity; a coasting vehicle
       then reads ~0. Gravity is evaluated at x2 because the second
       difference is centered on the middle sample. */
    Vector3d ag;
    gravityAccel(x2v, j2Enabled, ag);
    dv -= ag * dTime;

    Matrix3d R1, R2;
    buildSatFrame(x2v, v1, R1);
    buildSatFrame(x3v, v2, R2);
    const Matrix3d R = R1.transpose() * R2;

    Vector3d w;
    wFromR(R, dTime, w);

    if (addNoise) {
        const Vector3d gb(gyroBias);
        const Vector3d ab(accelBias);
        simulateGyroNoise(arw, dTime, gb, w);
        simulateAccelNoise(vrw, dTime, ab, dv);
    }

    /* wFromR returns a RATE, but dTheta is a delta-ANGLE and is consumed
       as one (small-angle quaternion). Multiply by dTime, or the attitude
       integrates 1/dTime times too fast. This also keeps a gyro-bias
       correction dimensionally consistent: dTheta - bias*dTime is rad. */
    for (int i = 0; i < 3; i++) {
        dTheta[i] = w(i) * dTime;
        dVel[i]   = dv(i);
    }

    isValid = true;
    return 0;
}
