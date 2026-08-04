#!/usr/bin/env python
"""Regenerate VALIDATION.md and gap-trace plots for every catalogue race
(spec Phase 3, the hard gate).

Usage:
    python backend/scripts/run_validation.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402
from pitwall.validation.metrics import real_gap_to_leader  # noqa: E402
from pitwall.validation.replay import DEFAULT_ENSEMBLE_SEEDS, replay_ensemble  # noqa: E402
from pitwall.validation.report import (  # noqa: E402
    EXCLUDED_FROM_GATE_AGGREGATE,
    aggregate_race_metrics,
    render_validation_md,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PLOTS_DIR = REPO_ROOT / "data" / "validation_plots"


def _plot_gap_trace(snapshot, race_params, race_key: str) -> Path:
    """One representative ensemble run (first seed) vs. reality, gap-to-leader
    over laps, one line per driver — spec Phase 3's "gap-trace comparison
    plots." Visual inspection catches shape errors aggregate metrics hide
    (spec 8.2).
    """
    results = replay_ensemble(snapshot, race_params, DEFAULT_ENSEMBLE_SEEDS[:1])
    result = results[0]
    real_gaps = real_gap_to_leader(snapshot)

    drivers = sorted({state.driver for state in result.lap_states})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

    for driver in drivers:
        sim_by_lap = {s.lap_number: s.gap_to_leader_s for s in result.lap_states if s.driver == driver}
        laps_sorted = sorted(sim_by_lap)
        axes[0].plot(laps_sorted, [sim_by_lap[l] for l in laps_sorted], linewidth=0.8)

        real_by_lap = {lap: gap for (d, lap), gap in real_gaps.items() if d == driver}
        laps_sorted_real = sorted(real_by_lap)
        axes[1].plot(laps_sorted_real, [real_by_lap[l] for l in laps_sorted_real], linewidth=0.8)

    axes[0].set_title(f"{race_key}: simulated (seed {DEFAULT_ENSEMBLE_SEEDS[0]})")
    axes[1].set_title(f"{race_key}: real")
    for ax in axes:
        ax.set_xlabel("Lap")
        ax.invert_yaxis()
    axes[0].set_ylabel("Gap to leader (s)")

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLOTS_DIR / f"{race_key}_gap_trace.png"
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def main() -> None:
    # Dirty air needs pooling across the whole catalogue to be identifiable
    # (see DECISIONS.md / parameters/dirty_air.py) — load every race first,
    # fit them together, then validate one at a time as before.
    snapshots = []
    for entry in CATALOGUE:
        snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
        snapshots.append(snapshot)
    race_params_by_key = fit_catalogue_with_pooled_dirty_air(snapshots)

    race_summaries = {}
    for snapshot in snapshots:
        entry_key = snapshot.race_key
        print(f"=== Validating {entry_key} ===")
        race_params = race_params_by_key[entry_key]
        summary = aggregate_race_metrics(snapshot, race_params)
        race_summaries[entry_key] = summary
        status = "PASS" if summary["passes_all_thresholds"] else "FAIL"
        print(f"  {status} — winner {summary['real_winner']}/{summary['modal_sim_winner']}, "
              f"rank_corr={summary['rank_correlation_median']:.3f}, "
              f"within_one={summary['within_one_position_rate_median']:.1%}")
        plot_path = _plot_gap_trace(snapshot, race_params, entry_key)
        print(f"  gap-trace plot: {plot_path}")

    markdown = render_validation_md(race_summaries)
    validation_path = REPO_ROOT / "VALIDATION.md"
    validation_path.write_text(markdown, encoding="utf-8")
    print(f"\nWrote {validation_path}")

    any_failed = any(
        not s["passes_all_thresholds"]
        for key, s in race_summaries.items()
        if key not in EXCLUDED_FROM_GATE_AGGREGATE
    )
    if EXCLUDED_FROM_GATE_AGGREGATE:
        print(
            f"\n(Excluded from the pass/fail aggregate: "
            f"{', '.join(EXCLUDED_FROM_GATE_AGGREGATE)} — see VALIDATION.md for why.)"
        )
    if any_failed:
        print("\n*** ONE OR MORE RACES FAIL Part 8.3 acceptance thresholds. ***")
        print("*** Per spec: STOP. Do not proceed to Phase 4. ***")
        sys.exit(1)
    print("\nAll races pass Part 8.3 acceptance thresholds.")


if __name__ == "__main__":
    main()
