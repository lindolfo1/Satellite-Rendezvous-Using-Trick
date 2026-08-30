#include "../include/attitude_nav.hh"
// #include "trick/exec_proto.h"

#include <cmath>
#include <eigen3/Eigen/Dense>
#include <iterator>
// #include <iostream>

using namespace Eigen;
using namespace std;

AttitudeNav::AttitudeNav() {}


int AttitudeNav::default_data() {
    attSigma0 = 2.0 * (M_PI / 180.0);
    biasSigma0 = (10.0 / 3600.0) * M_PI / 180.0;

    qHat[0] = 1.0;
    qHat[1] = 0.0;
    qHat[2] = 0.0;
    qHat[3] = 0.0;

    for (int i = 0; i < size(gyroBiasHat); ++ i)
        gyroBiasHat[i] = 0.0;

    for (int i = 0; i < size(P); ++ i) {
        for (int j = 0; j < size(P[i]); ++ j) {
            P[i][j] = 0.0;
            Q[i][j] = 0.0;
        }
    }

    isInitialized = false;
    return 0;
}


int AttitudeNav::initialize(double arw, double rrw, const double qMeas[4]) {
    for (int i = 0; i < 3; ++ i) {
        P[i][i] = attSigma0 * attSigma0;
        P[i+3][i+3] = biasSigma0 * biasSigma0;

        Q[i][i] = arw * arw;
        Q[i+3][i+3] = rrw * rrw;
    }

    for (int i = 0; i < size(qHat); ++ i)
        qHat[i] = qMeas[i];

    for (int i = 0; i < 3; ++ i)
        gyroBiasHat[i] = 0.0;

    isInitialized = true;

    return 0;
}


int AttitudeNav::propagate(const double dThetaGyro[3], double dTime, double arw, double rrw) {
    if (!isInitialized) return -1;

    Vector3d dTheta(dThetaGyro);
    for (int i = 0; i < dTheta.size(); ++ i)
        dTheta(i) -= gyroBiasHat[i];

    const double theta = dTheta.norm();

    Quaterniond dq;
    if (theta > 1.0e-12) {
        const double s = sin(theta / 2.0) / theta;
        dq = Quaterniond(cos(theta / 2.0),
                         dTheta(0)*s, dTheta(1)*s, dTheta(2)*s);
    } else {
        dq = Quaterniond(1.0, 0.5*dTheta(0), 0.5*dTheta(1), 0.5*dTheta(2));
    }
    
    Quaterniond q(qHat[0], qHat[1], qHat[2], qHat[3]);

    q = (q * dq).normalized();
    qHat[0] = q.w();
    qHat[1] = q.x();
    qHat[2] = q.y();
    qHat[3] = q.z();

    Vector3d w = dTheta/dTime;

    Matrix3d wx;
    wx <<   0.0, -w(2),  w(1),
           w(2),   0.0, -w(0),
          -w(1),  w(0),   0.0;

    /* create phi */
    Matrix<double, 6, 6> phi = Matrix<double,6,6>::Identity();
    phi.block<3,3>(0,0) = Matrix3d::Identity() - wx * dTime;
    phi.block<3,3>(0,3) = -Matrix3d::Identity() * dTime;

    /* build Qd (not Q) */
    const double sv2 = arw * arw;
    const double su2 = rrw * rrw;
    const double a = sv2*dTime + su2*dTime*dTime*dTime/3.0;
    const double b = su2*dTime;
    const double c = -su2*dTime*dTime/2.0;
    Matrix<double,6,6> Qd = Matrix<double,6,6>::Zero();
    for (int i = 0; i < 3; ++i) {
        Qd(i,i)     = a;
        Qd(i+3,i+3) = b;
        Qd(i,i+3)   = c;
        Qd(i+3,i)   = c;
    }
    
    Matrix<double,6,6> Pk;
    for (int i = 0; i < 6; ++i)
        for (int j = 0; j < 6; ++j)
            Pk(i,j) = P[i][j];
        
    Pk = phi * Pk * phi.transpose() + Qd;

    for (int i = 0; i < size(P); ++ i)
        for (int j = 0; j < size(P[i]); ++ j)
            P[i][j] = Pk(i, j);
    
    return 0;
}


int AttitudeNav::update(const double qMeas[4], const double R[3][3]) {
    /* build qErr */
    Quaterniond q (qHat[0],  qHat[1],  qHat[2],  qHat[3]);
    Quaterniond qM(qMeas[0], qMeas[1], qMeas[2], qMeas[3]);
    Quaterniond qErr = q.conjugate() * qM;
    /* guard rotations about opposite axis of rotation */
    if (qErr.w() < 0)
        qErr.coeffs() *= -1.0;

    /* build z */
    const Vector3d z = 2.0 * qErr.vec();

    /* calculate S */
    Matrix<double,6,6> Pk;
    for (int i = 0; i < 6; ++i)
        for (int j = 0; j < 6; ++j)
            Pk(i,j) = P[i][j];

    Matrix3d Ratt;
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            Ratt(i,j) = R[i][j];

    Matrix3d Paa = Pk.block<3,3>(0,0);
    Matrix3d Pba = Pk.block<3,3>(3,0);
    Matrix3d S = Paa + Ratt;

    /* build K */
    Matrix<double, 6, 3> K;
    K.block<3,3>(0,0) = Paa;
    K.block<3,3>(3,0) = Pba;
    K = K * S.inverse();

    Matrix<double, 6, 1> xErr = K * z;

    /* build H */
    Matrix<double,3,6> H = Matrix<double,3,6>::Zero();
    H.block(0, 0, 3, 3) = Matrix3d::Identity();

    Matrix<double, 6, 6> IKH = Matrix<double, 6, 6>::Identity() - K * H;

    /* update Pk */
    Pk = IKH * Pk * IKH.transpose() + K * Ratt * K.transpose();
    Pk = 0.5 * (Pk + Pk.transpose().eval());
    for (int i = 0; i < size(P); ++ i)
        for (int j = 0; j < size(P[i]); ++ j)
            P[i][j] = Pk(i, j);

    /* update q */
    Vector3d da = xErr.segment<3>(0);
    Quaterniond aErr(1.0, 0.5*da(0), 0.5*da(1), 0.5*da(2));
    q = (q * aErr).normalized();
    
    qHat[0] = q.w();
    qHat[1] = q.x();
    qHat[2] = q.y();
    qHat[3] = q.z();

    /* update gyroBias */
    const Vector3d db = xErr.segment<3>(3);
    Vector3d gyroBias(gyroBiasHat);
    for (int i = 0; i < 3; ++i)
        gyroBiasHat[i] += db(i);

    return 0;
}
