/*************************************************************************
PURPOSE: IMU -- strapdown inertial measurement unit.
**************************************************************************/

#ifndef IMU_HH
#define IMU_HH

/*========================================================================
 * IMU -- strapdown inertial measurement unit.
 *
 * dTheta is a delta-ANGLE (rad) over dTime, not a rate. dVel is SPECIFIC
 * FORCE (gravity removed), so it reads ~0 in free fall.
 *
 * Nothing consumes dTheta/dVel yet. dTheta is the input to the attitude
 * filter when that is written; dVel is the input to thrust sensing.
 *=======================================================================*/
class IMU {
    public:
        /* --- output --- */
        double dVel[3];         /* (m/s)    delta-velocity, specific force, body frame */
        double dTheta[3];       /* (rad)    delta-angle over dTime, body frame */
        double dTime;           /* (s)      accumulation interval */
        double timestamp;       /* (s)      sim time at end of interval */
        bool   isValid;         /* (--)     whether the sample is usable */

        /* --- error model (dispersible from the input file) --- */
        bool   addNoise;
        double accelBias[3];    /* (m/s2)       per-run accelerometer bias */
        double gyroBias[3];     /* (rad/s)      per-run gyro bias */
        double vrw;             /* (m/s/s^0.5)  velocity random walk */
        double arw;             /* (rad/s^0.5)  angle random walk */
        double rrw;             /* (rad/s/s^0.5) rate random walk */

        /* Gravity model used to convert total acceleration to specific
           force. MUST match Satellite::j2Enabled -- a mismatch reads as
           phantom thrust. Synced in Satellite::initialize(). */
        bool   j2Enabled;       /* (--) */

        IMU();
        int default_data(bool enableJ2);

        int sample_imu(double x1[3], double x2[3], double x3[3]);
};

#endif /* IMU_HH */