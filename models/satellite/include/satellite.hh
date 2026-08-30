/*************************************************************************
PURPOSE: (Satellite truth state, sensors, and relative-navigation filter)

FRAME/QUATERNION CONVENTION -- read this before touching any rotation.

  buildSatFrame() sets the COLUMNS of R to the body axes expressed in ECI.
  A matrix whose columns are the target frame's basis vectors maps
  body -> ECI. Every quaternion built from it therefore rotates body -> ECI,
  and going ECI -> body requires the conjugate/transpose.

  All quaternions here are scalar-first: [q0, qx, qy, qz].
**************************************************************************/

#ifndef SATELLITE_HH
#define SATELLITE_HH

/* Physical constants */
#define MU_EARTH  3.986004418e14   /* (m3/s2)  Earth's gravitational constant */
#define R_EARTH   6.378137e6       /* (m)      Earth's equatorial radius */
#define J2_EARTH  1.08262668e-3    /* (--)     Earth's J2 coefficient */

#include "./rangefinder.hh"
#include "./imu.hh"
#include "./relative_nav.hh"
#include "./guidance.hh"
#include "./thruster.hh"
#include "./attitude_sensor.hh"
#include "./attitude_nav.hh"
#include "./target_ephemeris.hh"


class Satellite {
    public:
      /* --- orbit definition: PRIMARY, set by default_data / input file --- */
      double sma;             /* (m)      semi-major axis */
      double ecc;             /* (--)     eccentricity */
      double inc;             /* (rad)    inclination */
      double raan;            /* (rad)    right ascension of ascending node */
      double argp;            /* (rad)    argument of perigee */
      double trueAnom;        /* (rad)    true anomaly */

      /* --- truth state: DERIVED by initialize(), then owned by the
             integrator. Never set these from the input file. --- */
      double pos_eci[3];      /* (m)      ECI: x vernal eq, z north pole */
      double vel_eci[3];      /* (m/s) */
      double acc_eci[3];      /* (m/s2) */
      double n;               /* (rad/s)  orbital rate, sqrt(mu/sma^3) */

      /* Truth attitude, body->ECI. Drives sensor models only. Never feed
         a filter estimate to a sensor. */
      double q_eci2body_truth[4];

      /* posHistory[0] = current, [1] = t-1, [2] = t-2, ECI.
         initialize() seeds [1] and [2] by backward Kepler propagation;
         posHistorySeeded makes each vehicle skip its own first
         update_pos_history() call, which would otherwise run at t=0
         before any integration and overwrite that seeding with a
         degenerate duplicate. Per-object, NOT a function-local static --
         a static would let only one of chaser/target skip. */
      double posHistory[3][3];
      bool   posHistorySeeded;


      /* --- model options --- */
      bool j2Enabled;
      IMU         imu;
      Rangefinder rangefinder;
      RelativeNav relNav;
      Guidance    guidance;
      Thruster    thruster;
      AttitudeSensor attSensor;
      AttitudeNav attNav;
      TargetEphemeris targetEph;
      Satellite();

      /* --- Trick jobs --- */
      int default_data();
      int initialize();
      // int navigate_initialize(Satellite& other);
      int navigate_initialize();
      int att_initialize();
      int derivative();
      int integ();
      int update_truth_attitude();
      int update_pos_history();
      int track(Satellite& other);
      // int navigate_propagate(Satellite& other);
      int navigate_propagate();
      // int navigate_update(Satellite& other);
      int navigate_update();
      int att_propagate();
      int att_update();
      //   int guide(Satellite& other);
      int guide();
      int shutdown();
      int thrustUpdate();
      int update_target_ephemeris(Satellite& other);
};
              

#endif /* SATELLITE_HH */
