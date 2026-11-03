"""
Simulate the Moxon on FR4 with openEMS (FDTD), including the substrate that NEC2 cannot model.

NEC2 (sim.py) gives the free-space design. On FR4 the Moxon does not simply get shorter: the substrate
also strengthens the coupling across the gap C between the tail tips, so scaling the NEC design down
detunes it (front/back < 10 dB). `--optimize` therefore tunes the board dimensions directly in openEMS:
a common scale factor s for A, B and D, the gap C, and a factor r for the reflector tails D alone
(FR4 may detune driven element and reflector differently), for good match, gain and front/back ratio
over 863-870 MHz. The result is written to moxon-868-dims.json as "board_mm", which layout.py uses.

Same orientation as the footprint: feed at the origin, driven element along x at y=0, reflector at
y=+E; the beam points to -y (phi 270), the back is +y (phi 90).

Speed: by default only the half x >= 0 is simulated, with a PEC wall at x = 0 (exact, the antenna and
its feed are mirror-symmetric; the far field is mirrored by openEMS). --full simulates the whole board
(cross-check). --coarse uses half the mesh density in x and y (for searches; check the result without it).

Run in the openEMS venv (results in $TMPDIR or /tmp):
  ~/.venvs/openems/bin/python sim_fdtd.py             check "board_mm"
  ~/.venvs/openems/bin/python sim_fdtd.py --sweep     grid of s x C x r, N_PARALLEL runs at a time,
                                                      table in moxon-868-fdtd-sweep.csv
  ~/.venvs/openems/bin/python sim_fdtd.py --optimize [s,C,r]  tune on FR4 from (s, C, r), e.g. the sweep's
                                                      best; progress in moxon-868-fdtd-opt.log
  ~/.venvs/openems/bin/python sim_fdtd.py --point s,C,r   one band check of these parameters (no file written)
  ~/.venvs/openems/bin/python sim_fdtd.py --show      look at the model in AppCSXCAD
Options: --coarse, --full; environment N_PARALLEL, THREADS (defaults 2 and 4).
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0, EPS0, Z0

HERE = Path(__file__).resolve().parent
PROJECT = "moxon-868"
DIMS_FILE = HERE / f"{PROJECT}-dims.json"
OPT_LOG = HERE / f"{PROJECT}-fdtd-opt.log"
SWEEP_CSV = HERE / f"{PROJECT}-fdtd-sweep.csv"
SIM_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / f"{PROJECT}-fdtd"

F0, FC = 868e6, 300e6  # Gaussian excitation: centre and 20 dB corner (568 ... 1168 MHz)
SUBSTRATE_H = 1.6  # mm
EPS_R, TAN_D = 4.4, 0.02  # FR4 at ~1 GHz (typical, varies with the maker)
CU_T = 35e-6  # m, 1 oz copper
GAP = 2.0  # mm, feed gap (as in layout.py)
MARGIN_TOP, MARGIN_SIDE, MARGIN_BOTTOM = 4.0, 8.0, 6.0  # mm, substrate beyond the copper (as in layout.py)
AIR = 120.0  # mm, air around the board up to the absorbing boundary (~lambda/3)
F_PATTERN = np.arange(700e6, 951e6, 10e6)  # gain and front/back are calculated at these frequencies
BAND = np.array([863e6, 868e6, 870e6])  # EU868 band edges and centre for the optimisation
SWEEP_S = np.array([0.90, 0.92, 0.94, 0.96])  # scale of A, B, D relative to the NEC design x K_FR4
SWEEP_C = np.array([4.0, 6.0, 8.0, 10.0])  # mm, gap between the tail tips
SWEEP_R = np.array([0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20])  # extra factor on the reflector tails D
N_PARALLEL = int(os.environ.get("N_PARALLEL", "2"))  # sweep: simultaneous runs
THREADS = int(os.environ.get("THREADS", "4"))  # openEMS threads per run

# Model options, set from the command line in main(); passed explicitly to worker processes.
OPTS = {"mesh_div": 1.0, "half": True}  # mesh_div: 2 = twice as fine (convergence check), 0.5 = coarse


def build(dims, w, end_criteria=1e-4, mesh_div=1.0, half=True):
    a2, h, b, d, e = dims["A"] / 2, w / 2, dims["B"], dims["D"], dims["E"]
    fdtd = openEMS(EndCriteria=end_criteria)
    fdtd.SetGaussExcite(F0, FC)
    # [xmin, xmax, ymin, ymax, zmin, zmax]; half model: PEC wall in the symmetry plane x = 0
    fdtd.SetBoundaryCond(["PEC" if half else "PML_8"] + ["PML_8"] * 5)
    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)

    sides = (1,) if half else (-1, 1)
    bx0, bx1 = (0.0 if half else -a2 - h - MARGIN_SIDE), a2 + h + MARGIN_SIDE
    by0, by1 = -h - MARGIN_TOP, e + h + MARGIN_BOTTOM
    kappa = 2 * np.pi * F0 * EPS0 * EPS_R * TAN_D
    fr4 = csx.AddMaterial("FR4", epsilon=EPS_R, kappa=kappa)
    fr4.AddBox([bx0, by0, -SUBSTRATE_H], [bx1, by1, 0])
    cu = csx.AddConductingSheet("copper", conductivity=5.8e7, thickness=CU_T)
    for s in sides:
        cu.AddBox([s * GAP / 2, -h, 0], [s * (a2 + h), h, 0], priority=10)  # driven element half
        cu.AddBox([s * (a2 - h), h, 0], [s * (a2 + h), b, 0], priority=10)  # its tail
        cu.AddBox([s * (a2 - h), e - d, 0], [s * (a2 + h), e + h, 0], priority=10)  # reflector tail
    cu.AddBox([0.0 if half else -a2 - h, e - h, 0], [a2 + h, e + h, 0], priority=10)  # reflector
    # Half model: the port spans only half the gap, so it sees half the voltage at the same current:
    # Z_full = 2 Z_half, and a 25 Ohm port gives the same reflection as 50 Ohm on the full antenna.
    x0 = 0.0 if half else -GAP / 2
    port = fdtd.AddLumpedPort(1, 25 if half else 50, [x0, -h, 0], [GAP / 2, h, 0], "x", 1.0, priority=5)

    res = C0 / (F0 + FC) / 1e-3 / 20 / mesh_div
    xs = [0, GAP / 2, bx1, bx1 + AIR] + ([] if half else [-GAP / 2, bx0, bx0 - AIR])
    for s in sides:
        xs += [s * (a2 - h), s * a2, s * (a2 + h)]
    mesh.AddLine("x", xs)
    mesh.AddLine("y", [-h, 0, h, b, e - d, e - h, e, e + h, by0, by1, by0 - AIR, by1 + AIR])
    nz = 3 * max(1, round(mesh_div))  # cells across the substrate (not coarsened)
    mesh.AddLine("z", list(np.linspace(-SUBSTRATE_H, 0, nz + 1)) + [-AIR, AIR])
    mesh.SmoothMeshLines("x", res / 4, 1.4)
    mesh.SmoothMeshLines("y", res / 4, 1.4)  # tail lengths and the gap C matter here
    mesh.SmoothMeshLines("z", res / 2 * mesh_div / max(1, mesh_div), 1.4)
    nf2ff = fdtd.CreateNF2FFBox()  # mirror at the PEC wall is derived automatically
    return fdtd, csx, port, nf2ff


def simulate(dims, w, f_pattern, end_criteria=1e-4, sim_path=SIM_PATH, threads=0, opts=None):
    """Run openEMS; returns the impedance sweep and gain / front-back ratio at f_pattern."""
    opts = opts or OPTS
    half = opts["half"]
    fdtd, csx, port, nf2ff = build(dims, w, end_criteria, opts["mesh_div"], half)
    fdtd.Run(str(sim_path), cleanup=True, verbose=0, numThreads=threads)
    f = np.linspace(650e6, 1100e6, 901)
    port.CalcPort(str(sim_path), f)
    k = 2 if half else 1  # half model: the full antenna has twice the voltage and accepts twice the power
    z = k * port.uf_tot / port.if_tot
    s11 = abs(port.uf_ref / port.uf_inc)
    p_acc = k * 0.5 * np.real(port.uf_tot * np.conj(port.if_tot))
    # Gain in the board plane, front (phi 270) and back (phi 90): G = 4 pi r^2 |E|^2 / (2 Z0 P_acc)
    ff = nf2ff.CalcNF2FF(str(sim_path), f_pattern, [90], [270, 90], center=[0, 0, 0], verbose=0,
                         read_cached=False)
    gain = []
    for i, fp in enumerate(f_pattern):
        j = np.argmin(abs(f - fp))
        gain.append(10 * np.log10(4 * np.pi * ff.r ** 2 * ff.E_norm[i][0] ** 2 / (2 * Z0) / p_acc[j]))
    gain = np.array(gain)
    return {"f": f, "z": z, "s11": s11, "swr": (1 + s11) / (1 - s11), "f_pattern": np.asarray(f_pattern),
            "gain": gain[:, 0], "fb": gain[:, 0] - gain[:, 1]}


def report(dims, r):
    print(f"\nMoxon A {dims['A']} B {dims['B']} C {dims['C']} D {dims['D']} E {dims['E']} mm "
          f"on {SUBSTRATE_H} mm FR4 (er {EPS_R}), {model_name()}")
    print("  f/MHz   Z/Ohm            SWR   gain/dBi  F/B/dB")
    for fp, g, fb in zip(r["f_pattern"], r["gain"], r["fb"]):
        j = np.argmin(abs(r["f"] - fp))
        mark = " <" if BAND[0] <= fp <= BAND[-1] else ""
        print(f"  {fp / 1e6:6.1f}  {r['z'][j].real:6.1f} {r['z'][j].imag:+7.1f}j  {r['swr'][j]:5.2f}  "
              f"{g:7.2f}  {fb:7.1f}{mark}")


def model_name(opts=None):
    opts = opts or OPTS
    return f"{'half' if opts['half'] else 'full'} model, mesh x{opts['mesh_div']:g}"


def scaled(base, x):
    """Board dimensions for scale s (A, B, D), gap c and reflector-tail factor r (default 1)."""
    s, c = x[0], x[1]
    r = x[2] if len(x) > 2 else 1.0
    dims = {k: round(base[k] * s, 2) for k in "AB"}
    dims["D"] = round(base["D"] * s * r, 2)
    dims["C"] = round(c, 2)
    dims["E"] = round(dims["B"] + dims["C"] + dims["D"], 2)
    return dims


def nec_base(d):
    """The NEC design x K_FR4 (written by sim.py): the reference for the scale factor s."""
    return {k: v * d["k_fr4"] for k, v in d["free_space_mm"].items()}


def band_cost(r):
    """Same goal as sim.py: match over the band, gain at 868 MHz, front/back ratio >= 25 dB."""
    gam = max(r["s11"][np.argmin(abs(r["f"] - fb))] for fb in BAND)
    cost = 30 * gam - r["gain"][1] + 0.3 * max(0.0, 25.0 - min(r["fb"]))
    return cost, (1 + gam) / (1 - gam)


def band_point(base, w, x, opts, threads=THREADS, tag=""):
    """One band check (relaxed end criterion, as for searches); returns a CSV line."""
    dims = scaled(base, x)
    t = time.time()
    r = simulate(dims, w, BAND, end_criteria=1e-3, threads=threads, opts=opts,
                 sim_path=SIM_PATH.with_name(f"{PROJECT}-{tag}{'h' if opts['half'] else 'f'}{opts['mesh_div']:g}-"
                                                 f"s{x[0]:.3f}-c{x[1]:.2f}-r{x[2]:.3f}"))
    cost, swr = band_cost(r)
    return (f"{x[0]:.3f},{x[1]:.2f},{x[2]:.3f},{dims['A']},{dims['D']},{dims['E']},{swr:.2f},"
            f"{r['gain'][1]:.2f},{min(r['fb']):.1f},{cost:.2f},{time.time() - t:.0f}")


CSV_HEAD = "s,C_mm,r,A_mm,D_mm,E_mm,swr_max,gain_868_dbi,fb_min_db,cost,seconds"


def sweep_point(args):
    base, w, x, opts = args
    line = band_point(base, w, x, opts)
    print(line, flush=True)
    return line


def sweep(d):
    from multiprocessing import Pool

    base = nec_base(d)
    jobs = [(base, d["w_trace_mm"], (s, c, r), dict(OPTS)) for s in SWEEP_S for c in SWEEP_C for r in SWEEP_R]
    print(f"{len(jobs)} runs, {N_PARALLEL} parallel x {THREADS} threads, {model_name()}", flush=True)
    with SWEEP_CSV.open("w") as out:
        out.write(f"# {model_name()}\n{CSV_HEAD}\n")
        with Pool(N_PARALLEL) as pool:
            for line in pool.imap_unordered(sweep_point, jobs):
                out.write(line + "\n")
                out.flush()
    rows = [l.split(",") for l in SWEEP_CSV.read_text().splitlines()[2:]]
    best = min(rows, key=lambda r: float(r[9]))
    print(f"\nBest: s {best[0]} C {best[1]} mm r {best[2]} (SWR {best[6]}, {best[7]} dBi, F/B {best[8]} dB)")
    print(f"Next: sim_fdtd.py --optimize {best[0]},{best[1]},{best[2]}")


def optimize(d, start):
    from scipy.optimize import minimize

    base, w = nec_base(d), d["w_trace_mm"]
    log = OPT_LOG.open("w")
    log.write(f"# {model_name()}\n")

    def cost(x):
        dims = scaled(base, x)
        r = simulate(dims, w, BAND, end_criteria=1e-3, threads=THREADS)
        c, swr = band_cost(r)
        line = (f"s {x[0]:.4f} C {x[1]:5.2f} r {x[2]:.4f}  A {dims['A']:6.2f} D {dims['D']:5.2f} "
                f"E {dims['E']:5.2f}  SWR max {swr:4.2f}  gain {r['gain'][1]:5.2f} dBi  "
                f"F/B min {min(r['fb']):5.1f} dB  cost {c:6.2f}")
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()
        return c

    s0, c0, r0 = start
    simplex = [[s0, c0, r0], [s0 - 0.01, c0, r0], [s0, c0 + 1.0, r0], [s0, c0, r0 + 0.04]]
    opt = minimize(cost, [s0, c0, r0], method="Nelder-Mead",
                   options={"initial_simplex": simplex, "xatol": 0.002, "fatol": 0.05, "maxiter": 60})
    dims = scaled(base, opt.x)
    d["board_mm"] = dims
    d["board_source"] = (f"openEMS optimisation ({model_name()}) on {SUBSTRATE_H} mm FR4 er {EPS_R}: "
                         f"NEC design x K_FR4 {d['k_fr4']}, then A, B, D x {opt.x[0]:.4f}, "
                         f"D x {opt.x[2]:.4f} more, C = {opt.x[1]:.2f} mm")
    DIMS_FILE.write_text(json.dumps(d, indent=2) + "\n")
    print(f"\n{opt.message} after {opt.nfev} runs; written to {DIMS_FILE.name}")
    return dims


def parse_x(arg):
    x = [float(v) for v in arg.split(",")]
    return x + [1.0] * (3 - len(x))


def main():
    if "--coarse" in sys.argv:
        OPTS["mesh_div"] = 0.5
    if "--full" in sys.argv:
        OPTS["half"] = False
    d = json.loads(DIMS_FILE.read_text())
    dims, w = d["board_mm"], d["w_trace_mm"]
    if "--show" in sys.argv:
        _, csx, _, _ = build(dims, w, mesh_div=OPTS["mesh_div"], half=OPTS["half"])
        SIM_PATH.mkdir(exist_ok=True)
        csx.Write2XML(str(SIM_PATH / "model.xml"))
        os.system(f"AppCSXCAD {SIM_PATH / 'model.xml'}")
        return
    if "--sweep" in sys.argv:
        return sweep(d)
    if "--point" in sys.argv:
        x = parse_x(sys.argv[sys.argv.index("--point") + 1])
        print(CSV_HEAD + f"   ({model_name()})")
        print(band_point(nec_base(d), w, x, OPTS, tag="pt-"))
        return
    if "--optimize" in sys.argv:
        i = sys.argv.index("--optimize")
        nxt = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("--") else "0.935,7.9"
        dims = optimize(d, parse_x(nxt))
    report(dims, simulate(dims, w, F_PATTERN, threads=THREADS))


if __name__ == "__main__":
    sys.exit(main())
