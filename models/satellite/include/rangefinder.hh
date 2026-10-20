/*************************************************************************
PURPOSE: Rangefinder -- body-fixed range + bearing sensor.
**************************************************************************/

#ifndef RANGEFINDER_HH
#define RANGEFINDER_HH

/*========================================================================
 * Rangefinder -- body-fixed range + bearing sensor.
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
