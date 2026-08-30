#############################################################################
# LAYER 2 -- the input file.
#
# Runs AFTER default_data, BEFORE initialize().
# This is where the two vehicles become different from each other, and
# where Monte Carlo dispersions are applied. Nothing here needs a rebuild.
#############################################################################

# pyright: reportUndefinedVariable=false

import math

# orbital-mechanics helpers (coe_to_eci, eci_to_coe, randomize_chaser_position)
exec(open("orbit_utils.py").read())


#############################################################################
# constants
#############################################################################
MU_EARTH = 3.986004418e14      # earth gravitational parameter [m^3/s^2]
R_EARTH  = 6.378137e6           # earth radius [m]
ALT      = 500.0e3              # orbit altitude [m]
SMA      = R_EARTH + ALT        # semi-major axis [m]
CHASER_DISPERSION_RADIUS = 1000.0   # chaser random placement radius [m]


#############################################################################
# integrators
#############################################################################
chaser_integloop.getIntegrator(trick.Runge_Kutta_4, 6)
target_integloop.getIntegrator(trick.Runge_Kutta_4, 6)


#############################################################################
################ IMPORTANT!!!! REMOVE FOR PRODUCTION ########################
#############################################################################
# dont add noise to sensor data
# chaser.sat.rangefinder.addNoise = False
# chaser.sat.imu.addNoise = False
# chaser.sat.attSensor.addNoise = False
#############################################################################


#############################################################################
# orbit setup
#############################################################################
target.sat.sma = SMA
target.sat.ecc = 0.0
target.sat.inc = 0.0
target.sat.trueAnom = 0.0

# Randomly place the chaser CHASER_DISPERSION_RADIUS from the target, within
# 45 degrees of directly behind it (trailing, anti-along-track direction),
# with the CW no-drift velocity so relative motion is bounded (a closed
# periodic orbit about the target) instead of drifting.
chaser_offset = randomize_chaser_position(
    target, chaser, mu=MU_EARTH, radius_m=CHASER_DISPERSION_RADIUS,
    max_angle_from_behind_deg=45.0,
)

# perturbations
target.sat.j2Enabled = False
chaser.sat.j2Enabled = False


#############################################################################
# data recording
#############################################################################
exec(open("Modified_data/record_states.py").read())
exec(open("Modified_data/record_metadata.py").read())


#############################################################################
# run for three orbits
#############################################################################
period = 2.0 * math.pi * math.sqrt(SMA ** 3 / MU_EARTH)
trick.stop(3.0 * period)