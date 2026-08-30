# pyright: reportUndefinedVariable=false

global DR_states
DR_states = trick.DRAscii("states")
DR_states.set_freq(trick.DR_Always)
DR_states.set_cycle(1.0)
DR_states.set_single_prec_only(False)

for v in ["target", "chaser"]:
    for i in range(3):
        DR_states.add_variable("%s.sat.pos_eci[%d]" % (v, i))
        DR_states.add_variable("%s.sat.vel_eci[%d]" % (v, i))

for i in range(4):
    DR_states.add_variable("chaser.sat.attNav.qHat[%d]" % i)

for i in range(3):
    DR_states.add_variable("chaser.sat.thruster.thrustAcc_eci[%d]" % i)
    DR_states.add_variable("chaser.sat.imu.dVel[%d]" % i)

DR_states.add_variable("chaser.sat.thruster.dVAccumulated")
DR_states.add_variable("chaser.sat.guidance.currentWaypoint")
DR_states.add_variable("chaser.sat.imu.isValid")
DR_states.add_variable("chaser.sat.rangefinder.range")
DR_states.add_variable("chaser.sat.rangefinder.azimuth")
DR_states.add_variable("chaser.sat.rangefinder.elevation")
DR_states.add_variable("chaser.sat.rangefinder.isValid")

for i in range(6):
    DR_states.add_variable(f"chaser.sat.relNav.xHat[{i}]")

trick.add_data_record_group(DR_states, trick.DR_Buffer)