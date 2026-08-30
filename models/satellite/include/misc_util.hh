#ifndef MISC_UTIL_HH
#define MISC_UTIL_HH

#include <eigen3/Eigen/Dense>

using namespace Eigen;
using Matrix6d = Matrix<double, 6, 6>;


double generateGaussianNoise(double sigma);
void generateGaussianNoise3d(double sigma, Vector3d& noise);
void buildSatFrame(const Vector3d& r, const Vector3d& v, Matrix3d& R);
double calculateN(double sma);
void cwTransitionMatrix(double n, double dt, Matrix6d& phi);

#endif