#include "../include/thruster.hh"
#include <cmath>
#include <eigen3/Eigen/Dense>
#include <iostream>

using namespace Eigen;
using namespace std;


Thruster::Thruster() {}

int Thruster::default_data() {
    isFiring = false;
    satMass = 200.0;
    thrustForce = 3.0;
    numQueued = 0;
    dVAccumulated = 0.0;
    timestamp = -0.05;
    for (int i = 0; i < 3; ++i)
        thrustAcc_eci[i] = 0.0;

    return 0;
}

/* Queue a burn from a desired delta-v; direction and duration are derived from thrustForce/mass. Zero-magnitude dV is a no-op. */
int Thruster::addBurn(double startTime, const double dVel_eci[3]) {
    /* calculate the burn command */
    Vector3d vectDv(dVel_eci);
    double dvNorm = vectDv.norm();
    if (dvNorm < 1e-9)
        return 0;

    /* calculate burn */
    double accelMag = thrustForce / satMass;
    Vector3d accel = accelMag * vectDv.normalized();
    double burnDuration = dvNorm / accelMag;\
    /* build burn command */
    BurnCmd burnCmd = {
        startTime,
        startTime + burnDuration
    };
    for (int i = 0; i < 3; ++i) 
        burnCmd.accel_eci[i] = accel[i];
    cout << "burn duration: " << burnDuration << "\n";

    /* queue the burn command */
    schedule.push(burnCmd);
    numQueued = schedule.size();

    return 0;
}


/* get the current burn command. If all are complete or there are none, it will return empty burnCmd */
Thruster::BurnCmd Thruster::getCurrentBurn(double currT) {
    while (!schedule.empty() && schedule.front().stopTime < currT)
        schedule.pop();
    numQueued = (int) schedule.size();

    if (schedule.empty())
        return {INFINITY, -INFINITY, {0.0, 0.0, 0.0}};

    return schedule.front();
}


/* if it is way off, maybe it might be good to have it to reset burns */ 
int Thruster::clearAllBurns() {
    while (!schedule.empty())
        schedule.pop();
    numQueued = 0;

    return 0;
}


/* True if any burn is running or still pending. Guidance should use this instead of sniffing the acceleration command. */
bool Thruster::isBusy(double currT) {
    return getCurrentBurn(currT).stopTime >= currT;
}

/* Called by Trick to turn on/off thruster depending on schedule */
/* Also updates thrustAcc_eci */
int Thruster::update(double currT) {
    const BurnCmd cmd = getCurrentBurn(currT);
    isFiring = (currT >= cmd.startTime) && (currT <= cmd.stopTime);

    double accMag = 0.0;
    for (int i = 0; i < 3; ++i) {
        thrustAcc_eci[i] = isFiring ? cmd.accel_eci[i] : 0.0;
        accMag += thrustAcc_eci[i] * thrustAcc_eci[i];
    }
    accMag = sqrt(accMag);

    const double dt = currT - timestamp;
    if (dt > 0.0)
        dVAccumulated += accMag * dt;
    timestamp = currT;

    return 0;
}