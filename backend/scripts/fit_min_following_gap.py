#!/usr/bin/env python
"""Fit `position.MIN_FOLLOWING_GAP_S` from observed real gaps instead of
declaring it as a placeholder.

This constant is load-bearing for product output: whenever a counterfactual
succeeds in bringing a car into contention, the clamp pins the gap here, so
this value *is* the margin the tool reports. It spent several passes as a
0.3s placeholder whose only empirical support was a 9-sample bucket with a
0.335s standard error — indefensible for a number that shows up in the UI.

Operational definition used: the 5th percentile of observed real
`gap_to_ahead_s` across the catalogue, over green-flag (usable) laps with a
positive recorded gap. That is a defensible reading of "as close as cars
actually get and stay" — it excludes the extreme tail (a momentary
same-corner reading, or a timing artifact) while still representing genuine
wheel-to-wheel running. Deliberately not the 1st percentile: at 0.32s that
is essentially "as close as cars *ever* get," which as a *sustained* floor
would let the simulator hold cars closer than real cars sustain.

Usage:
    python backend/scripts/fit_min_following_gap.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.simulation.position import MIN_FOLLOWING_GAP_S  # noqa: E402

PERCENTILE = 5.0


def main() -> None:
    pooled: list[float] = []
    print(f"{'race':>18} {'n':>6} {'p1':>7} {'p5':>7} {'p10':>7} {'median':>8}")
    for entry in CATALOGUE:
        snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
        gaps = [
            lap.gap_to_ahead_s
            for lap in snapshot.laps
            if lap.gap_to_ahead_s is not None and lap.gap_to_ahead_s > 0 and lap.is_usable_for_fitting
        ]
        if not gaps:
            continue
        arr = np.array(gaps)
        print(
            f"{snapshot.race_key:>18} {len(arr):>6} {np.percentile(arr, 1):>7.3f} "
            f"{np.percentile(arr, 5):>7.3f} {np.percentile(arr, 10):>7.3f} {np.median(arr):>8.3f}"
        )
        pooled.extend(gaps)

    arr = np.array(pooled)
    fitted = float(np.percentile(arr, PERCENTILE))
    print()
    print(f"POOLED n={len(arr)}")
    for p in (0.5, 1, 2, 5, 10):
        print(f"  p{p} = {np.percentile(arr, p):.4f}s")
    print(f"  min={arr.min():.4f}s  median={np.median(arr):.3f}s")
    print()
    print(f"Fitted MIN_FOLLOWING_GAP_S (p{PERCENTILE:g}) = {fitted:.4f}s")
    print(f"position.MIN_FOLLOWING_GAP_S is currently {MIN_FOLLOWING_GAP_S}")
    if abs(fitted - MIN_FOLLOWING_GAP_S) > 0.05:
        print(
            f"  MISMATCH: differs from the constant by more than 0.05 — update "
            "position.MIN_FOLLOWING_GAP_S (and its comment) to match, or explain the divergence."
        )
    else:
        print("  Consistent with the pooled fit (within 0.05).")


if __name__ == "__main__":
    main()
