# pyright: reportUndefinedVariable=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false

# Writes a one-time JSON sidecar (UTC start time, static waypoint table)
# into RUN_<name>/data_output/. Not a DR group: this is one-shot metadata,
# not a periodic time series, so it does not belong in the .trk output.

import json
import os
import datetime

output_dir = "RUN_test"

try:
    os.makedirs(output_dir, exist_ok=True)

    try:
        utc_start = datetime.datetime.now(datetime.UTC).isoformat()
    except AttributeError:
        utc_start = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Trick's SWIG bindings expose a fixed-size C array as a proxy object.
    # Iterating it works, but the elements are swig_double, not plain
    # Python float -- json.dump rejects those unless explicitly converted.
    raw_waypoints = chaser.sat.guidance.waypointRange

    try:
        waypoint_range = [float(x) for x in raw_waypoints]
    except TypeError:
        # Nested structure (array of vectors) -- flatten one level deeper.
        waypoint_range = [[float(c) for c in row] for row in raw_waypoints]

    # Scalars come back as swig_double too, so cast for the same reason.
    tolerance = float(chaser.sat.guidance.tolerance)

    metadata = {
        "utc_start_time": utc_start,
        "waypoint_range": waypoint_range,
        "tolerance": tolerance,
    }

    out_path = os.path.join(output_dir, "run_metadata.json")
    with open(out_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # cwd confirms where Trick actually thinks "here" is, since a file
    # written to a relative path only lands where you expect if this
    # matches the RUN_ directory you launched from.
    print("record_metadata.py: wrote %s (cwd=%s)" % (os.path.abspath(out_path), os.getcwd()))

except Exception as e:
    # Re-raised after printing, so the failure is loud and visible in the
    # console rather than silently truncating the rest of input.py.
    print("record_metadata.py FAILED: %r" % (e,))
    raise