# Status moxon-868 (2026-11-03)

**Ready to etch or order.** The layout uses the dimensions tuned in openEMS on 1.6 mm FR4
(`board_mm` in `moxon-868-dims.json`). Next step: build it and compare with `../dipole-868` by RSSI
(see README, "Testing without a VNA").

Decision 2026-11-03: the printed version is accepted with a front/back ratio of ~13-14 dB instead of the
original goal of >= 20 dB (see below why it does not get further). Fallback if more is needed: Moxon from
2 mm copper wire on a plastic frame, NEC is then directly valid (6 dBi, F/B > 25 dB).

## Result

A 98.1, B 12.33, C 12.18, D 20.56, E 45.07 mm; copper strips 3 mm; board 117.1 x 58.1 mm, DRC clean.
openEMS, half model, end criterion 1e-4:

| f / MHz | Z / Ohm | SWR | Gain / dBi | F/B / dB |
|---|---|---|---|---|
| 850 | 33.7 - 13.6j | 1.67 | 5.36 | 11.1 |
| 860 | 44.3 - 5.2j | 1.18 | 5.34 | 13.1 |
| 870 | 56.4 - 0.1j | 1.13 | 5.24 | 14.4 |
| 880 | 67.6 + 0.8j | 1.35 | 5.06 | 14.5 |
| 900 | 80.7 - 1.7j | 1.62 | 4.75 | 12.9 |

Band 863-870 MHz (search runs, end criterion 1e-3): SWR max 1.11, 5.30 dBi at 868 MHz, F/B min 13.5 dB.
Final check with the full model (`--full`): same SWR and F/B, gain +0.03 dB.

## How it was found

1. NEC2 free-space design (`sim.py`): A 123.3, B 15.5, C 7.1, D 23.6 mm -> 6.0 dBi, F/B > 25 dB.
2. Scaling it by `K_FR4 = 0.86` (right for the dipole) detunes the Moxon on FR4: 4.0 dBi, F/B 7 dB,
   SWR 2.6. The substrate also changes the coupling between the elements, not only their length.
3. `sim_fdtd.py` parameters: s (A, B, D relative to NEC x 0.86), gap C, and r (extra factor on the
   reflector tails D only).
4. Sweep s 0.90-0.96 x C 4-10 mm x r 0.90-1.20, 112 points (`moxon-868-fdtd-sweep.csv`): best
   s 0.92, C 10, r 1.10 -> SWR 1.23, 5.15 dBi, F/B 12.1 dB. Longer reflector and larger C help the match a lot;
   F/B stayed <= 12 dB on the whole grid.
5. Nelder-Mead from there, 90 runs (`moxon-868-fdtd-opt.log`): s 0.9253, C 12.18, r 1.0935.

Why F/B stops at ~14.5 dB: the optimiser already put the F/B maximum into the band, and it is only
14.5 dB at any frequency. Most likely the FR4 (losses, and its loading of the reflector) keeps the reflector
current from cancelling the driven element's field completely. A thicker or low-loss substrate, or
air (wire Moxon), would be needed for more.

## Simulation model

* Half model by default: PEC wall at x = 0 (exact, the antenna is mirror-symmetric); openEMS mirrors the
  far field. Checked against the full model at s 0.935, C 7.89: SWR 1.80 / 1.80, gain 5.01 / 5.06 dBi,
  F/B 10.9 / 10.9 dB. Run time 23 s instead of ~5 min (4 threads).
* `--coarse` (half mesh density in x, y): 14 s, but F/B ~1.5 dB off - not used.
* openEMS built from source (openEMS-Project), Python venv `~/.venvs/openems`. The sweep ran with
  2 parallel runs x 4 threads on a 16-core machine (~30 min for 112 points).

## Decisions

* 2026-10-19: build both DIY antennas, this Moxon and `../dipole-868`. Moxon over a PCB Yagi (2-el: same gain,
  worse F/B, wider, needs matching; 3-el: ~2 dB more but ~3x the area) and over fractal antennas (no gain).
* Optional third comparison antenna to buy: Linx ANT-868-CW-HW-SMA (honest 0 dBi half-wave, no ground
  plane needed). Avoid stubby / helical SMA antennas without 868 MHz data.
* 2026-11-03: printed version with F/B ~13-14 dB accepted (see above).
