#!/usr/bin/env python
"""Fit and persist RaceParameters for every catalogue race (spec Phase 2).

Usage:
    python backend/scripts/fit_parameters.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_race_parameters, save_race_parameters  # noqa: E402


def _print_summary(race_key: str, params) -> None:
    print(f"\n=== {race_key} ===")
    print(f"fuel_effect_s_per_lap: {params.fuel_effect_s_per_lap:.4f}")
    print(
        f"pit_lane_loss_s: {params.pit_lane_loss_s:.2f}  "
        f"pit_stop_stationary_s: {params.pit_stop_stationary_s:.2f} (declared prior)"
    )
    print(
        f"dirty_air: max_penalty={params.dirty_air.max_penalty_s:.3f}s "
        f"decay_scale={params.dirty_air.decay_scale_s:.3f}s r2={params.dirty_air.r_squared:.3f}"
    )
    print(f"overtake_difficulty: {params.overtake_difficulty:.3f}")
    print(
        f"sc_multiplier: {params.sc_lap_time_multiplier:.3f}  "
        f"vsc_multiplier: {params.vsc_lap_time_multiplier:.3f}"
    )
    fallbacks = params.fit_diagnostics.get("per_driver_fallbacks", {})
    if fallbacks:
        print(f"Driver fallbacks ({len(fallbacks)}):")
        for driver, reason in fallbacks.items():
            print(f"  {driver}: {reason}")
    print("Tyre degradation (base_offset_s, linear_deg_s_per_lap, cliff_lap, r2, n):")
    any_driver = next(iter(params.drivers))
    for compound, model in sorted(
        params.drivers[any_driver].tyre_models.items(), key=lambda kv: kv[0].value
    ):
        print(
            f"  [{any_driver}] {compound.value}: offset={model.base_offset_s:+.3f}s "
            f"slope={model.linear_deg_s_per_lap:+.4f}s/lap cliff={model.cliff_lap} "
            f"r2={model.r_squared:.3f} n={model.n_observations}"
        )


def main() -> None:
    for entry in CATALOGUE:
        snapshot, _report = load_race(entry.year, entry.fastf1_event_identifier)
        params = fit_race_parameters(snapshot)
        path = save_race_parameters(params)
        _print_summary(entry.race_key, params)
        print(f"Saved to {path}")


if __name__ == "__main__":
    main()
