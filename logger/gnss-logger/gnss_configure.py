#!/usr/bin/env python3
"""
Configure the F9P for raw output and verify it works.

Run this ONCE after wiring up the receiver (and after dealing with ModemManager
-- see README). It:
  1. enables UBX-RXM-RAWX and UBX-NAV-SAT on USB at 1 Hz, saved to flash so it
     survives power cycles;
  2. listens for ~15 seconds and reports how many raw epochs and satellite-info
     messages arrived, plus a sample TEC value -- proof the pipeline works before
     you start the full logger.
"""

import argparse
import sys
import time
from serial import Serial
from pyubx2 import UBXReader, UBX_PROTOCOL

import gnss_logger as G


def main():
    p = argparse.ArgumentParser(description="Configure + verify F9P raw output.")
    p.add_argument("--port", default="/dev/ttyACM0")
    p.add_argument("--baud", type=int, default=38400)
    p.add_argument("--seconds", type=int, default=15)
    args = p.parse_args()

    stream = Serial(args.port, args.baud, timeout=3)
    print(f"Enabling RXM-RAWX + NAV-SAT (saved to flash) on {args.port} ...")
    G.configure_receiver(stream, persist=True)

    ubr = UBXReader(stream, protfilter=UBX_PROTOCOL)
    n_rawx = n_navsat = 0
    nav = {}
    sample_printed = False
    t_end = time.time() + args.seconds
    print(f"Listening {args.seconds}s for raw data...\n")

    while time.time() < t_end:
        try:
            _raw, parsed = ubr.read()
        except Exception:
            continue
        if parsed is None:
            continue
        if parsed.identity == "NAV-SAT":
            n_navsat += 1
            nav = G.process_navsat(parsed)
        elif parsed.identity == "RXM-RAWX":
            n_rawx += 1
            rows, nmeas = G.process_rawx(parsed, nav, {}, "now")
            if rows and not sample_printed:
                r = rows[0]
                print(f"  sample: SV{r[3]}  elev={r[4]}  "
                      f"code_TEC={r[6]:.2f} TECU  ({len(rows)} GPS L1/L2 pairs this epoch)")
                sample_printed = True

    stream.close()
    print(f"\nRXM-RAWX epochs received: {n_rawx}")
    print(f"NAV-SAT messages received: {n_navsat}")
    if n_rawx == 0:
        print("\n\u26a0  No raw epochs. Check: ModemManager disabled? antenna sky view? "
              "correct port (/dev/ttyACM0)?")
        sys.exit(1)
    if not sample_printed:
        print("\n\u26a0  Raw epochs arriving but no GPS L1/L2 pairs yet -- the receiver "
              "may still be acquiring L2C. Give it a few minutes of open sky and retry.")
    else:
        print("\n\u2705 Raw dual-frequency data confirmed. Ready to run the logger.")


if __name__ == "__main__":
    main()
