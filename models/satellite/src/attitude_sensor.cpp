#include "../include/attitude_sensor.hh"
#include "../include/misc_util.hh"
#include <cmath>
#include <eigen3/Eigen/Dense>
#include "trick/exec_proto.h"

using namespace Eigen;
using namespace std;

/*
 * Direction of a centered dipole ALIGNED with the spin axis, in ECI.
 * m points to geographic south, so mHat = -zHat and the field direction
 * 3(mHat.rHat)rHat - mHat reduces to the form below. Magnitude is not
 * modeled -- attitude uses direction only. No time argument: an untilted
 * dipole is symmetric about z, so Earth rotation leaves it unchanged.
 */
static void dipoleDir_eci(const Vector3d& pos, Vector3d& magRef) {
    const Vector3d rHat = pos.normalized();
    const double   rz   = rHat(2);

    magRef << -3.0 * rz * rHat(0), -3.0 * rz * rHat(1), 1.0 - 3.0 * rz * rz;
    magRef.normalize();
}
 
/*
 * Corrupt a unit direction: v' = normalize(v + eps x v), with eps a
 * rotation vector of per-run bias plus white noise. Rotation about v
 * itself has no effect, which is correct -- a unit vector carries only
 * 2 DOF. Unlike the IMU there is no 1/sqrt(dTime) scaling: sigma is a
 * plain angle, not a density, so the noise is rate-independent.
 */
static void simulateDirNoise(double sigma, const Vector3d& alignBias, Vector3d& v) {
    Vector3d noise;
    generateGaussianNoise3d(sigma, noise);
    const Vector3d eps = alignBias + noise;
    v = (v + eps.cross(v)).normalized();
}

AttitudeSensor::AttitudeSensor() {}

int AttitudeSensor::default_data() {
    sunSigma    = 0.1  * M_PI / 180.0;
    magSigma    = 0.5  * M_PI / 180.0;
    minGeometry = 10.0 * M_PI / 180.0;

    for (int i = 0; i < 3; i++) {
        sunAlignBias[i] = 0.0;
        magAlignBias[i] = 0.0;
    }

    qMeas[0] = 1.0;
    qMeas[1] = 0.0;
    qMeas[2] = 0.0;
    qMeas[3] = 0.0;

    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            Ratt[i][j] = 0.0;

    geometryAngle = 0.0;
    timestamp = 0.0;
    isValid = false;
    addNoise = true;

    return 0;
}

/*
 * Truth attitude is DERIVED from truth pos/vel via buildSatFrame(), the
 * same frame Satellite::update_truth_attitude() builds, so no quaternion
 * is passed in. pos_eci/vel_eci must be the TRUTH state, never a filter
 * estimate: sharing a state between sensor generation and filter
 * prediction cancels attitude error out of the innovation and makes
 * attitude unobservable by construction.
 */
int AttitudeSensor::sample(const double pos_eci[3], const double vel_eci[3]) {
    timestamp = exec_get_sim_time();
    isValid   = false;              /* set true only on a clean solve */

    const Vector3d posv(pos_eci);
    const Vector3d velv(vel_eci);

    /* SIMPLIFYING ASSUMPTION: the Sun is pinned to ECI +x. ECI x points at the vernal equinox, which is the Earth->Sun direction at the March equinox, so this freezes the sim at that instant. The real Sun moves ~0.04 deg/hr in ECI, negligible over a run of hours. */
    const Vector3d sunRef = Vector3d::UnitX();

    Vector3d magRef;
    dipoleDir_eci(posv, magRef);

    /* Geometry from the clean ECI vectors, never the measured body ones: their noise would leak into Ratt, which exists to describe that same noise. sunRef is xHat, so the dot product is just magRef(0). */
    double c = magRef(0);
    if (c >  1.0) c =  1.0;
    if (c < -1.0) c = -1.0;
    geometryAngle = acos(c);

    /* Gate on the SINE. TRIAD is singular at both 0 and pi and acos() returns [0,pi], so testing the angle alone sails past the antiparallel case. Same quantity that scales Ratt below, so the gate fires exactly when the about-sun variance blows up. This is reachable, not defensive: with the Sun on xHat, ry = 0 and rz = 1/sqrt(3) (lat 35.26 deg) makes the two lines exactly parallel, at the same two points of every orbit. */
    const double sinGeom = sin(geometryAngle);
    if (sinGeom < sin(minGeometry))
        return 0;                   /* isValid stays false */

    /* buildSatFrame sets the COLUMNS of R to the body axes in ECI, so R maps body->ECI and R^T maps ECI->body. */
    Matrix3d Rbody2eci;
    buildSatFrame(posv, velv, Rbody2eci);

    Vector3d sunBody = Rbody2eci.transpose() * sunRef;
    Vector3d magBody = Rbody2eci.transpose() * magRef;

    if (addNoise) {
        simulateDirNoise(sunSigma, Vector3d(sunAlignBias), sunBody);
        simulateDirNoise(magSigma, Vector3d(magAlignBias), magBody);
    }

    /* TRIAD, sun primary and mag secondary: the sun sensor is the more accurate of the two, so it is placed on the axis it fixes exactly. */
    Matrix3d Mb, Mr;

    Mb.col(0) = sunBody;
    Mb.col(1) = sunBody.cross(magBody).normalized();
    Mb.col(2) = Mb.col(0).cross(Mb.col(1));

    Mr.col(0) = sunRef;
    Mr.col(1) = sunRef.cross(magRef).normalized();
    Mr.col(2) = Mr.col(0).cross(Mr.col(1));

    /* Mb maps triad->body and Mr maps triad->ECI, so Mr * Mb^T is body->ECI, matching the qMeas convention. */
    Quaterniond qOut(Matrix3d(Mr * Mb.transpose()));
    qOut.normalize();
    if (qOut.w() < 0.0)
        qOut.coeffs() *= -1.0;

    qMeas[0] = qOut.w();
    qMeas[1] = qOut.x();
    qMeas[2] = qOut.y();
    qMeas[3] = qOut.z();

    /* Anisotropic by construction. Rotation perpendicular to the sun line is pinned by the sun sensor; rotation ABOUT it is invisible to the sun sensor and resolved only by the magnetometer, degraded by 1/sin geometryAngle). An isotropic sigma^2*I here would make the filter overconfident about exactly the worst axis. */
    const Matrix3d ssT = sunBody * sunBody.transpose();
    const double varPerp = sunSigma * sunSigma;
    const double sigAbout = magSigma / sinGeom;
    const Matrix3d Rm = varPerp * (Matrix3d::Identity() - ssT) + (sigAbout * sigAbout) * ssT;

    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            Ratt[i][j] = Rm(i, j);

    isValid = true;
    return 0;
}

