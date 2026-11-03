"""
Simulate the printed half-wave dipole for 868 MHz with NEC2 (nec2c), write the length for layout.py.

The dipole is the reference antenna (2.15 dBi by definition): the Moxon and bought antennas are compared
against it with RSSI measurements. Its length is chosen for zero reactance at F0; the input resistance is
then about 70 Ohm (SWR ~1.4 at 50 Ohm, 0.2 dB mismatch loss), left that way to keep the reference simple.

The copper strip (width W_TRACE) is modelled as a round wire with the equivalent radius W/4, the FR4
shortening K_FR4 comes from the openEMS simulation with the substrate (sim_fdtd.py).

Run with the system Python (scipy) and nec2c on the PATH:  /usr/bin/python3 sim.py
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scipy.optimize import brentq

HERE = Path(__file__).resolve().parent
PROJECT = "dipole-868"
DIMS_FILE = HERE / f"{PROJECT}-dims.json"

F0 = 868.0  # MHz
W_TRACE = 3.0  # mm
K_FR4 = 0.86  # FR4 shortening from the openEMS check (sim_fdtd.py)
SEG_MM = 4.0
COPPER = 5.8e7  # S/m


def deck(length_mm, freqs):
    """Dipole along x, feed on the middle segment; RP in the board plane (phi 90 = broadside)."""
    n = round(length_mm / SEG_MM) | 1
    x, r = length_mm / 2000, W_TRACE / 4000
    lines = ["CM Dipole 868 MHz", "CE", f"GW 1 {n} {-x:.6f} 0 0 {x:.6f} 0 0 {r:.6f}", "GE 0",
             f"LD 5 0 0 0 {COPPER:.3e}", f"EX 0 1 {n // 2 + 1} 0 1 0"]
    for f in freqs:
        lines += [f"FR 0 1 0 0 {f:.3f} 0", "RP 0 1 1 1000 90 90 0 0"]
    lines.append("EN")
    return "\n".join(lines) + "\n"


def evaluate(length_mm, freqs):
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = Path(tmp) / "in.nec", Path(tmp) / "out.txt"
        inp.write_text(deck(length_mm, freqs))
        subprocess.run(["nec2c", f"-i{inp}", f"-o{out}"], check=True, capture_output=True)
        text = out.read_text()
    res = []
    for block in text.split("ANTENNA INPUT PARAMETERS")[1:]:
        row = block.splitlines()[3].split()
        gain = float(re.search(r"^\s+90\.00\s+\S+\s+\S+\s+\S+\s+(\S+)", block, re.M).group(1))
        res.append((complex(float(row[6]), float(row[7])), gain))
    return res


def swr(z, z0=50.0):
    g = abs((z - z0) / (z + z0))
    return (1 + g) / (1 - g)


def main():
    length = brentq(lambda l: evaluate(l, [F0])[0][0].imag, 140.0, 180.0, xtol=0.05)
    print(f"Resonant length {length:.1f} mm (free space)")
    freqs = [850 + 5 * i for i in range(9)]
    print("\n  f/MHz   Z/Ohm            SWR   gain/dBi")
    for f, (z, g) in zip(freqs, evaluate(length, freqs)):
        print(f"  {f:6.1f}  {z.real:6.1f} {z.imag:+7.1f}j  {swr(z):5.2f}  {g:6.2f}")
    z, g = evaluate(length, [F0])[0]
    phys = round(length * K_FR4, 2)
    DIMS_FILE.write_text(json.dumps({
        "f0_mhz": F0, "k_fr4": K_FR4, "w_trace_mm": W_TRACE,
        "free_space_mm": {"L": round(length, 2)}, "board_mm": {"L": phys},
        "nec_at_f0": {"z_ohm": [round(z.real, 1), round(z.imag, 1)], "gain_dbi": round(g, 2)},
    }, indent=2) + "\n")
    print(f"\nOn FR4 (x {K_FR4}): L {phys:.1f} mm")
    print("Written:", DIMS_FILE.name)


if __name__ == "__main__":
    sys.exit(main())
