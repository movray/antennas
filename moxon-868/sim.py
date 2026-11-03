"""
Simulate and optimise the Moxon rectangle for 868 MHz with NEC2 (nec2c), write the dimensions for layout.py.

Geometry (top view, the beam points to +y = "front"):

        <------------- A ------------->
        +-----------------------------+   driven element, feed in the middle
        |              ^              |   tails B
        |  B           |              |
                       |  E = B + C + D
        |  C (gap)     |              |
        |  D           v              |   tails D
        +-----------------------------+   reflector

The copper strips (width W_TRACE) are modelled as round wires with the equivalent radius W/4.
NEC2 knows no dielectric: the FR4 under the strips makes the antenna electrically longer.
The design is optimised in free space and then shrunk by K_FR4 (see below).

Run with the system Python (scipy) and nec2c on the PATH:  /usr/bin/python3 sim.py
"""

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
PROJECT = "moxon-868"
DIMS_FILE = HERE / f"{PROJECT}-dims.json"

F0 = 868.0  # MHz, middle of the EU868 LoRa channels
BAND = (863.0, 870.0)  # MHz, EU868 SRD band used by LoRaWAN
W_TRACE = 3.0  # mm, copper strip width
# Shortening by the FR4 under one-sided strips (1.6 mm, er 4.4), from the openEMS check (sim_fdtd.py):
# the dipole on FR4 resonates 12 % lower than in free space. sim_fdtd.py prints a corrected value.
K_FR4 = 0.86
SEG_MM = 4.0  # NEC segment length (lambda/86)
COPPER = 5.8e7  # S/m


def lam_mm(f_mhz):
    return 299792.458 / f_mhz


def cebik_start(f_mhz, d_mm):
    """Moxon dimensions from L. B. Cebik's regression for wire diameter d (all in wavelengths)."""
    lam = lam_mm(f_mhz)
    d1 = math.log10(d_mm / lam)
    a = -0.0008571428571 * d1 ** 2 - 0.009571428571 * d1 + 0.3398571429
    b = -0.002142857143 * d1 ** 2 - 0.02035714286 * d1 + 0.008285714286
    c = 0.001809523381 * d1 ** 2 + 0.01780952381 * d1 + 0.05164285714
    d = 0.001 * d1 + 0.07178571429
    return [v * lam for v in (a, b, c, d)]


def nsegs(length_mm, odd=False):
    n = max(1, round(length_mm / SEG_MM))
    if odd and n % 2 == 0:
        n += 1
    return n


def deck(dims, freqs):
    """NEC2 input: driven element at y=0, reflector at y=-E, everything in metres."""
    a, b, c, d = dims
    e = b + c + d
    r = W_TRACE / 4 / 1000
    x, yb, yr, yd = a / 2000, -b / 1000, -e / 1000, (-e + d) / 1000
    nd = nsegs(a, odd=True)
    wires = [
        (1, nd, (-x, 0), (x, 0)),  # driven, feed on the middle segment
        (2, nsegs(b), (-x, 0), (-x, yb)),
        (3, nsegs(b), (x, 0), (x, yb)),
        (4, nsegs(a), (-x, yr), (x, yr)),  # reflector
        (5, nsegs(d), (-x, yr), (-x, yd)),
        (6, nsegs(d), (x, yr), (x, yd)),
    ]
    lines = ["CM Moxon 868 MHz", "CE"]
    for tag, n, (x0, y0), (x1, y1) in wires:
        lines.append(f"GW {tag} {n} {x0:.6f} {y0:.6f} 0 {x1:.6f} {y1:.6f} 0 {r:.6f}")
    lines += ["GE 0", f"LD 5 0 0 0 {COPPER:.3e}", f"EX 0 1 {nd // 2 + 1} 0 1 0"]
    for f in freqs:
        # Gain in the board plane: phi 90 = front (+y), phi 270 = back
        lines += [f"FR 0 1 0 0 {f:.3f} 0", "RP 0 1 2 1000 90 90 0 180"]
    lines.append("EN")
    return "\n".join(lines) + "\n"


def run_nec(text):
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = Path(tmp) / "in.nec", Path(tmp) / "out.txt"
        inp.write_text(text)
        subprocess.run(["nec2c", f"-i{inp}", f"-o{out}"], check=True, capture_output=True)
        return out.read_text()


def parse(out):
    """Per frequency: (Z, gain front dBi, gain back dBi)."""
    res = []
    for block in out.split("ANTENNA INPUT PARAMETERS")[1:]:
        row = block.splitlines()[3].split()
        z = complex(float(row[6]), float(row[7]))
        gains = [float(m) for m in re.findall(r"^\s+90\.00\s+\S+\s+\S+\s+\S+\s+(\S+)", block, re.M)[:2]]
        res.append((z, gains[0], gains[1]))
    return res


def evaluate(dims, freqs):
    return parse(run_nec(deck(dims, freqs)))


def gamma(z, z0=50.0):
    return abs((z - z0) / (z + z0))


def swr(z):
    g = gamma(z)
    return (1 + g) / (1 - g)


def cost(dims):
    if min(dims) <= 1.0:
        return 1e6
    freqs = (BAND[0], F0, BAND[1])
    res = evaluate(dims, freqs)
    worst_gamma = max(gamma(z) for z, _, _ in res)
    worst_fb = min(gf - gb for _, gf, gb in res)
    g0 = res[1][1]
    return 30 * worst_gamma - g0 + 0.3 * max(0.0, 25.0 - worst_fb)


def main():
    start = cebik_start(F0, W_TRACE / 2)  # strip W ~ wire of diameter W/2
    opt = minimize(cost, start, method="Nelder-Mead", options={"xatol": 0.05, "fatol": 1e-3, "maxiter": 600})
    a, b, c, d = opt.x
    print(f"Cebik start    A {start[0]:.1f}  B {start[1]:.1f}  C {start[2]:.1f}  D {start[3]:.1f} mm")
    print(f"NEC optimised  A {a:.1f}  B {b:.1f}  C {c:.1f}  D {d:.1f}  E {b + c + d:.1f} mm (free space)")

    freqs = [850 + 2.5 * i for i in range(17)]
    print("\n  f/MHz   Z/Ohm            SWR   front/dBi  F/B/dB")
    for f, (z, gf, gb) in zip(freqs, evaluate(opt.x, freqs)):
        mark = " <" if BAND[0] <= f <= BAND[1] else ""
        print(f"  {f:6.1f}  {z.real:6.1f} {z.imag:+7.1f}j  {swr(z):5.2f}  {gf:7.2f}  {gf - gb:7.1f}{mark}")

    phys = {k: round(v * K_FR4, 2) for k, v in zip("ABCD", opt.x)}
    phys["E"] = round(phys["B"] + phys["C"] + phys["D"], 2)
    z, gf, gb = evaluate(opt.x, [F0])[0]
    DIMS_FILE.write_text(json.dumps({
        "f0_mhz": F0, "k_fr4": K_FR4, "w_trace_mm": W_TRACE,
        "free_space_mm": {k: round(v, 2) for k, v in zip("ABCD", opt.x)},
        "board_mm": phys,
        "nec_at_f0": {"z_ohm": [round(z.real, 1), round(z.imag, 1)], "gain_dbi": round(gf, 2),
                      "front_back_db": round(gf - gb, 1)},
    }, indent=2) + "\n")
    print(f"\nOn FR4 (x {K_FR4}): " + "  ".join(f"{k} {v:.1f}" for k, v in phys.items()) + " mm")
    print("Written:", DIMS_FILE.name)


if __name__ == "__main__":
    sys.exit(main())
