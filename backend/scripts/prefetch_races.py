#!/usr/bin/env python
"""Populate the FastF1 cache offline for every catalogued race (spec Part 4, Phase 1).

Run this before serving the API — FastF1 must never be called during an HTTP
request (spec Part 10). Also prints each race's ingestion report so a human can
sanity-check cleaning stats and safety-car periods after a cache refresh.

Usage:
    python backend/scripts/prefetch_races.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402


def main() -> None:
    failures: list[str] = []

    for entry in CATALOGUE:
        print(f"\n=== Prefetching {entry.year} {entry.event_name} ===")
        start = time.monotonic()
        try:
            snapshot, report = load_race(entry.year, entry.fastf1_event_identifier)
        except Exception as exc:  # noqa: BLE001 - report and continue with remaining races
            print(f"FAILED to load {entry.race_key}: {exc}")
            failures.append(entry.race_key)
            continue
        elapsed = time.monotonic() - start

        report.print_summary()
        print(f"Loaded in {elapsed:.1f}s. total_laps={snapshot.total_laps}")

    print("\n" + "=" * 70)
    if failures:
        print(f"{len(failures)} race(s) FAILED to load: {', '.join(failures)}")
        sys.exit(1)
    print(f"All {len(CATALOGUE)} catalogue races cached and loaded successfully.")


if __name__ == "__main__":
    main()
