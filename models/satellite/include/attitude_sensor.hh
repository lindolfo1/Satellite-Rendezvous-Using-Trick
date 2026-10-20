/*************************************************************************
PURPOSE: AttitudeSensor -- merged sun + magnetometer, outputs measured attitude.
**************************************************************************/

#ifndef ATTITUDE_SENSOR_HH
#define ATTITUDE_SENSOR_HH

#define DEG2RAD (M_PI/180.0)

/*========================================================================
 * AttitudeSensor -- merged sun + magnetometer, outputs measured attitude.
 *=======================================================================*/
class AttitudeSensor {
    public:
        /* output */
        double qMeas[4];    /* (--)     measured attitude, body->ECI */
        double Ratt[3][3];  /* (rad2)   attitude error covariance, body frame */
        double timestamp;   /* (s) */
        bool isValid;       /* (--)     false if geometry is degenerate */

        /* diagnostics */
        double geometryAngle;   /* (rad)    angle between sun and field lines */

        /* error model */
        bool addNoise;      /* (--) */
        double sunSigma;    /* (rad)    sun direction sensor error (sensor accuracy limit) */
        double magSigma;    /* (rad)    magnetic field sensor direction error (sensor accuracy limit) */

        double sunAlignBias[3]; /* (rad)    per-run sun sensor misalignment */
        double magAlignBias[3]; /* (rad)    per-run mag misalignment + hard iron */
        double minGeometry;     /* (rad)    gate where below this TRIAD is singular */

        AttitudeSensor();
        int default_data();

        /* q is body->ECI (truth). simTime drives the sun ephemeris and the timestamp only. The field model does not use it. */
        int sample(const double pos_eci[3], const double vel_eci[3]);
};


#endif /* ATTITUDE_SENSOR_HH */
