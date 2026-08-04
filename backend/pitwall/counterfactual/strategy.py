"""Turn a `Decision` into a modified per-lap strategy (spec 9.1 step 2).

Only `ChangePitLap` is implemented. The others (`ChangeCompound`,
`AddPitStop`, `RemovePitStop`, `ShiftSafetyCar`, `RemoveSafetyCar`) are
declared on `Decision` (`domain/decision.py`) with working
`first_affected_lap` properties, but `apply_decision` raises
`NotImplementedError` for them — a deliberate scope boundary for this pass
of Phase 4, not a placeholder pretending to work. `ChangePitLap` and
`ShiftSafetyCar` are "where the real content is" for a pit-strategy tool;
`ChangeCompound` specifically should stay flagged as prior-driven even once
built (spec 6.3: 61% of adjacent-compound gaps across the catalogue sit at
the declared 0.15s floor, so for most drivers a compound-swap counterfactual
answers from the prior, not from that driver's data — ship it visibly
flagged as such, or don't ship it).
"""

from __future__ import annotations

from dataclasses import replace

from pitwall.domain.decision import ChangePitLap, Decision
from pitwall.domain.race import LapRecord, RaceSnapshot


def apply_decision(snapshot: RaceSnapshot, decision: Decision) -> dict[tuple[str, int], LapRecord]:
    """Returns overrides: `{(driver, lap_number): LapRecord}` for every lap
    whose compound/tyre-age/pit-lap status differs from reality under this
    decision. Laps not present in the returned mapping are unaffected —
    the caller (`counterfactual/engine.py`) falls back to the real record
    for anything not overridden.
    """
    if isinstance(decision, ChangePitLap):
        return _apply_change_pit_lap(snapshot, decision)
    raise NotImplementedError(
        f"{type(decision).__name__} is not yet implemented in counterfactual/strategy.py "
        "— see module docstring for current scope."
    )


def _apply_change_pit_lap(snapshot: RaceSnapshot, decision: ChangePitLap) -> dict[tuple[str, int], LapRecord]:
    driver_laps = {lap.lap_number: lap for lap in snapshot.laps if lap.driver == decision.driver}

    original_in = driver_laps.get(decision.original_lap)
    if original_in is None or not original_in.is_in_lap:
        raise ValueError(
            f"{decision.driver} lap {decision.original_lap} is not a real pit in-lap — "
            "ChangePitLap.original_lap must name an actual stop."
        )

    # The next stint's *first* lap is not reliably `original_lap + 1` — the
    # transition can span more than one lap in the raw data (found on 2019
    # Hungary's Hamilton: lap 48 in, lap 49 still flagged an out-lap but
    # still on the old compound with tyre age continuing 17->18, and the
    # new stint (compound + tyre_life=1) doesn't actually start until lap
    # 50). Derive the transition's width from the real data instead of
    # assuming a fixed offset, and preserve that same width when the stop
    # is shifted, rather than hardcoding it.
    old_stint = original_in.stint
    old_stint_laps = sorted(
        (lap for lap in driver_laps.values() if lap.stint == old_stint), key=lambda lap: lap.lap_number
    )
    old_stint_start_lap = old_stint_laps[0].lap_number
    old_stint_start_age = old_stint_laps[0].tyre_life
    old_compound = original_in.compound

    next_stint_laps = sorted(
        (lap for lap in driver_laps.values() if lap.stint == old_stint + 1), key=lambda lap: lap.lap_number
    )
    if not next_stint_laps:
        raise ValueError(
            f"{decision.driver}: lap {decision.original_lap} was the last stop of the race — "
            "nothing to shift it relative to."
        )
    real_new_stint_start_lap = next_stint_laps[0].lap_number
    new_stint_start_age = next_stint_laps[0].tyre_life
    new_stint_compound = next_stint_laps[0].compound
    transition_width = real_new_stint_start_lap - decision.original_lap  # >=1; usually 1

    # Affected range: from the earlier of (original, new) pit lap through
    # the end of the shifted second stint — up to (but not including)
    # whichever real lap is the driver's *next independent pit event* after
    # `original_lap`, or the end of the race if there isn't one. Found by
    # the real `is_in_lap` flag directly, not by stint index +2: a stint
    # transition and its `is_in_lap` flag don't reliably land on the same
    # lap (the same multi-lap-transition anomaly noted above), so indexing
    # two stints ahead can land inside — and silently overwrite — a later,
    # unrelated real stop. A `new_lap` that would collide with that next
    # stop isn't handled — raised explicitly rather than silently producing
    # a wrong strategy.
    next_stop_lap = min(
        (lap.lap_number for lap in driver_laps.values() if lap.is_in_lap and lap.lap_number > decision.original_lap),
        default=None,
    )
    range_end = (next_stop_lap - 1) if next_stop_lap is not None else max(driver_laps)
    lo = min(decision.original_lap, decision.new_lap)
    shifted_new_stint_start_lap = decision.new_lap + transition_width
    if next_stop_lap is not None and shifted_new_stint_start_lap >= next_stop_lap:
        raise ValueError(
            f"{decision.driver}: shifting lap {decision.original_lap} to {decision.new_lap} would push the "
            f"new stint past the following real stop (lap {next_stop_lap}) — "
            "shifting a stop past the following one isn't supported here."
        )

    overrides: dict[tuple[str, int], LapRecord] = {}
    for lap_number in range(lo, range_end + 1):
        real = driver_laps.get(lap_number)
        if real is None:
            continue

        if lap_number < shifted_new_stint_start_lap:
            # Still the old stint, including the in-lap itself and any
            # multi-lap transition — compound and tyre age continue the old
            # stint's progression, matching the real data's own behaviour
            # through an equivalent-width transition. Any lap strictly
            # between the in-lap and the (shifted) tyre-reset lap carries
            # the out-lap flag — this is where it lands in the observed
            # transition_width > 1 case (2019 Hungary's Hamilton: the
            # out-lap flag is on lap 49, one lap *before* the tyre actually
            # resets on lap 50).
            compound = old_compound
            tyre_age = old_stint_start_age + (lap_number - old_stint_start_lap)
            is_in_lap = lap_number == decision.new_lap
            is_out_lap = decision.new_lap < lap_number < shifted_new_stint_start_lap
        else:
            compound = new_stint_compound
            tyre_age = new_stint_start_age + (lap_number - shifted_new_stint_start_lap)
            is_in_lap = False
            # Only mark the reset lap itself as the out-lap when there's no
            # separate transition-zone lap to carry that flag instead
            # (transition_width == 1, the ordinary case) — otherwise the
            # transition-zone lap above already carries it, and marking
            # this lap too would double up the out-lap (and its pit-loss
            # time addition) on a lap that's really just a normal green-flag
            # lap on the new tyre.
            is_out_lap = lap_number == shifted_new_stint_start_lap and transition_width == 1

        overrides[(decision.driver, lap_number)] = replace(
            real,
            compound=compound,
            tyre_life=tyre_age,
            is_in_lap=is_in_lap,
            is_out_lap=is_out_lap,
        )

    return overrides
