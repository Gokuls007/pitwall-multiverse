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
from pitwall.counterfactual.strategy import (  # noqa: E402
    apply_decision,
    extrapolation_by_lap,
    observed_max_tyre_age,
)
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
    # Real tyre ages are carried explicitly rather than derived from stint
    # length. They are NOT the same thing: a stint can start on used tyres
    # (VER's 2019 Hungary first stint runs laps 1-25 but at ages 4-28), so
    # `end_lap - start_lap + 1` understates the age the tyre model was
    # actually asked about. An earlier version of the frontend computed it
    # that way and displayed ages that were simply wrong.
    tyre_age_by_driver_lap = {
        (lap.driver, lap.lap_number): lap.tyre_life for lap in snapshot.laps
    }

    def stint_age_bounds(driver: str, start_lap: int, end_lap: int) -> tuple[int, int]:
        ages = [
            tyre_age_by_driver_lap[(driver, lap)]
            for lap in range(start_lap, end_lap + 1)
            if (driver, lap) in tyre_age_by_driver_lap
        ]
        return (min(ages), max(ages)) if ages else (0, 0)

    stints = []
    for s in snapshot.stints:
        start_age, end_age = stint_age_bounds(s.driver, s.start_lap, s.end_lap)
        stints.append(
            {
                "driver": s.driver,
                "stintNumber": s.stint_number,
                "compound": s.compound.value,
                "startLap": s.start_lap,
                "endLap": s.end_lap,
                "startedFresh": s.started_fresh,
                "startTyreAge": start_age,
                "endTyreAge": end_age,
            }
        )
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

    # Alternate stint structure for the focus driver, plus how far past that
    # driver's observed tyre life each lap sits. The stint bar is where the
    # user makes the choice, so it's the right surface for the epistemics —
    # shading the beyond-evidence portion puts the caveat at the point of
    # decision instead of leaving it in DECISIONS.md.
    overrides = apply_decision(snapshot, DECISION)
    excess_by_lap = extrapolation_by_lap(snapshot, overrides)
    real_by_lap = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}

    def stint_runs(records: list[tuple[int, str, int, int]]) -> list[dict]:
        """Collapse per-lap (lap, compound, tyre_age, excess) into stint runs."""
        runs: list[dict] = []
        for lap_number, compound, tyre_age, excess in records:
            if runs and runs[-1]["compound"] == compound and lap_number == runs[-1]["endLap"] + 1:
                runs[-1]["endLap"] = lap_number
                runs[-1]["endTyreAge"] = tyre_age
                runs[-1]["extrapolatedLaps"] += 1 if excess > 0 else 0
                runs[-1]["maxExcessLaps"] = max(runs[-1]["maxExcessLaps"], excess)
                if excess > 0 and runs[-1]["firstExtrapolatedLap"] is None:
                    runs[-1]["firstExtrapolatedLap"] = lap_number
            else:
                runs.append(
                    {
                        "compound": compound,
                        "startLap": lap_number,
                        "endLap": lap_number,
                        "startTyreAge": tyre_age,
                        "endTyreAge": tyre_age,
                        "extrapolatedLaps": 1 if excess > 0 else 0,
                        "maxExcessLaps": excess,
                        "firstExtrapolatedLap": lap_number if excess > 0 else None,
                    }
                )
        return runs

    focus_alternate_records: list[tuple[int, str, int, int]] = []
    focus_real_records: list[tuple[int, str, int, int]] = []
    for lap_number in range(1, snapshot.total_laps + 1):
        real = real_by_lap.get((focus, lap_number))
        if real is None:
            continue
        focus_real_records.append((lap_number, real.compound.value, real.tyre_life, 0))
        effective = overrides.get((focus, lap_number), real)
        focus_alternate_records.append(
            (
                lap_number,
                effective.compound.value,
                effective.tyre_life,
                excess_by_lap.get((focus, lap_number), 0),
            )
        )

    observed_ceiling = {
        compound.value: age for compound, age in observed_max_tyre_age(snapshot, focus).items()
    }

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
            "focusStrategy": {
                "real": stint_runs(focus_real_records),
                "alternate": stint_runs(focus_alternate_records),
                "observedMaxTyreAge": observed_ceiling,
            },
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
