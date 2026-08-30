#include "../include/guidance.hh"
#include "trick/exec_proto.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <eigen3/Eigen/Dense>
#include <iostream>
#include <numeric>

using namespace Eigen;
using namespace std;

static Vector3d calcDeltaV(Vector3d posCurr, Vector3d velCurr, Vector3d waypt, double tFinal, double n) {
    Matrix3d phiRV_inv, phiRR; // phi_rv^-1, phi_rr  <-- Matrix3d, not Matrix6d
    phiRV_inv.setZero();
    phiRR.setZero();
    double s = sin(n*tFinal);
    double c = cos(n*tFinal);
    double D = n / (8.0*(1.0-c) - 3.0*n*tFinal*s);
    phiRV_inv(0, 0) = D*(4.0*s - 3.0*n*tFinal);
    phiRV_inv(0, 1) = -2.0*D*(1.0 - c);
    phiRV_inv(1, 0) = 2.0*D*(1.0 - c);
    phiRV_inv(1, 1) = D*s;
    phiRV_inv(2, 2) = n/s;

    phiRR(0, 0) = 4.0 - 3.0*c;
    phiRR(1, 0) = 6*(s - n*tFinal);
    phiRR(1, 1) = 1.0;
    phiRR(2, 2) = c;

    Vector3d velReq = phiRV_inv * (waypt - phiRR*posCurr);
    return velReq - velCurr;
}

static void findTfCandidates(double n, vector<double>& tfCandidates) {
    constexpr double dt = 0.1;
    constexpr double tSpan = 6 * M_PI;
    tfCandidates.reserve(tfCandidates.size() + static_cast<size_t>(tSpan / dt) + 1);
    int steps = static_cast<int>(tSpan / dt);
    for (int k = 1; k <= steps; ++k) {
        double i = k * dt;
        double D = 8 * (1 - cos(i)) - 3*i*sin(i);
        if (D < -1 || D > 1)
            tfCandidates.push_back(i / n); 
            // tfCandidates.push_back(n/D);
    }
}

static void normalizeVector(vector<double>& vect) {
    double norm = sqrt(inner_product(vect.begin(), vect.end(), vect.begin(), 0.0));
    if (norm > 0)
        for (double& x : vect)
            x /= norm;
}

struct TfSolution {
    double tf;
    Vector3d dV;
};

static TfSolution findBestTf(Vector3d pos0, Vector3d vel0, Vector3d waypt, double n, double accelMag, double timeWeight) {
    vector<double> tfCandidates;
    findTfCandidates(n, tfCandidates);

    constexpr double maxBurnFraction = 0.05; // burn must take <5% of tf to be "impulsive"

    double bestCost = std::numeric_limits<double>::infinity();
    TfSolution best{-1.0, Vector3d::Zero()};

    for (const auto& tf : tfCandidates) {
        Vector3d dV = calcDeltaV(pos0, vel0, waypt, tf, n);
        double burnDuration = dV.norm() / accelMag;

        if (burnDuration > maxBurnFraction * tf)
            continue; // not impulsive enough at this thrust level -- reject

        double cost = dV.norm() + timeWeight * tf;
        if (cost < bestCost) {
            bestCost = cost;
            best = {tf, dV};
        }
    }
    cout << "best time: " << best.tf/3600 << "hrs\n";

    return best; // best.tf < 0 if nothing was feasible -- caller should handle that
}

static double calcVelTolerance(double distance, double n, double velTolFactor, double velTolFloor) {
    // velTolFactor: dimensionless scale factor (tune based on desired forgiveness)
    // velTolFloor: minimum tolerance (m/s), set based on IMU/sensor noise floor
    double velTol = velTolFactor * n * distance;
    return max(velTol, velTolFloor);
}

Guidance::Guidance() {}

int Guidance::default_data() {
   waypointRange[0] = 1000.0;
   waypointRange[1] = 250.0;
   waypointRange[2] = 50.0;
   waypointRange[3] = 20.0;
   numWaypoints     = 4;
   currentWaypoint  = 0;
   dVAccumulated    = 0.0;
   wayptTfinal      = -1.0;
   burnEndTime      = -1.0;
   retryInterval    = 60;
   tolerance        = 0.01;

   return 0;
}

int Guidance::guide(double chaserPos0[3], double chaserVel0[3], double currT, double n, double accelMag, bool isThrusterBusy, double dVel[3]) {
    /* allow kalman filter to settle */
    if (exec_get_sim_time() < 30)
        return 0;

    Vector3d pos(chaserPos0), vel(chaserVel0), waypt;
    waypt = {0.0, -waypointRange[currentWaypoint], 0.0};

    /* check whether it hit a waypoint inside the tolerance */
    double posTolerance = abs(tolerance*waypointRange[currentWaypoint]);
    double velTolerance = calcVelTolerance(pos.norm(), n, tolerance, 0.1);
    if ((pos-waypt).norm() > posTolerance || vel.norm() > velTolerance) {
        /* if still outside tolerance despite previous burn + coasting -> calculate correction burn */
        if (!isThrusterBusy && (wayptTfinal < 0.0 || currT >= wayptTfinal)) {
            TfSolution soltn = findBestTf(pos, vel, waypt, n, accelMag, 5e-5);
            if (soltn.tf < 0.0) {
                // no feasible impulsive solution; coast and retry later rather than
                // spamming, and don't push wayptTfinal into the past
                wayptTfinal = currT + retryInterval;   // e.g. 60.0 s
            } else {
                wayptTfinal = currT + soltn.tf;
                /* add delta v's to the return dVel */
                for (int i = 0; i < 3; ++ i)
                    dVel[i] = soltn.dV[i];
            }
        }
    }
    else {
        int nextWpt = min(currentWaypoint + 1, numWaypoints-1);
        if (nextWpt != currentWaypoint) {
            cout << "FINISHED waypt: " << currentWaypoint << " (" << waypointRange[currentWaypoint] << " m)\n";
            cout << "waypt stats: \n";
            cout << "chaserPos[" << chaserPos0[0] << ", " << chaserPos0[1] << ", " << chaserPos0[2] << "]\n";
            cout << "chaserVel[" << chaserVel0[0] << ", " << chaserVel0[1] << ", " << chaserVel0[2] << "]\n";
            cout << "velTolerance: " << velTolerance << " m/s\n\n";
        }
        currentWaypoint = nextWpt;
        wayptTfinal = -1.0;
    }

    return 0;
}