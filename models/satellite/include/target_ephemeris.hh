/*************************************************************************
PURPOSE: TargetEphemeris -- simulate the chaser's onboard knowledge of the target state.
**************************************************************************/

#ifndef TARGET_EPHEMERIS_HH
#define TARGET_EPHEMERIS_HH

class TargetEphemeris {
    public:
        double pos_eci[3];      /* (m)      onboard estimate of target pos */
        double vel_eci[3];      /* (m/s)    onboard estimate of target vel */
        double timestamp;       /* (s)      sim time at last update */
        bool isValid;           /* (--)     whether state is usable */

        bool addNoise;          /* (--)     default is no */
        double posSigma;        /* (m)      ~50, typical uplink accuracy */
        double velSigma;        /* (m/s)    ~0.05 */

        double posBias[3];      /* (m)      per-run draw, held for the run */
        double velBias[3];      /* (m/s)    per-run draw, held for the run */

        TargetEphemeris();

        int default_data();

        int initialize();

        /* inputs are actual position and vel of target sat, updates the TargetEphemeris pos_eci and vel_eci with or without noise */
        int update(const double posTruth[3], const double velTruth[3]);
};

#endif /* TARGET_EPHEMERIS_HH */