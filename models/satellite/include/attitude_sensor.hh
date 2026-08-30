/*************************************************************************
PURPOSE: AttitudeSensor -- merged sun + magnetometer, outputs measured attitude.
**************************************************************************/

#ifndef ATTITUDE_SENSOR_HH
#define ATTITUDE_SENSOR_HH

#define DEG2RAD (M_PI/180.0)

/*========================================================================
 * AttitudeSensor -- merged sun + magnetometer, outputs measured attitude.
 *
 * Truth measurement generation, driven by the truth pos/vel state. Never
 * pass a filter estimate -- same rule as Rangefinder.
 *
 * Internally: sun and field DIRECTIONS in ECI from models, rotated into
 * body with the truth attitude from buildSatFrame(), corrupted, then an
 * attitude recovered with TRIAD (sun primary, mag secondary). Field
 * magnitude is never modeled -- attitude uses direction only.
 *
 * ASSUMES the truth attitude is LVLH-locked. If real attitude dynamics
 * are ever added, this class must change too or it will keep reporting
 * the LVLH frame and silently stop measuring truth.
 *
 * ASSUMPTION 1 -- no eclipse, Sun pinned to ECI +x. Any drift or coverage
 * result out of this sim is OPTIMISTIC: real LEO loses the Sun ~35 min
 * per orbit, during which attitude would be on gyro propagation alone.
 * Adding eclipse means adding a second, vector-only update path to the
 * filter -- not a change confined to this class.
 *
 * ASSUMPTION 2 -- centered dipole ALIGNED with the spin axis. Real
 * Earth's dipole is tilted ~11 deg; harmless here only because sensor
 * and filter share the model. Note magSigma is therefore a pure sensor
 * number; in flight, field-model error (1-3 deg) would dominate it.
 *
 * Both references are now time-invariant, so geometryAngle is a periodic
 * function of ORBITAL POSITION alone. Degeneracies recur at the same
 * points every orbit -- reproducible, but coverage statistics are
 * meaningless. Equatorial orbits are the trap: rz = 0 pins geometryAngle
 * at exactly 90 deg for the whole run, and the degraded axis of Ratt is
 * never exercised. Check the logged range before drawing conclusions.
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