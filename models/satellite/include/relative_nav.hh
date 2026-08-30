/*************************************************************************
PURPOSE: RelativeNav -- 6-state EKF over the rangefinder ONLY.
**************************************************************************/

#ifndef RELATIVE_NAV_HH
#define RELATIVE_NAV_HH

/*========================================================================
 * RelativeNav -- 6-state EKF over the rangefinder ONLY.
 *
 * States: relative position (3), relative velocity (3), expressed in the
 * target's LVLH frame, holding TARGET-RELATIVE-TO-CHASER (the sensor
 * line-of-sight sense).
 *=======================================================================*/
 class RelativeNav {
    public:
        double xHat[6];         /* (--)     [relPos(3) m, relVel(3) m/s], LVLH */
        double P[6][6];         /* (--)     covariance */
        double Q[6][6];         /* (--)     process noise, rebuilt each propagate */
        double R[3][3];         /* (--)     measurement noise, rebuilt each update */

        /* Initial uncertainty; initialize() builds P from these. */
        double posSigma0;       /* (m) */
        double velSigma0;       /* (m/s) */

        /* Process noise, per LVLH axis. QtransSigma is the COAST value:
           differential J2/drag and CW linearization only. QburnSigma is
           thrust execution error, added in quadrature while firing. Both
           are SIGMAS (m/s2) -- squared internally. */
        double QtransSigma[3];  /* (m/s2) */
        double QburnSigma;      /* (m/s2) */

        /* Sensor error model, mirrored from Rangefinder so R can be
           rebuilt at the current range every update. attitudeSigma is the
           1-sigma attitude estimate error that leaks into az/el; leave 0
           while truth attitude is wired in, set it when the attitude
           filter lands. */
        double rangeSigmaBase;  /* (m) */
        double rangeSigmaSlope; /* (--) */
        double angleSigma;      /* (rad) */
        double attitudeSigma;   /* (rad) */

        bool   isInitialized;
        bool   debugLog;        /* (--) NIS/HPHt console output */

        RelativeNav();
        int default_data();

        /* All tuning is now member state, dispersible from the input file. */
        int initialize();

        /* accel_lvlh is the CHASER's commanded/sensed acceleration expressed
           in the target's LVLH frame. */
        int navigate_propagate(double dTime, double n,
                               const double accel_lvlh[3], bool isFiring);

        int navigate_update(double posTarget_eci[3], double velTarget_eci[3],
                            double rfAttitude[3], const double qChaser[4]);
};

#endif /* RELATIVE_NAV_HH */