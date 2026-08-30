/*************************************************************************
PURPOSE: Rangefinder -- body-fixed range + bearing sensor.
**************************************************************************/

#ifndef RANGEFINDER_HH
#define RANGEFINDER_HH

/*========================================================================
 * Rangefinder -- body-fixed range + bearing sensor.
 *
 * Truth measurement generation. Must be driven by the TRUTH attitude
 * (q_eci2body_truth), never by a filter estimate: real hardware sees what
 * the vehicle is actually pointing at. Sharing one quaternion between
 * sensor generation and filter prediction cancels attitude error out of
 * the innovation and makes the attitude unobservable by construction.
 *=======================================================================*/
class Rangefinder {
    public:
        /* --- output --- */
        double range;           /* (m)      chaser-to-target distance */
        double azimuth;         /* (rad)    bearing in body x-y plane */
        double elevation;       /* (rad)    bearing above body x-y plane */
        double timestamp;       /* (s)      sim time at measurement */
        bool   isValid;         /* (--)     whether the sample is usable */

        /* --- error model (dispersible) --- */
        bool   addNoise;
        double rangeSigmaBase;  /* (m)      range noise floor */
        double rangeSigmaSlope; /* (--)     range noise growth per meter */
        double angleSigma;      /* (rad)    bearing noise, per axis */

        Rangefinder();
        int default_data();

        /* qChaser is body->ECI (see header comment). */
        int track(const double posChaser[3], const double qChaser[4],
                  const double posTarget[3]);
};

#endif /* RANGEFINDER_HH */