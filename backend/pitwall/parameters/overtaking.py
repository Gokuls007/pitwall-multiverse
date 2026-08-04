"""Circuit overtake-difficulty fitting (spec 6.7).

Counts observed on-track position swaps between consecutive laps — excluding
swaps caused by a pit stop, a retirement, or involving lap 1 — relative to how
many "close following" lap-opportunities existed for a pass to happen at all.
`overtake_difficulty` is then `1 - pass_rate`, clamped to [0, 1].

This is a small-sample, single-race estimate (spec 6.7: "pool across multiple
races at the same circuit if available, and be explicit in diagnostics about
the uncertainty"). This project has no multi-race pooling for a single
circuit (that's Part 15's stretch goal), so every value here should be read as
noisy — the diagnostics say so explicitly rather than presenting a false
precision.

Driver `overtake_skill`/`defence_skill` priors are *not* fitted here — spec
6.7 explicitly allows them as hand-set, narrowly-bounded priors since they
aren't identifiable from one race. See `pace.py` for where they're set
(uniformly neutral) and DECISIONS.md for the reasoning.
"""

from __future__ import annotations

from pitwall.domain.race import RaceSnapshot

CLOSE_PROXIMITY_GAP_S = 1.5


def _positions_by_lap(snapshot: RaceSnapshot) -> dict[int, dict[str, int]]:
    by_lap: dict[int, dict[str, int]] = {}
    for lap in snapshot.laps:
        if lap.position <= 0:
            continue
        by_lap.setdefault(lap.lap_number, {})[lap.driver] = lap.position
    return by_lap


def _pit_laps_by_number(snapshot: RaceSnapshot) -> dict[int, set[str]]:
    by_lap: dict[int, set[str]] = {}
    for lap in snapshot.laps:
        if lap.is_in_lap or lap.is_out_lap:
            by_lap.setdefault(lap.lap_number, set()).add(lap.driver)
    return by_lap


def fit_overtake_difficulty(snapshot: RaceSnapshot) -> tuple[float, dict]:
    positions = _positions_by_lap(snapshot)
    pit_laps = _pit_laps_by_number(snapshot)
    retired_on_lap = {
        d.code: d.retired_on_lap for d in snapshot.drivers if d.retired_on_lap is not None
    }

    lap_numbers = sorted(n for n in positions if n > 1)
    passes = 0
    passes_excluded_pit = 0
    passes_excluded_retirement = 0

    for cur_lap in lap_numbers:
        prev_lap = cur_lap - 1
        if prev_lap not in positions or prev_lap == 1:
            continue
        prev_pos, cur_pos = positions[prev_lap], positions[cur_lap]
        common = sorted(set(prev_pos) & set(cur_pos))

        for i, d1 in enumerate(common):
            for d2 in common[i + 1 :]:
                d1_ahead_before = prev_pos[d1] < prev_pos[d2]
                d1_ahead_after = cur_pos[d1] < cur_pos[d2]
                if d1_ahead_before == d1_ahead_after:
                    continue  # no order change between these two drivers

                pitted = pit_laps.get(cur_lap, set()) | pit_laps.get(prev_lap, set())
                if d1 in pitted or d2 in pitted:
                    passes_excluded_pit += 1
                    continue
                if retired_on_lap.get(d1) in (cur_lap, prev_lap) or retired_on_lap.get(
                    d2
                ) in (cur_lap, prev_lap):
                    passes_excluded_retirement += 1
                    continue
                passes += 1

    close_proximity_laps = sum(
        1
        for lap in snapshot.laps
        if lap.lap_number > 1
        and lap.gap_to_ahead_s is not None
        and lap.gap_to_ahead_s < CLOSE_PROXIMITY_GAP_S
    )

    pass_rate = min(passes / close_proximity_laps, 1.0) if close_proximity_laps > 0 else 0.0
    overtake_difficulty = max(0.0, min(1.0, 1.0 - pass_rate))

    diagnostics = {
        "passes_counted": passes,
        "passes_excluded_pit_stop": passes_excluded_pit,
        "passes_excluded_retirement": passes_excluded_retirement,
        "close_proximity_laps": close_proximity_laps,
        "pass_rate": pass_rate,
        "single_race_estimate_uncertainty": (
            "This is a single-race sample (no multi-race circuit pooling, spec Part 15 "
            "stretch goal) — treat overtake_difficulty as noisy, not a precise circuit constant."
        ),
    }
    return overtake_difficulty, diagnostics
