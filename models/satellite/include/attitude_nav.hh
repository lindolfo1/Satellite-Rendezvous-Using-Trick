/*************************************************************************
PURPOSE: M-Extended Kalman filter for attitude
**************************************************************************/

#ifndef ATTITUDE_NAV_HH
#define ATTITUDE_NAV_HH

/*========================================================================
 * AttitudeNav -- 6-state MEKF, error state [attErr(3), gyroBiasErr(3)].
 *
 * The reference quaternion absorbs the attitude error each update, so the
 * error state is zeroed after every correction and stays small.
 *=======================================================================*/
class AttitudeNav {
    public:
        double qHat[4];     /* (--)     reference attitude, body->ECI */
        double gyroBiasHat[3]; /* (rad/s)  estimated gyro bias */
        double P[6][6];     /* (--) */
        double Q[6][6];     /* (--) */
 
        double attSigma0;   /* (rad) */
        double biasSigma0;  /* (rad/s) */

        bool isInitialized; /* (--) */

        AttitudeNav();
        int default_data();

        /* arw/rrw come from the IMU error model and build Q. */
        int initialize(double arw, double rrw, const double qMeas[4]);

        /* dTheta is the IMU delta-angle; bias estimate is removed here. */
        int propagate(const double dThetaGyro[3], double dTime, double arw, double rrw);

        /* R comes straight from AttitudeSensor::R_att. */
        int update(const double qMeas[4], const double R[3][3]);
};

#endif /* ATTITUDE_NAV_HH */