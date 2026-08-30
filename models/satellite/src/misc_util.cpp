#include "../include/satellite.hh"

#include <eigen3/Eigen/Dense>
#include <cmath>
#include <random>

using namespace Eigen;
using namespace std;
using Matrix6d = Matrix<double, 6, 6>;


double generateGaussianNoise(double sigma) {
    random_device rd;
    mt19937 gen(rd());

    normal_distribution<double> dist(0.0, sigma);
    return dist(gen);
}

void generateGaussianNoise3d(double sigma, Vector3d& noise) {
    for (int i = 0; i < 3; i++)
        noise(i) = generateGaussianNoise(sigma);
}

void buildSatFrame(const Vector3d& r, const Vector3d& v, Matrix3d& R) {
    Vector3d x = r.normalized();
    Vector3d z = r.cross(v).normalized();
    Vector3d y = z.cross(x).normalized();

    R.col(0) = x;
    R.col(1) = y;
    R.col(2) = z;
}

// get n from semi major axis and mu_earth
double calculateN(double sma) {
    return sqrt(MU_EARTH / (sma * sma * sma));
}

/*
 * Clohessy-Wiltshire state transition matrix for a circular reference
 * orbit of mean motion n over an interval dt.
 * State order: [radial, along-track, cross-track, and their rates].
 */
void cwTransitionMatrix(double n, double dt, Matrix6d& phi) {
    phi.setZero();
    const double c = cos(n*dt);
    const double s = sin(n*dt);

    /* phi_rr */
    phi(0,0) = 4.0 - 3.0*c;
    phi(1,0) = 6.0*(s - n*dt);
    phi(1,1) = 1.0;
    phi(2,2) = c;
    /* phi_rv */
    phi(0,3) = s/n;
    phi(0,4) = 2.0*(1.0 - c)/n;
    phi(1,3) = -2.0*(1.0 - c)/n;
    phi(1,4) = (4.0*s - 3.0*n*dt)/n;
    phi(2,5) = phi(0,3);
    /* phi_vr */
    phi(3,0) = 3.0*n*s;
    phi(4,0) = 6.0*n*(c - 1.0);
    phi(5,2) = -n*s;
    /* phi_vv */
    phi(3,3) = c;
    phi(3,4) = 2.0*s;
    phi(4,3) = -2.0*s;
    phi(4,4) = 4.0*c - 3.0;
    phi(5,5) = c;
}