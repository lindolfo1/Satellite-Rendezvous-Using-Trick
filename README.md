# Satellite-Rendezvous-Using-Trick
A Trick sim of one satellite rendezvousing with another in low Earth orbit.





https://github.com/user-attachments/assets/9619d791-254c-4c13-80cc-baccf9675db1






Both vehicles are in a 500 km circular orbit. The target coasts while the chaser
starts about a kilometer away at a random point at most 45 degrees from the back
of the target, and has to park 20 m behind the target satellite by stopping at
different waypoints behind the target.

## How the chaser works

It has 4 sensors:

1. Rangefinder: measures range, azimuth and elevation to the target once a
   second, in the chaser's own body frame.
2. IMU: samples 10 times a second. It reports how far the chaser rotated since
   the last sample, and the acceleration it felt with gravity taken out.
3. Suntracker: measures the direction to the sun.
4. Magnetometer: measures the direction of the Earth's magnetic field.

The last two are one class. Neither direction alone pins down an attitude, but the pair are solved together with TRIAD and comes out as a single measured quaternion plus a covariance saying which axis it trusts least.

---



Everything starts from the initial position and velocity of both satellites. The
chaser knows where it is, and it is handed a copy of the target's state, so it
can work out the relative position and velocity to start its filter from. From
then on it is on its own with the sensors.

Two **Kalman filters** run off those measurements.

1. The first one tracks attitude. It is a 6-state MEKF holding attitude error and
   gyro bias. Ten times a second it takes the IMU's rotation and updates the estimate, which drifts a little each time because the gyro has a bias. Once a second
   the sun and magnetometer measurement comes in and corrects the estimate, and part of that correction goes into the bias estimate, so the drift between updates
   gets smaller as the run goes on.

2. The second one tracks the target. It is a 6-state EKF holding the relative
   position and velocity in the target's LVLH frame. Ten times a second it coasts
   that state forward with the Clohessy-Wiltshire equations and adds in whatever the
   thruster is doing. Once a second the rangefinder reading arrives, and the filter
   compares it against the range, azimuth and elevation it expected to see. NOTE: the rangefinder's az and el are in its own body frame, so to figure out its position  elative to LVLH, it needs the attitude estimate from the 1st kalman filter. 

**Guidance** runs every 5 seconds off the relative estimate. It gives the filter the first 30 seconds to settle, then starts working.

Its target is a waypoint point directly behind the target satellite, at whichever waypoint
range it is currently on. It checks whether it is already there: inside 1% of the waypoint range in position, and slow enough relative to the target. If it is, the waypoint is done.

If it is not, it plans a transfer. It sweeps a few orbits' worth of transfer
times, and for each one solves the two-burn CW problem for the delta-v that would
put it on the waypoint at that time. Slow transfers are cheap but waste time and
fast ones cost fuel, so it scores each candidate on both and takes the best. It
also throws out any candidate where the burn would take more than 5% of the
transfer time, because the CW solution assumes the burn is instant and that stops
being true for long ones.

That delta-v goes to the thruster, which then calculates a burn duration based on the mass and the thrust force, queues it, and fires. Guidance does not command thrust directly; it just adds burns to the queue.

Guidance also writes down when the transfer was supposed to finish. When that
time comes around it checks the tolerance again. If the chaser is off, which it
usually is a little, since it was steering off an estimate and the burn was not
really instant, guidance plans another transfer to the same waypoint and queues
another burn. That repeats until the chaser is inside tolerance, at which point it
moves to the next waypoint and the whole cycle starts over at 250, then 50, then
20 m.

Under all of this is the truth simulation the chaser never sees: two-body gravity
with J2, integrated with RK4, plus whatever the thruster is firing.

## Layout

