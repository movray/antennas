# Status dipole-868 (2026-10-19)

**Done and checked with openEMS** - can be etched or ordered.

* Length 139.0 mm on 1.6 mm FR4 (`K_FR4 = 0.86`), board 147 x 22 mm.
* openEMS: resonance 868.7 MHz, Z = 61 Ohm, SWR 1.21 at 868 MHz (< 1.3 over 850-870 MHz), 1.96 dBi.
* Layout, DRC (0 errors), ERC (0), etching masks are up to date.

Open:

* Real measurement: RSSI comparison with two LoRa modules (dipole as reference for the Moxon and the bought
  antenna), see `../moxon-868/README.md`. Which LoRa modules / microcontrollers are used is not decided yet.
* The er of the FR4 actually used (home etching boards / JLCPCB ~4.5) can move the resonance by about +-2 %;
  only a measurement shows it.

Decision 2026-10-19: this dipole is built together with the Moxon; it is the reference for the RSSI tests.
