import csv
import os

# xHat is [x, y, z, vx, vy, vz] in the relative (chaser-target) frame
xhat_units = ["m", "m", "m", "m/s", "m/s", "m/s"]

# qHat is a unit quaternion [q0, q1, q2, q3] -- always dimensionless
qhat_units = ["--", "--", "--", "--"]

def relabel_units():
    """Post-process the recorded CSV to fix xHat[i] and qHat[i] unit labels
    explicitly, rather than relying on whatever unit the sim happened to write."""
    units_map = {}
    units_map.update({f"chaser.sat.relNav.xHat[{i}]": xhat_units[i] for i in range(6)})
    units_map.update({f"chaser.sat.attNav.qHat[{i}]": qhat_units[i] for i in range(4)})

    infile = "../RUN_test/log_states.csv"
    if not os.path.exists(infile):
        print(f"ERROR: {infile} not found -- run the sim first.")
        return

    with open(infile, "r") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    new_header = []
    for col in header:
        name = col.split(" {")[0]
        existing_unit = col.split("{")[1].rstrip("}") if "{" in col else "--"
        unit = units_map.get(name, existing_unit)
        new_header.append(f"{name} {{{unit}}}")

    with open(infile, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(new_header)
        writer.writerows(rows)


if __name__ == "__main__":
    relabel_units()