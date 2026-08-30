#ifndef ORBIT_UTIL_HH
#define ORBIT_UTIL_HH


/* Fills pos_eci[] and vel_eci[] from classical elements. */
int elementsToCartesian(double sma, double ecc, double inc,
                        double raan, double argp, double trueAnom,
                        double pos_eci[3], double vel_eci[3]);

/* Expresses posIn/velIn in the reference vehicle's LVLH (Hill) frame:
   [radial, along-track, cross-track]. Returns posIn - posRef, so
   eciToLvlh(target, chaser) gives CHASER-RELATIVE-TO-TARGET. Velocity
   includes the -omega x r term for the frame's own rotation. */
int eciToLvlh(const double posRef[3], const double velRef[3], const double posIn[3], const double velIn[3], double posOut[3], double velOut[3]);

int lvlhToEci(const double posRef[3], const double velRef[3], const double vecLvlh[3], double vecEci[3]);


/* Unit vector to Sun in ECI, analytic low-precision ephemeris. */
int sunVector_eci(double simTime, double sunVec_eci[3]);

/* Tilted-dipole field DIRECTION in ECI. Magnitude not modeled. */
int dipoleDir_eci(const double pos_eci[3], double simTime,
                  double coelev, double eastLon, double gmst0,
                  double dir_eci[3]);

#endif