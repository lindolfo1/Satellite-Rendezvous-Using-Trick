#include "../include/relative_nav.hh"
#include "../include/misc_util.hh"
#include <cmath>
#include <eigen3/Eigen/Dense>

using namespace Eigen;
using namespace std;

using Vector6d    = Matrix<double, 6, 1>;
using Matrix6d    = Matrix<double, 6, 6>;
using Matrix6dRow = Matrix<double, 6, 6, RowMajor>;
using Matrix3dRow = Matrix<double, 3, 3, RowMajor>;


/* Direction cosine matrix from a scalar-first quaternion. Returns the
   same sense as the quaternion: body -> ECI. */
static void qToDcm(const double q[4], Matrix3d& C) {
    C(0,0) = 1.0 - 2.0*(q[2]*q[2] + q[3]*q[3]);
    C(0,1) = 2.0*(q[1]*q[2] - q[0]*q[3]);
    C(0,2) = 2.0*(q[1]*q[3] + q[0]*q[2]);
    C(1,0) = 2.0*(q[1]*q[2] + q[0]*q[3]);
    C(1,1) = 1.0 - 2.0*(q[1]*q[1] + q[3]*q[3]);
    C(1,2) = 2.0*(q[2]*q[3] - q[0]*q[1]);
    C(2,0) = 2.0*(q[1]*q[3] - q[0]*q[2]);
    C(2,1) = 2.0*(q[2]*q[3] + q[0]*q[1]);
    C(2,2) = 1.0 - 2.0*(q[1]*q[1] + q[2]*q[2]);
}

/* Piecewise-white acceleration process noise over dTime.

   Q = sigma_a^2 * [ dt^3/3 I,  dt^2/2 I ;
                     dt^2/2 I,  dt     I ]

   sigma is a SIGMA (m/s2); every entry of Q is a variance, hence the
   square. Getting this wrong by one square inflates Q by 1e5 at these
   magnitudes, which drives the gain to unity and turns the filter into a
   passthrough of the rangefinder. */
static void buildQ(const double sigma[3], double dTime, double Q[6][6]) {
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 6; j++)
            Q[i][j] = 0.0;

    const double dt2 = dTime*dTime/2.0;
    const double dt3 = dTime*dTime*dTime/3.0;

    for (int i = 0; i < 3; i++) {
        const double qa = sigma[i] * sigma[i];
        Q[i][i]     = dt3   * qa;
        Q[i][i+3]   = dt2   * qa;
        Q[i+3][i]   = dt2   * qa;
        Q[i+3][i+3] = dTime * qa;
    }
}

RelativeNav::RelativeNav() {}

int RelativeNav::default_data() {
    posSigma0     = 10.0;
    velSigma0     = 0.1;
    isInitialized = false;
    debugLog      = true;

    /* Coast process noise. Two vehicles on near-identical orbits differ
       by differential J2 (~1e-8 m/s2 at 1 km) plus CW linearization
       error. 1e-7 leaves headroom; sweep down from here against NIS. */
    for (int i = 0; i < 3; i++)
        QtransSigma[i] = 1.0e-7;

    /* Thrust execution error, ~3% of a 0.015 m/s2 command. */
    QburnSigma = 4.5e-4;

    /* Truth attitude is wired in at the seam, so no attitude error yet. */
    attitudeSigma = 0.0;

    return 0;
}

int RelativeNav::initialize() {
    /* Initial covariance */
    for (int i = 0; i < 6; i++)
        for (int j = 0; j < 6; j++)
            P[i][j] = 0.0;

    for (int i = 0; i < 3; i++) {
        P[i][i]     = posSigma0 * posSigma0;
        P[i+3][i+3] = velSigma0 * velSigma0;
    }

    /* R is rebuilt at the current range every update; this is only a
       sane starting value in case anything reads it before then. */
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            R[i][j] = 0.0;

    const double rs = rangeSigmaBase;
    R[0][0] = rs * rs;
    R[1][1] = angleSigma*angleSigma + attitudeSigma*attitudeSigma;
    R[2][2] = R[1][1];

    /* Q likewise: rebuilt each propagate at the dTime actually taken. */
    buildQ(QtransSigma, 1.0, Q);

    return 0;
}

