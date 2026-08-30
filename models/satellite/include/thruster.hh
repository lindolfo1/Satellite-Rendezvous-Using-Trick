/*************************************************************************
PURPOSE: Simulates the thruster scheduler and the acceleration due to the thruster
**************************************************************************/

#ifndef THRUSTER_HH
#define THRUSTER_HH

#include <queue>

/******************************* TRICK HEADER ****************************
NOTE ON THE STL member: Trick's checkpoint agent handles std::queue when
it is nested in a class the memory manager knows about, so the schedule
survives checkpoint/restore. It is NOT visible to data recording, the
variable server, or the input processor -- unlike a fixed array. The
scalars below (numQueued, dVAccumulated, isFiring) are plain types
specifically so the queue's state stays observable in run data.

Burns must be enqueued in non-decreasing startTime order.
*************************************************************************/
class Thruster {
    public:
        enum {MAX_BURNS = 16};

        struct BurnCmd {
            double startTime;       /* (s)      timestamp for start of burn */
            double stopTime;        /* (s)      timestamp for end of burn */
            double accel_eci[3];    /* (m/s2)   commanded acceleration (ECI) */
        };

        std::queue<BurnCmd> schedule;   /* not ICG-visible; see header note     */
        
        int numQueued;              /* (--)     number of burns queued */
        double dVAccumulated;       /* (m/s)    total delta-v delivered */
        bool isFiring;              /* (--)      true if currently thrusting */
        double thrustAcc_eci[3];    /* (m/s2)   current commanded acceleration (ECI) */
        double timestamp;           /* (s)      sim time at update */

        double thrustForce;         /* (kg*m/s2)    the magnitude of the rocket's thrust */
        double satMass;             /* (kg)         mass of satellite */
        
        Thruster();
        int default_data();

        /* Queue a burn from a desired delta-v (ECI); direction and duration are derived from thrustForce/mass. Zero-magnitude dV is a no-op. */
        int addBurn(double startTime, const double dVel_eci[3]);

        /* get the current burn command. If all are complete or there are none, it will return empty burnCmd */
        BurnCmd getCurrentBurn(double currT);

        /* if it is way off, maybe it might be good to have it to reset burns */ 
        int clearAllBurns();

        /* True if any burn is running or still pending. Guidance should use this instead of sniffing the acceleration command. */
        bool isBusy(double currT);

        /* Called by Satellite for Trick to turn on/off thruster depending on schedule */
        /* Also updates thrustAcc_eci */
        int update(double currT);
};

#endif /* THRUSTER_HH */