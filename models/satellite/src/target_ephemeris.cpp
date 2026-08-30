#include "../include/target_ephemeris.hh"
#include "../include/misc_util.hh"
#include "trick/exec_proto.h"

#include <eigen3/Eigen/Dense>

using namespace Eigen;


TargetEphemeris::TargetEphemeris() {}

int TargetEphemeris::default_data() {
    for (int i = 0; i < 3; ++ i) {
        pos_eci[i] = 0.0;
        vel_eci[i] = 0.0;
        posBias[i] = 0.0;
        velBias[i] = 0.0;
    }
    timestamp = 0.0;
    isValid = false;

    addNoise = false;
    posSigma = 50.0;
    velSigma = 0.05;

    return 0;
}


int TargetEphemeris::initialize() {
    if (addNoise) {
        Vector3d pNoise, vNoise;
        generateGaussianNoise3d(posSigma, pNoise);
        generateGaussianNoise3d(velSigma, vNoise);

        for (int i = 0; i < 3; ++ i) {
            posBias[i] = pNoise(i);
            velBias[i] = vNoise(i);
        }
    }

    return 0;
}

int TargetEphemeris::update(const double posTruth[3], const double velTruth[3]) {
    timestamp = exec_get_sim_time();

    for (int i = 0; i < 3; ++ i) {
        pos_eci[i] = posTruth[i];
        vel_eci[i] = velTruth[i];
    }

    if (addNoise) {
        for (int i = 0; i < 3; ++ i) {
            pos_eci[i] += posBias[i];
            vel_eci[i] += velBias[i];
        }
    }

    isValid = true;

    return 0;
}