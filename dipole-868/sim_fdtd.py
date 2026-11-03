"""
Check the printed dipole on FR4 with openEMS (FDTD), including the substrate that NEC2 cannot model.

Simulates the board dimensions from dipole-868-dims.json (copper strips on top of 1.6 mm FR4), finds the
resonance (zero reactance) and prints impedance, SWR and gain over the band. If the resonance is off 868 MHz
it prints the K_FR4 for sim.py that moves it there:  K_new = K_FR4 * f_res / 868.

Run in the openEMS venv:  ~/.venvs/openems/bin/python sim_fdtd.py
(results in /tmp/dipole-868-fdtd, about 1 minute)
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0

HERE = Path(__file__).resolve().parent
PROJECT = "dipole-868"
DIMS_FILE = HERE / f"{PROJECT}-dims.json"
SIM_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / f"{PROJECT}-fdtd"

F0, FC = 868e6, 300e6  # Gaussian excitation: centre and 20 dB corner (568 ... 1168 MHz)
SUBSTRATE_H = 1.6  # mm
EPS_R, TAN_D = 4.4, 0.02  # FR4 at ~1 GHz (typical, varies with the maker)
CU_T = 35e-6  # m, 1 oz copper
GAP = 2.0  # mm, feed gap (as in layout.py)
MARGIN = 4.0  # mm, substrate beyond the copper (as in layout.py)
STRIP_BELOW = 16.0  # mm, board below the dipole's centre line (as in layout.py)
AIR = 120.0  # mm, air around the board up to the absorbing boundary (~lambda/3)
MESH_DIV = 1  # 2 = twice as fine everywhere (convergence check, about 8x the run time)


def build(dims, w):
    l2, h = dims["L"] / 2, w / 2
    fdtd = openEMS(EndCriteria=1e-4)
    fdtd.SetGaussExcite(F0, FC)
    fdtd.SetBoundaryCond(["PML_8"] * 6)
    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)

    # Board: dipole along x at y=0, copper on top (z=0), substrate below
    bx0, bx1, by0, by1 = -l2 - MARGIN, l2 + MARGIN, -h - MARGIN, STRIP_BELOW
    kappa = 2 * np.pi * F0 * EPS0 * EPS_R * TAN_D
    fr4 = csx.AddMaterial("FR4", epsilon=EPS_R, kappa=kappa)
    fr4.AddBox([bx0, by0, -SUBSTRATE_H], [bx1, by1, 0])
    cu = csx.AddConductingSheet("copper", conductivity=5.8e7, thickness=CU_T)
    cu.AddBox([-l2, -h, 0], [-GAP / 2, h, 0], priority=10)
    cu.AddBox([GAP / 2, -h, 0], [l2, h, 0], priority=10)
    port = fdtd.AddLumpedPort(1, 50, [-GAP / 2, -h, 0], [GAP / 2, h, 0], "x", 1.0, priority=5)

    # Mesh: fine on the copper edges and through the substrate, max lambda/20 in air
    res = C0 / (F0 + FC) / 1e-3 / 20 / MESH_DIV
    mesh.AddLine("x", [-l2, -GAP / 2, 0, GAP / 2, l2, bx0, bx1, -l2 - AIR, l2 + AIR])
    mesh.AddLine("y", [-h, 0, h, by0, by1, by0 - AIR, by1 + AIR])
    mesh.AddLine("z", list(np.linspace(-SUBSTRATE_H, 0, 3 * MESH_DIV + 1)) + [-AIR, AIR])
    mesh.SmoothMeshLines("x", res / 4, 1.4)  # dipole length matters most
    mesh.SmoothMeshLines("y", res / 2, 1.4)
    mesh.SmoothMeshLines("z", res / 2, 1.4)
    nf2ff = fdtd.CreateNF2FFBox()
    return fdtd, csx, port, nf2ff


def main():
    d = json.loads(DIMS_FILE.read_text())
    dims, w, k_fr4 = d["board_mm"], d["w_trace_mm"], d["k_fr4"]
    fdtd, csx, port, nf2ff = build(dims, w)
    if "--show" in sys.argv:  # look at the model in AppCSXCAD before the run
        SIM_PATH.mkdir(exist_ok=True)
        csx.Write2XML(str(SIM_PATH / "model.xml"))
        os.system(f"AppCSXCAD {SIM_PATH / 'model.xml'}")
        return
    fdtd.Run(str(SIM_PATH), cleanup=True, verbose=0)

    f = np.linspace(650e6, 1100e6, 901)
    port.CalcPort(str(SIM_PATH), f)
    z = port.uf_tot / port.if_tot
    s11 = port.uf_ref / port.uf_inc
    swr = (1 + abs(s11)) / (1 - abs(s11))
    i = np.where(np.diff(np.sign(z.imag)) > 0)[0]
    f_res = f[i[0]] - z.imag[i[0]] * (f[i[0] + 1] - f[i[0]]) / (z.imag[i[0] + 1] - z.imag[i[0]]) if len(i) else None

    print(f"\nDipole L {dims['L']} mm on {SUBSTRATE_H} mm FR4 (er {EPS_R}), K_FR4 {k_fr4}")
    print("  f/MHz   Z/Ohm            SWR")
    for fm in (850, 863, 868, 870, 890):
        j = np.argmin(abs(f - fm * 1e6))
        print(f"  {fm:6.1f}  {z[j].real:6.1f} {z[j].imag:+7.1f}j  {swr[j]:5.2f}")
    j0 = np.argmin(abs(f - F0))
    # Far field broadside in the board plane (phi 90 / 270), the dipole's maximum
    ff = nf2ff.CalcNF2FF(str(SIM_PATH), F0, [90], [90, 270], center=[0, 0, 0], verbose=0)
    p_acc = 0.5 * np.real(port.uf_tot[j0] * np.conj(port.if_tot[j0]))
    gain = 10 * np.log10(ff.Prad[0] / p_acc * ff.Dmax[0])
    print(f"\nAt 868 MHz: directivity {10 * np.log10(ff.Dmax[0]):.2f} dBi, gain (incl. losses) {gain:.2f} dBi")
    if f_res is None:
        print("No resonance between 650 and 1100 MHz")
        return 1
    print(f"Resonance (X = 0): {f_res / 1e6:.1f} MHz")
    print(f"K_FR4 for sim.py to move it to 868 MHz: {k_fr4 * f_res / F0:.4f}")


if __name__ == "__main__":
    sys.exit(main())