int RelativeNav::navigate_propagate(double dTime, double n,
                                    const double accel_lvlh[3], bool isFiring) {
    Map<Vector6d>     x(&xHat[0]);
    Map<Matrix6dRow>  Pmap(&P[0][0]);
    Map<Matrix6dRow>  Qmap(&Q[0][0]);

    /* Two-regime process noise, built at the step actually taken rather
       than the one initialize() happened to see. Coasting, the dynamics
       are nearly exact and Q should be tiny; under thrust, execution
       error dominates and Q has to absorb it. */
    double sigma[3];
    for (int i = 0; i < 3; i++) {
        sigma[i] = isFiring
                 ? sqrt(QtransSigma[i]*QtransSigma[i] + QburnSigma*QburnSigma)
                 : QtransSigma[i];
    }
    buildQ(sigma, dTime, Q);

    Matrix6d phi;
    cwTransitionMatrix(n, dTime, phi);

    /* Control input. xHat holds TARGET-relative-to-CHASER, so the
       chaser's own thrust enters the relative state with a NEGATIVE sign.
       Gamma uses the rectilinear [dt^2/2; dt] form: at n*dt ~ 5e-7 for a
       0.5 s step in LEO, the CW correction to Gamma is orders of
       magnitude below the noise floor. */
    const Vector3d a(accel_lvlh);
    Vector6d gamma;
    gamma.head<3>() = -0.5 * dTime * dTime * a;
    gamma.tail<3>() = -dTime * a;

    const Vector6d xNew = phi * x + gamma;
    for (int i = 0; i < 6; i++)
        xHat[i] = xNew(i);

    Pmap = (phi * Pmap * phi.transpose() + Qmap).eval();
    Pmap = (0.5 * (Pmap + Pmap.transpose())).eval();

    return 0;
}

int RelativeNav::navigate_update(double posTarget_eci[3], double velTarget_eci[3],
                                 double rfAttitude[3], const double qChaser[4]) {
    /* Rotation taking a vector from the target's LVLH frame into the
       chaser's sensor/body frame.

       buildSatFrame sets COLUMNS, so CLvlhEci maps LVLH -> ECI; qToDcm
       returns the quaternion's own sense, body -> ECI. The composition
       below is validated: with noise off, xs matches the independently
       computed truth line-of-sight to 4+ significant figures. */
    Matrix3d CLvlhEci, CBodyEci;
    Vector3d pt(posTarget_eci), vt(velTarget_eci);
    buildSatFrame(pt, vt, CLvlhEci);
    qToDcm(qChaser, CBodyEci);

    const Matrix3d rotMat = CLvlhEci * CBodyEci.transpose();

    Map<Vector3d> r(&xHat[0]);
    const Vector3d xs = rotMat.transpose() * r;

    /* Predicted measurement */
    const double rxy  = sqrt(xs(0)*xs(0) + xs(1)*xs(1));
    const double rxy2 = rxy * rxy;

    Vector3d hx;
    hx(0) = xs.norm();
    hx(1) = atan2(xs(1), xs(0));
    hx(2) = atan2(xs(2), rxy);

    /* Degenerate geometry: the Jacobian below divides by rxy and rxy^2,
       so a line of sight along the sensor boresight blows up the gain. */
    if (!(rxy > 1.0e-6) || !(hx(0) > 1.0e-6))
        return -1;

    Map<Matrix3dRow>  Rk(&R[0][0]);
    Map<Matrix6dRow>  Pmap(&P[0][0]);

    /* Range noise is range-dependent in the sensor model, so R must
       follow it. Fixing R at one range under-trusts the sensor at close
       approach and over-trusts it far out -- mistuned at one end of the
       trajectory by construction. Bearings pick up attitude estimate
       error in quadrature. */
    const double rs = rangeSigmaBase + rangeSigmaSlope * hx(0);
    Rk(0,0) = rs * rs;
    Rk(1,1) = angleSigma*angleSigma + attitudeSigma*attitudeSigma;
    Rk(2,2) = Rk(1,1);

    const Vector3d zk(rfAttitude);
    Vector3d yk = zk - hx;
    /* Azimuth is an angle: wrap the residual, or a measurement either side
       of +/-pi produces a ~2pi innovation on a quantity that barely moved. */
    yk(1) = atan2(sin(yk(1)), cos(yk(1)));

    /* Measurement Jacobian w.r.t. relative position. Velocity columns are
       zero: range/az/el carry no instantaneous velocity information. */
    Matrix<double, 3, 6> Hk;
    Hk.setZero();
    for (int j = 0; j < 3; j++) {
        Hk(0, j) = rotMat.row(j).dot(xs) / hx(0);
        Hk(1, j) = (-rotMat(j,0)*xs(1) + rotMat(j,1)*xs(0)) / rxy2;
        Hk(2, j) = (rotMat(j,2)*rxy2
                    - xs(2)*(rotMat(j,0)*xs(0) + rotMat(j,1)*xs(1)))
                   / (rxy * hx(0) * hx(0));
    }

    const Matrix3d HPHt = Hk * Pmap * Hk.transpose();
    const Matrix3d Sk   = HPHt + Rk;
    const Matrix<double, 6, 3> Kk = Pmap * Hk.transpose() * Sk.inverse();

    const Vector6d deltaX = Kk * yk;
    for (int i = 0; i < 6; i++)
        xHat[i] += deltaX(i);

    /* Joseph form: stays symmetric positive-definite under roundoff. */
    const Matrix6d IKH = Matrix6d::Identity() - Kk * Hk;
    Pmap = (IKH * Pmap * IKH.transpose() + Kk * Rk * Kk.transpose()).eval();
    Pmap = (0.5 * (Pmap + Pmap.transpose())).eval();

    return 0;
}