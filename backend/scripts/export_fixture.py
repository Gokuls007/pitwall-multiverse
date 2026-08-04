#!/usr/bin/env python
"""Export one race + one counterfactual to JSON for the frontend.

Interim measure, honestly labelled: Phase 5's FastAPI layer is not built
yet, so Phase 6's components would otherwise have nothing to render. This
dumps the same data the API will eventually serve, from the same functions,
so the components are built against real validated numbers rather than
invented shapes — and swapping the fixture for a live endpoint later is a
data-source change, not a rewrite.

Everything here comes from the real pipeline: real lap data (`ingestion`),
fitted parameters (`parameters`, including the pooled cross-race dirty-air
fit), and the counterfactual engine's own ensemble.

Usage:
    python backend/scripts/export_fixture.py
"""

from __future__ import annotations

import json
import statistics
import sys
import warnings
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from pitwall.counterfactual.engine import simulate_counterfactual  # noqa: E402
from pitwall.domain.decision import ChangePitLap  # noqa: E402
from pitwall.ingestion.catalogue import get_entry  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402
from pitwall.simulation.lap_time import AR1_PHI  # noqa: E402
from pitwall.simulation.position import MIN_FOLLOWING_GAP_S  # noqa: E402
from pitwall.validation.metrics import real_gap_to_leader  # noqa: E402

RACE_KEY = "2019_hungarian"
# The demo counterfactual: Verstappen's real 42-lap second stint (laps
# 26-67) cut short, the stop Red Bull didn't make to cover Hamilton.
DECISION = ChangePitLap(driver="VER", original_lap=67, new_lap=50)
ENSEMBLE_SEEDS = range(60)
OUT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "fixtures" / "race.json"


