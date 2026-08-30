/*************************************************************************
PURPOSE: Guidance calculates burns to go to the next waypoint 
**************************************************************************/

#ifndef GUIDANCE_HH
#define GUIDANCE_HH

/*========================================================================
 * Guidance 
 *=======================================================================*/
class Guidance {
    public:
        double waypointRange[4];    /* (m)      approach waypoints */
        int    numWaypoints;        /* (--)     number of waypoints to be used */
        int    currentWaypoint;     /* (--)     current waypoint */
        double dVAccumulated;       /* (m/s)    total dV used so far */
        double wayptTfinal;         /* (s)      the timestamp for arriving at a current waypoint */
        double burnEndTime;         /* (s)      timestamp for the burn end */
        double retryInterval;       /* (s)      time interval on to which retry correction burn */
        double tolerance;           /* (--)     tolerance for each waypoint err (0-1) */

        Guidance();
        int default_data();

        /* Trick jobs called by Satellite */
        /* pos and vel should be in LVLH frame */
        int guide(double currPos[3], double currVel[3], double currT, double n, double accelMag, bool isThrusterBusy, double dVel[3]);
};


#endif /* GUIDANCE_HH */