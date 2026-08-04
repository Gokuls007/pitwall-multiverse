#!/usr/bin/env python
"""Held-out extrapolation check for the pace/tyre model (Phase 3, spec 8.2/8.3).

The open-loop green-flag MAE reported in VALIDATION.md is in-sample: the
parameters were fitted by minimizing residuals against the exact laps being
scored. That measures fit quality, not forward prediction — and every
counterfactual answer *is* forward prediction (a tyre-age/lap-number
combination that never occurred in the data).

An earlier version of this check used leave-one-stint-out cross-validation
and found a large (0.596s -> 0.99s) degradation. That result was confounded
and wrong: Phase 2 established that within a stint, tyre age and lap number
are perfectly collinear, so degradation and fuel effect are only separable
across stints (most drivers have only 2-3, and only one or two per race
revisit a compound at a different race offset). Removing a whole stint
leaves a fit that's rank-deficient or near-singular for the same reason
Phase 2 already documented — the degradation is measuring the fitting
procedure collapsing, not genuine extrapolation error, and has nothing to
do with how the model is actually used (fit once on all real stints, then
asked to shift a tyre age by a few laps).

The corrected experiment: fit on ALL stints, but truncate the last few laps
of one stint, and predict the truncated tail. This is exactly what "pitted
a few laps later" asks for (same driver, same compound, slightly higher
tyre age than anything in the fitting sample) while leaving the fit fully
identified (every stint Phase 2's fit needs is still present in full or
in majority). Reports per-cell fitted-model condition number alongside the
accuracy numbers specifically so a future degenerate case is visible, not
silently averaged away.

Usage:
    python backend/scripts/held_out_check.py [--tail-laps N]
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters import pace, tyre  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402
from pitwall.simulation.lap_time import compose_lap_time_s  # noqa: E402
from pitwall.simulation.rng import make_rng  # noqa: E402

# "Pitted a few laps later" is the more common counterfactual direction and
# the harder one (pitting earlier asks for a *shorter* stint, i.e.
# interpolation within tyre ages already observed) — truncate this many
# laps off the end of a stint to simulate it. Not a declared prior in the
# Part 14 sense; a parameter of this diagnostic script, adjustable via CLI.
DEFAULT_TAIL_LAPS = 4
MIN_STINT_LAPS_TO_TRUNCATE = DEFAULT_TAIL_LAPS + 5  # leave a meaningful remainder to fit on


def _condition_number(train_frame: pd.DataFrame) -> float:
    """Same design-matrix construction as tyre.fit_driver_final, just to
    read off its condition number without duplicating the whole fit."""
    counts = train_frame["Compound"].value_counts()
    present = list(counts.index)
    reference = counts.idxmax()
    eligible = [c for c in present if counts[c] >= tyre.MIN_SAMPLES_PER_COMPOUND]
    cols = [np.ones(len(train_frame))]
    for c in eligible:
        cols.append(np.where(train_frame["Compound"] == c, train_frame["TyreAge"].to_numpy(dtype=float), 0.0))
    for c in present:
        if c != reference:
            cols.append((train_frame["Compound"] == c).to_numpy(dtype=float))
    X = np.column_stack(cols)
    try:
        return float(np.linalg.cond(X))
    except np.linalg.LinAlgError:
        return float("inf")


def main(tail_laps: int) -> None:
    snapshots = [load_race(e.year, e.fastf1_event_identifier)[0] for e in CATALOGUE]
    params_by_key = fit_catalogue_with_pooled_dirty_air(snapshots)
    rng = make_rng(0)  # unused: include_noise=False throughout

    rows = []  # one row per truncated-tail test cell

    for snap in snapshots:
        race_params = params_by_key[snap.race_key]
        dirty_air_model = race_params.dirty_air
        fuel_effect = race_params.fuel_effect_s_per_lap
        base_pace_correction = race_params.fit_diagnostics.get("base_pace_correction_s", 0.0)

        drivers = sorted({lap.driver for lap in snap.laps})
        for driver in drivers:
            driver_laps = [lap for lap in snap.laps if lap.driver == driver]
            full_params = race_params.drivers.get(driver)
            if full_params is None:
                continue
            stints = sorted({lap.stint for lap in driver_laps})

            full_frame = pd.DataFrame(
                [
                    {
                        "LapNumber": lap.lap_number,
                        "LapTimeSeconds": lap.lap_time_s,
                        "Compound": lap.compound.value,
                        "TyreAge": lap.tyre_life,
                        "IsUsableForFitting": lap.is_usable_for_fitting,
                        "Stint": lap.stint,
                        "GapToAhead": lap.gap_to_ahead_s,
                    }
                    for lap in driver_laps
                ]
            )

            for stint in stints:
                stint_laps = full_frame[full_frame["Stint"] == stint]
                usable_stint_laps = stint_laps[stint_laps["IsUsableForFitting"]].sort_values("LapNumber")
                if len(usable_stint_laps) < MIN_STINT_LAPS_TO_TRUNCATE:
                    continue

                tail_lap_numbers = set(usable_stint_laps["LapNumber"].tail(tail_laps))
                train_frame = full_frame[~full_frame["LapNumber"].isin(tail_lap_numbers)].drop(
                    columns=["Stint", "GapToAhead"]
                )
                test_rows = full_frame[full_frame["LapNumber"].isin(tail_lap_numbers)]

                cond_number = _condition_number(train_frame[train_frame["IsUsableForFitting"]])

                try:
                    base_pace_s, pace_std_s, tyre_models, _, _ = tyre.fit_driver_final(
                        train_frame, fuel_effect, {}
                    )
                except Exception:
                    continue
                if not np.isfinite(base_pace_s):
                    continue
                base_pace_s += base_pace_correction
                truncated_params = pace.build_driver_params(driver, base_pace_s, pace_std_s, tyre_models)

                for _, row in test_rows.iterrows():
                    compound = next((c for c in truncated_params.tyre_models if c.value == row["Compound"]), None)
                    full_compound = next((c for c in full_params.tyre_models if c.value == row["Compound"]), None)
                    if compound is None or full_compound is None:
                        continue

                    common = dict(
                        tyre_age=int(row["TyreAge"]),
                        lap_number=int(row["LapNumber"]),
                        fuel_effect_s_per_lap=fuel_effect,
                        dirty_air_model=dirty_air_model,
                        gap_to_ahead_s=row["GapToAhead"],
                        is_under_sc=False,
                        is_under_vsc=False,
                        sc_lap_time_multiplier=1.0,
                        vsc_lap_time_multiplier=1.0,
                        pit_lane_loss_s=0.0,
                        is_in_lap=False,
                        is_out_lap=False,
                        rng=rng,
                        include_noise=False,
                    )
                    predicted_held_out = compose_lap_time_s(
                        driver_params=truncated_params, compound=compound, **common
                    )
                    predicted_in_sample = compose_lap_time_s(
                        driver_params=full_params, compound=full_compound, **common
                    )
                    if not (np.isfinite(predicted_held_out) and np.isfinite(predicted_in_sample)):
                        continue

                    rows.append(
                        {
                            "race": snap.race_key,
                            "driver": driver,
                            "stint": stint,
                            "n_stints_total": len(stints),
                            "condition_number": cond_number,
                            "held_out_error": abs(predicted_held_out - row["LapTimeSeconds"]),
                            "in_sample_error": abs(predicted_in_sample - row["LapTimeSeconds"]),
                        }
                    )

    df = pd.DataFrame(rows)
    if df.empty:
        print("No held-out cells found — check tail_laps / MIN_STINT_LAPS_TO_TRUNCATE against the catalogue.")
        return

    print(f"n_test_laps={len(df)}  n_distinct_stints_truncated={df.groupby(['race', 'driver', 'stint']).ngroups}")
    print(f"In-sample MAE (same test laps): {df['in_sample_error'].mean():.3f}s (median {df['in_sample_error'].median():.3f}s)")
    print(f"Held-out MAE (truncated-tail):  {df['held_out_error'].mean():.3f}s (median {df['held_out_error'].median():.3f}s)")

    per_cell = df.groupby(["race", "driver", "stint"]).agg(
        held_out_mae=("held_out_error", "mean"),
        n_stints_total=("n_stints_total", "first"),
        condition_number=("condition_number", "first"),
    )
    frac_under = (per_cell["held_out_mae"] < 0.5).mean()
    print(f"Fraction of held-out (driver, stint) cells with MAE < 0.5s: {frac_under:.1%} ({(per_cell['held_out_mae'] < 0.5).sum()}/{len(per_cell)})")

    print("\nHeld-out MAE by remaining stint count and condition number (confound check):")
    for n_stints, group in per_cell.groupby("n_stints_total"):
        print(
            f"  n_stints_total={n_stints}: n_cells={len(group)}  "
            f"mean_held_out_mae={group['held_out_mae'].mean():.3f}s  "
            f"median_condition_number={group['condition_number'].median():.1f}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tail-laps", type=int, default=DEFAULT_TAIL_LAPS)
    args = parser.parse_args()
    main(args.tail_laps)
