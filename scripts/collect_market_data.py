"""Collect market data into CSVs for Phase 2.

This is a lightweight wrapper around the project ingest modules.
"""
from __future__ import annotations

import argparse

from bsp.ingest.benchmarks import collect_benchmarks
from bsp.ingest.constituents import collect_constituents
from bsp.ingest.fpi import collect_fpi
from bsp.ingest.macro import collect_macro
from bsp.ingest.prices import collect_prices

COMMANDS = {
    "prices": collect_prices,
    "indices": collect_benchmarks,
    "constituents": collect_constituents,
    "macro": collect_macro,
    "fpi": collect_fpi,
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*COMMANDS, "all"])
    args = parser.parse_args()
    for name in (COMMANDS if args.command == "all" else [args.command]):
        COMMANDS[name]()