The C++ is in `satellite/`, one class per file. `rangefinder`, `imu` and
`attitude_sensor` make measurements. `relative_nav` and `attitude_nav` are the
two filters. `guidance` decides, `thruster` acts. `satellite` holds the truth
state and calls everything. `target_ephemeris` is what the chaser thinks it knows
about the target. `orbit_util` and `misc_util` have the frame conversions, the CW
matrix and the noise generator.

`S_define` builds the two vehicles and sets the rates: 0.1 s for the IMU and the
filter time update, 1 s for the sensors, 5 s for guidance, 0.005 s for
integration.

`input.py` runs between the defaults and initialization. It sets the orbit, picks
the integrator, disperses the chaser with `randomize_chaser_position` from
`orbit_utils.py`, and stops after three orbits. Sensor noise is on unless you
uncomment the block near the top.

## Getting started

You need Trick, Eigen 3 and Python 3. Trick is Linux and macOS only, so this
does not run natively on Windows.

Eigen on Ubuntu is `sudo apt install libeigen3-dev`. Trick has its own install
guide; once it is done, `trick-CP` should be on your PATH.

Keep `SIM_rendezvous/` and `models/` next to each other. `S_overrides.mk` adds
`../models` to the include path, so moving either one breaks the build.

The runner script sources a virtualenv one level above the repo, so make that
first:

```
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r visualizer/requirements.txt
```

If you keep your venv somewhere else, change `VENV_ACTIVATE` at the top of
`run_sim.sh`.

Then run everything:

```
./run_sim.sh
```

It compiles with `trick-CP` if there is no executable yet, runs the sim against
`RUN_test/input.py`, fixes the unit labels in the CSV, stamps both output files
with a timestamped name and drops them in `visualizer/runs/`. Compiling takes a
few minutes the first time and is skipped after that. Delete
`SIM_rendezvous/S_main_Linux*.exe` if you change the C++ and want a rebuild.

To do it by hand instead:

```
cd SIM_rendezvous
trick-CP
./S_main_Linux_*.exe RUN_test/input.py
```

That leaves `log_states.csv` and `run_metadata.json` in `RUN_test/`. Rename them
to a matching pair, like `my_run.csv` and `my_run.json`, and move them into
`visualizer/runs/`. The viewer finds runs by matching stems, so the two names
have to agree.

To look at a run:

```
cd visualizer
streamlit run app.py
```

Pick the run from the sidebar. The `visualizer/` README covers the viewer
itself, including publishing runs to GitHub Pages.


## Limitations

Attitude and pointing:

- Both satellites always point perfectly along LVLH, with body x pointing away
  from the Earth, y along velocity and z on the orbit normal. Nothing steers
  them and nothing disturbs them. 

Orbits:

- Everything relative is Clohessy-Wiltshire, so this only holds for a
  near-circular target orbit, close range and roughly the same plane.
- `input.py` runs equatorial, which is the worst case for the attitude sensor.
  The sun and field directions stay 90 degrees apart the whole run, so the weak
  axis of the attitude covariance never gets tested.

Sensors:

- The sun sensor and magnetometer are one merged sensor that spits out a
  quaternion. The sun is nailed to ECI +x and never goes behind the Earth, which
  it should for about 35 minutes an orbit, so attitude drift here looks better
  than it would in flight. The magnetic field is an untilted dipole, which is
  aligned with the geometric poles for simplicity. The sensor and the filter use
  the same two models, so there is no model error at all.
- The rangefinder is always aimed at the target and always returns a good
  reading. No field of view, no max or min range, no dropouts. There is also no
  latency.

Navigation and thrust:

- The filter gets the commanded thrust acceleration.
- The thruster snaps on and off, always points exactly where commanded, and never
  runs out.

Scenario:

- No keep-out zones. Guidance scores transfers on delta-v and time and never
  looks at the path in between, so a burn can send the chaser straight through
  the target's neighborhood.
- The target never maneuvers.
- It stops at 20 m and has no final approach, docking, contact dynamics, or
  collision check.

## Requires

Trick and Eigen 3.
