#include <cmath>
#include <math.h>
#include "../include/satellite.hh"
#include <eigen3/Eigen/Dense>

using namespace std;
using namespace Eigen;


// pos_eci[] and vel_eci[] will be the return values filled by the function 
int elementsToCartesian(double sma, double ecc, double inc, double raan, double argp, double trueAnom, double pos_eci[3], double vel_eci[3]) {
    // Guards
    if (!(ecc >= 0.0) || ecc >= 1.0) return -1;   // also catches NaN input
    if (!(sma > 0.0)) return -1;
    const double denom = 1.0 + ecc * std::cos(trueAnom);
    if (std::fabs(denom) < 1e-12) return -1;


    // mu is the gravitational parameter itself 
    // Units must match sma: km^3/s^2 with km, or m^3/s^2 with m.
    const double mu = MU_EARTH;
    
    const double p = sma * (1.0 - ecc * ecc);
    const double r = p / (1.0 + ecc * std::cos(trueAnom));
    const double h = std::sqrt(mu * p);
    
    // Perifocal frame: x toward periapsis, z along angular momentum.
    Vector3d r_pf { r * std::cos(trueAnom),
                        r * std::sin(trueAnom),
                        0.0 };
    
    Vector3d v_pf { -std::sin(trueAnom),
                        ecc + std::cos(trueAnom),
                        0.0 };
    v_pf *= mu / h;
    
    const double c_raan = std::cos(raan),  s_raan = std::sin(raan);
    const double c_inc  = std::cos(inc),   s_inc  = std::sin(inc);
    const double c_argp = std::cos(argp),  s_argp = std::sin(argp);
    
    // R = Rz(raan) Rx(inc) Rz(argp). Columns are the perifocal basis in ECI:
    // column 1 points at periapsis, column 3 is the orbit normal.
    Matrix3d R;
    R << c_raan*c_argp - s_raan*s_argp*c_inc, -c_raan*s_argp - s_raan*c_argp*c_inc, s_raan*s_inc,
        s_raan*c_argp + c_raan*s_argp*c_inc, -s_raan*s_argp + c_raan*c_argp*c_inc, -c_raan*s_inc,
        s_argp*s_inc,c_argp*s_inc, c_inc;
    const Vector3d r_eci = R * r_pf;
    const Vector3d v_eci = R * v_pf;
    for (int i = 0; i < 3; i++){
        pos_eci[i] = r_eci[i];
        vel_eci[i] = v_eci[i];
    }
    return 0;
}

/* 
* Expresses the chaser's state relative to a reference vehicle in that
* vehicle's LVLH (Hill) frame: [radial, along-track, cross-track].
* Velocity includes the -omega x r term for the frame's own rotation.
*/
int eciToLvlh(const double posRef[3], const double velRef[3], const double posIn[3], const double velIn[3], double posOut[3], double velOut[3]) {
    Map<const Vector3d> rRef(posRef);
    Map<const Vector3d> vRef(velRef);
    Map<const Vector3d> rIn(posIn);
    Map<const Vector3d> vIn(velIn);

    // Guard 1
    const double rMag = rRef.norm();
    if (!(rMag > 1e-6)) return -1;

    Vector3d rHat = rRef.normalized();
    Vector3d h = rRef.cross(vRef);
    // Guard 2
    const double h_mag = h.norm();
    if (!(h_mag > 1e-6)) return -1;   // degenerate: radial trajectory
    Vector3d hHat = h.normalized();
    Vector3d sHat = hHat.cross(rHat);

    Vector3d dr = rIn - rRef;
    Vector3d dv = vIn - vRef;

    Vector3d omega = (h.norm() / rRef.squaredNorm()) * h.normalized();
    Vector3d dvrot = dv - omega.cross(dr);

    Matrix3d R;
    R.row(0) = rHat;
    R.row(1) = sHat;
    R.row(2) = hHat;

    const Vector3d rLVLH = R * dr;
    const Vector3d vLVLH = R * dvrot;
    
    for (int i = 0; i < 3; i++){
        posOut[i] = rLVLH[i];
        velOut[i] = vLVLH[i];
    }
    return 0;
}

int lvlhToEci(const double posRef[3], const double velRef[3], const double vecLvlh[3], double vecEci[3]) {
    Map<const Vector3d> rRef(posRef);
    Map<const Vector3d> vRef(velRef);
    Map<const Vector3d> vLvlh(vecLvlh);

    const double rMag = rRef.norm();
    if (!(rMag > 1e-6)) return -1;

    Vector3d rHat = rRef.normalized();
    Vector3d h = rRef.cross(vRef);
    const double h_mag = h.norm();
    if (!(h_mag > 1e-6)) return -1;
    Vector3d hHat = h.normalized();
    Vector3d sHat = hHat.cross(rHat);

    Matrix3d R;
    R.row(0) = rHat;
    R.row(1) = sHat;
    R.row(2) = hHat;

    Vector3d vEci = R.transpose() * vLvlh;

    for (int i = 0; i < 3; i++)
        vecEci[i] = vEci[i];

    return 0;
}