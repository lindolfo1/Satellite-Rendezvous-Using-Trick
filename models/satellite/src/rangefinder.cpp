#include "../include/rangefinder.hh"
#include "../include/misc_util.hh"
#include <cmath>
#include <eigen3/Eigen/Dense>
#include "trick/exec_proto.h"

using namespace Eigen;
using namespace std;

Rangefinder::Rangefinder() {}

int Rangefinder::default_data() {
    range     = 1000.0;
    azimuth   = 0.0;
    elevation = 0.0;
    timestamp = 0.0;
    isValid   = false;
    addNoise  = true;

    rangeSigmaBase  = 0.01;     /* m */
    rangeSigmaSlope = 1.0e-8;   /* ~1 m sigma at 1 km */
    angleSigma      = 8.7e-4;   /* rad, ~0.05 deg */

    return 0;
}

/*
 * Simulates a body-fixed rangefinder measuring the target relative to the
 * chaser.
 *
 *   posChaser -- chaser TRUTH position, ECI (m)
 *   qChaser   -- chaser TRUTH attitude, body->ECI, scalar-first (--)
 *   posTarget -- target TRUTH position, ECI (m)
 *
 * qChaser must be the truth attitude, never a filter estimate: real
 * hardware measures what the vehicle actually points at, and feeding an
 * estimate here cancels attitude error out of the innovation.
 */
int Rangefinder::track(const double posChaser[3], const double qChaser[4],
                       const double posTarget[3]) {
    const Vector3d posC(posChaser), posT(posTarget);
    const Vector3d r = posT - posC;

    Quaterniond qC(qChaser[0], qChaser[1], qChaser[2], qChaser[3]);
    qC.normalize();

    /* qChaser is body->ECI, so the conjugate takes ECI->body. */
    const Vector3d rBody = qC.conjugate() * r;

    double dist = rBody.norm();
    double az   = atan2(rBody[1], rBody[0]);
    double el   = atan2(rBody[2], sqrt(rBody[0]*rBody[0] + rBody[1]*rBody[1]));

    if (addNoise) {
        /* rangeSigmaBase is a noise FLOOR, so it belongs inside the sigma.
           Adding it outside would make it a fixed bias on every sample. */
        dist += generateGaussianNoise(rangeSigmaBase + dist * rangeSigmaSlope);
        az   += generateGaussianNoise(angleSigma);
        el   += generateGaussianNoise(angleSigma);
    }

    range     = dist;
    azimuth   = az;
    elevation = el;
    timestamp = exec_get_sim_time();
    isValid   = true;

    return 0;
}