def main() -> None:
    entry = get_entry(RACE_KEY)
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    race_params = fit_catalogue_with_pooled_dirty_air([snapshot])[snapshot.race_key]

    # --- Reality ---
    real_gaps = real_gap_to_leader(snapshot)
    real_series: dict[str, list[dict]] = defaultdict(list)
    for (driver, lap_number), gap in sorted(real_gaps.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        real_series[driver].append({"lap": lap_number, "gap": round(gap, 3)})

    real_position_by_driver_lap = {
        (lap.driver, lap.lap_number): lap.position for lap in snapshot.laps if lap.position > 0
    }

    drivers = [
        {
            "code": d.code,
            "team": d.team,
            "gridPosition": d.grid_position,
            "finishPosition": d.finish_position,
            "status": d.status,
            "retiredOnLap": d.retired_on_lap,
        }
        for d in snapshot.drivers
    ]

    # --- Stints, for the strategy timeline (aligned to the same lap axis) ---
    stints = [
        {
            "driver": s.driver,
            "stintNumber": s.stint_number,
            "compound": s.compound.value,
            "startLap": s.start_lap,
            "endLap": s.end_lap,
            "startedFresh": s.started_fresh,
        }
        for s in snapshot.stints
    ]
    pit_laps = sorted(
        {(lap.driver, lap.lap_number) for lap in snapshot.laps if lap.is_in_lap}
    )

    # --- Counterfactual ensemble ---
    results = [
        simulate_counterfactual(snapshot, race_params, DECISION, seed=seed, include_noise=True)
        for seed in ENSEMBLE_SEEDS
    ]

    # Per-lap distribution for the focused driver: median line plus a
    # pace-only band. Pace-only means total minus accumulated clamp penalty,
    # so the band is uncertainty about pace and NOT "how much traffic did he
    # hit" -- those are separate channels by design (see DECISIONS.md).
    focus = DECISION.driver
    by_lap_gaps: dict[int, list[float]] = defaultdict(list)
    by_lap_pace_only: dict[int, list[float]] = defaultdict(list)
    by_lap_clamped: dict[int, int] = defaultdict(int)
    for result in results:
        leader_cum_by_lap: dict[int, float] = {}
        for state in result.lap_states:
            current = leader_cum_by_lap.get(state.lap_number)
            if current is None or state.cumulative_time_s < current:
                leader_cum_by_lap[state.lap_number] = state.cumulative_time_s
        for state in result.lap_states:
            if state.driver != focus:
                continue
            by_lap_gaps[state.lap_number].append(state.gap_to_leader_s)
            # Strip this driver's accumulated held-up time to isolate pace.
            by_lap_pace_only[state.lap_number].append(
                state.gap_to_leader_s - state.cumulative_clamp_penalty_s
            )
            if state.stuck_behind_clamped:
                by_lap_clamped[state.lap_number] += 1

    def quantile(values: list[float], q: float) -> float:
        ordered = sorted(values)
        if not ordered:
            return float("nan")
        idx = min(int(q * (len(ordered) - 1)), len(ordered) - 1)
        return ordered[idx]

    alternate_series = []
    for lap_number in sorted(by_lap_gaps):
        gaps = by_lap_gaps[lap_number]
        pace = by_lap_pace_only[lap_number]
        n_clamped = by_lap_clamped.get(lap_number, 0)
        alternate_series.append(
            {
                "lap": lap_number,
                "gap": round(statistics.median(gaps), 3),
                # Pace-only band: the ONLY thing the band may represent.
                "paceLow": round(quantile(pace, 0.1), 3),
                "paceHigh": round(quantile(pace, 0.9), 3),
                # Traffic as a discrete event channel, not merged into the band.
                "clampedFraction": round(n_clamped / len(results), 3),
            }
        )

    # A subsample of individual seed traces. Spec 6.10 wants a distribution,
    # and the chart is the most persuasive surface in the product: a lone
    # median line reads as *the* answer and can visually contradict the
    # classification panel beside it (median shows a small final gap while
    # the ensemble says he wins in a fifth of runs). Drawing real seed
    # traces behind the median makes the spread honest.
    seed_series = []
    for result in results[:14]:
        trace = [
            {"lap": s.lap_number, "gap": round(s.gap_to_leader_s, 3)}
            for s in result.lap_states
            if s.driver == focus and s.lap_number >= DECISION.first_affected_lap
        ]
        if trace:
            seed_series.append({"seed": result.rng_seed, "points": trace})

    winners = [result.classification[0][0] for result in results if result.classification]
    focus_positions = [dict(result.classification).get(focus) for result in results]
    focus_wins = sum(1 for p in focus_positions if p == 1)

    payload = {
        "meta": {
            "raceKey": snapshot.race_key,
            "year": snapshot.year,
            "eventName": snapshot.event_name,
            "circuit": snapshot.circuit,
            "totalLaps": snapshot.total_laps,
            "source": "generated by backend/scripts/export_fixture.py (Phase 5 API not yet built)",
            # Parameter fingerprint. A hand-exported fixture goes stale
            # silently the moment anything is refit, and this session's
            # parameters moved three times — the 25%-win figure quoted in
            # prose was measured at MIN_FOLLOWING_GAP_S=0.3 and was already
            # wrong by the time it was written down. `tests/test_fixture.py`
            # asserts these match the live constants, so a refit that
            # invalidates the fixture fails a test instead of quietly
            # shipping a number nobody re-derived.
            "paramFingerprint": {
                "minFollowingGapS": MIN_FOLLOWING_GAP_S,
                "ar1Phi": AR1_PHI,
                "pitLaneLossS": round(race_params.pit_lane_loss_s, 4),
                "overtakeDifficulty": round(race_params.overtake_difficulty, 6),
                "dirtyAirMaxPenaltyS": round(race_params.dirty_air.max_penalty_s, 6),
                "dirtyAirDecayScaleS": round(race_params.dirty_air.decay_scale_s, 6),
            },
        },
        "drivers": drivers,
        "stints": stints,
        "pitLaps": [{"driver": d, "lap": lap} for d, lap in pit_laps],
        "realSeries": real_series,
        "realPositions": [
            {"driver": d, "lap": lap, "position": pos}
            for (d, lap), pos in sorted(real_position_by_driver_lap.items())
        ],
        "safetyCarPeriods": [
            {"kind": p.kind, "startLap": p.start_lap, "endLap": p.end_lap}
            for p in snapshot.safety_car_periods
        ],
        "counterfactual": {
            "label": f"{DECISION.driver} pits lap {DECISION.new_lap} instead of {DECISION.original_lap}",
            "driver": DECISION.driver,
            "divergenceLap": DECISION.first_affected_lap,
            "nSeeds": len(results),
            "series": alternate_series,
            "seedSeries": seed_series,
            "outcome": {
                "focusDriver": focus,
                "winFraction": round(focus_wins / len(results), 3),
                "positionDistribution": {
                    str(pos): focus_positions.count(pos) for pos in sorted(set(p for p in focus_positions if p))
                },
                "modalWinner": max(set(winners), key=winners.count) if winners else None,
            },
            "caveat": (
                "The closing trajectory rests on the pace and tyre models, which have "
                "held-out validation. Whether the pass completes rests on "
                "overtake_difficulty (a noisy single-race fit) and driver skill (never "
                "fitted, uniform prior) -- so treat the win fraction as soft."
            ),
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(f"  drivers={len(drivers)} laps={snapshot.total_laps} stints={len(stints)}")
    print(f"  counterfactual: {payload['counterfactual']['label']}")
    print(f"  {focus} wins {focus_wins}/{len(results)} seeds")


if __name__ == "__main__":
    main()
