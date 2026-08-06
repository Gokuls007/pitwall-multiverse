"""Turn a `Decision` into a modified per-lap strategy (spec 9.1 step 2).

`ChangePitLap` and `AddPitStop` are implemented. The others
(`ChangeCompound`, `RemovePitStop`, `ShiftSafetyCar`, `RemoveSafetyCar`)
are declared on `Decision` (`domain/decision.py`) with working
`first_affected_lap` properties, but `apply_decision` raises
`NotImplementedError` for them — a deliberate scope boundary, not a
placeholder pretending to work.

Implementation order here is driven by which direction the *tyre model*
can actually support, not by which is easiest to code (see DECISIONS.md's
held-out findings):

  - `AddPitStop` shortens the *original* stint it splits, so those laps sit
    at tyre ages the driver's own data already covers. Implemented — but
    note the important qualification a test caught here: the *new* stint it
    creates runs from the added stop to the driver's next real stop (or the
    finish), and that can easily exceed how long the driver actually ran the
    chosen compound. On 2019 Hungary, VER ran SOFT for only 6 real laps, so
    adding a SOFT stop on lap 50 asks for SOFT ages up to 17 — genuine
    extrapolation. `add_pit_stop_extrapolation_laps` reports exactly how far
    past observed data a given `AddPitStop` reaches, so callers can surface
    it rather than the tool answering confidently past its evidence. Adding
    a stop is *directionally* safer than removing one, not unconditionally
    safe.
  - `RemovePitStop` lengthens a stint, extrapolating tyre age past
    anything observed. On this catalogue that's severe: Verstappen's real
    42-lap 2019 Hungary stint is the longest sample available, so a
    one-stop counterfactual would need 60+-lap tyre life predicted from
    nothing. Deliberately *not* implemented until the model can support
    it or the output can honestly flag how far past the data it is.
  - `ChangeCompound` should stay flagged as prior-driven even once built
    (spec 6.3: 61% of adjacent-compound gaps across the catalogue sit at
    the declared 0.15s floor, so for most drivers a compound-swap
    counterfactual answers from the prior, not from that driver's data —
    ship it visibly flagged as such, or don't ship it).
"""

from __future__ import annotations

from dataclasses import replace

from pitwall.domain.decision import AddPitStop, ChangePitLap, Decision
from pitwall.domain.enums import Compound
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
    if isinstance(decision, AddPitStop):
        return _apply_add_pit_stop(snapshot, decision)
    raise NotImplementedError(
        f"{type(decision).__name__} is not yet implemented in counterfactual/strategy.py "
        "— see module docstring for current scope."
    )


def observed_max_tyre_age(snapshot: RaceSnapshot, driver: str) -> dict[Compound, int]:
    """The oldest tyre age this driver actually ran on each compound in this
    race — the boundary past which any counterfactual using that compound is
    extrapolating rather than interpolating."""
    observed: dict[Compound, int] = {}
    for lap in snapshot.laps:
        if lap.driver != driver:
            continue
        observed[lap.compound] = max(observed.get(lap.compound, 0), lap.tyre_life)
    return observed


def extrapolation_by_lap(
    snapshot: RaceSnapshot, overrides: dict[tuple[str, int], LapRecord]
) -> dict[tuple[str, int], int]:
    """For every overridden lap, how many laps *past* that driver's observed
    tyre life on that compound it sits. 0 means within observed range.

    Decision-agnostic on purpose: `ChangePitLap` extrapolates too, not just
    `AddPitStop`. Moving VER's 2019 Hungary stop from lap 67 to 50 lengthens
    the following SOFT stint to ~20 laps against the 6 he actually ran, which
    is exactly the same class of exposure the `AddPitStop` helper was written
    for. Anything that surfaces confidence to a user should read this rather
    than assume a decision type is safe by construction.
    """
    result: dict[tuple[str, int], int] = {}
    observed_by_driver: dict[str, dict[Compound, int]] = {}
    for (driver, lap_number), record in overrides.items():
        if driver not in observed_by_driver:
            observed_by_driver[driver] = observed_max_tyre_age(snapshot, driver)
        observed = observed_by_driver[driver].get(record.compound, 0)
        result[(driver, lap_number)] = max(0, record.tyre_life - observed)
    return result


def add_pit_stop_extrapolation_laps(snapshot: RaceSnapshot, decision: AddPitStop) -> int:
    """How many laps of the stint an `AddPitStop` creates would run at a
    tyre age *beyond* anything the driver actually ran on that compound in
    this race — i.e. how far the answer extrapolates past its own evidence.
    0 means fully within observed range.

    Exists because "adding a stop is interpolation" is only true of the
    shortened original stint; the new stint can be much longer than the
    driver's real sample on the chosen compound (see module docstring).
    Callers should surface a non-zero value rather than presenting the
    result with the same confidence as an in-range one.
    """
    overrides = _apply_add_pit_stop(snapshot, decision)
    return sum(1 for excess in extrapolation_by_lap(snapshot, overrides).values() if excess > 0)


def _apply_add_pit_stop(snapshot: RaceSnapshot, decision: AddPitStop) -> dict[tuple[str, int], LapRecord]:
    """Insert an extra stop at `decision.lap`, splitting whichever real
    stint contains that lap into two. Laps up to and including `lap` keep
    the original stint's compound and tyre-age progression (with `lap`
    becoming an in-lap); from `lap + 1` onward the driver runs
    `decision.compound` on a fresh tyre, re-aged from 1.

    Everything after the split keeps its real strategy: the driver's *next*
    real stop still happens on its real lap, so this models "one extra
    stop" rather than "re-plan the rest of the race." The affected range
    therefore ends at the lap before that next real stop (or the last lap,
    if there isn't one). Bounded by the real `is_in_lap` flag directly
    rather than by stint index, for the same reason `_apply_change_pit_lap`
    does — a stint transition and its in-lap flag don't reliably land on
    the same lap in this data.
    """
    driver_laps = {lap.lap_number: lap for lap in snapshot.laps if lap.driver == decision.driver}

    target = driver_laps.get(decision.lap)
    if target is None:
        raise ValueError(f"{decision.driver} has no lap {decision.lap} to add a stop on.")
    if target.is_in_lap or target.is_out_lap:
        raise ValueError(
            f"{decision.driver} lap {decision.lap} is already part of a real pit sequence "
            "(in-lap or out-lap) — adding a second stop on the same lap isn't meaningful."
        )

    split_stint = target.stint
    split_stint_laps = sorted(
        (lap for lap in driver_laps.values() if lap.stint == split_stint), key=lambda lap: lap.lap_number
    )
    stint_start_lap = split_stint_laps[0].lap_number
    stint_start_age = split_stint_laps[0].tyre_life
    old_compound = target.compound

    next_stop_lap = min(
        (lap.lap_number for lap in driver_laps.values() if lap.is_in_lap and lap.lap_number > decision.lap),
        default=None,
    )
    # Through the next real stop *inclusive*. That lap belongs to the stint
    # being shifted, so its tyre age has to be renumbered with the rest of it —
    # excluding it entirely (as this did until a fixture audit caught it)
    # conflates "don't move this stop" with "don't renumber this stint", and
    # left the in-lap carrying reality's age. On 2019 Hungary BOT 5->20 that
    # produced a tyre jumping from age 25 on lap 45 to age 41 on lap 46. The
    # stop itself still stays exactly where reality put it: the in-lap and
    # out-lap flags below are taken from the real record, not synthesised.
    range_end = next_stop_lap if next_stop_lap is not None else max(driver_laps)
    if next_stop_lap is not None and decision.lap + 1 >= next_stop_lap:
        raise ValueError(
            f"{decision.driver}: an added stop on lap {decision.lap} leaves no room before the next "
            f"real stop (lap {next_stop_lap})."
        )

    overrides: dict[tuple[str, int], LapRecord] = {}
    for lap_number in range(decision.lap, range_end + 1):
        real = driver_laps.get(lap_number)
        if real is None:
            continue

        if lap_number == decision.lap:
            compound = old_compound
            tyre_age = stint_start_age + (lap_number - stint_start_lap)
            is_in_lap, is_out_lap = True, False
        else:
            compound = decision.compound
            tyre_age = 1 + (lap_number - (decision.lap + 1))
            is_in_lap = False
            is_out_lap = lap_number == decision.lap + 1

        overrides[(decision.driver, lap_number)] = replace(
            real,
            compound=compound,
            tyre_life=tyre_age,
            is_in_lap=is_in_lap,
            is_out_lap=is_out_lap,
        )

    return overrides


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
    # Through the next real stop *inclusive*. That lap belongs to the stint
    # being shifted, so its tyre age has to be renumbered with the rest of it —
    # excluding it entirely (as this did until a fixture audit caught it)
    # conflates "don't move this stop" with "don't renumber this stint", and
    # left the in-lap carrying reality's age. On 2019 Hungary BOT 5->20 that
    # produced a tyre jumping from age 25 on lap 45 to age 41 on lap 46. The
    # stop itself still stays exactly where reality put it: the in-lap and
    # out-lap flags below are taken from the real record, not synthesised.
    range_end = next_stop_lap if next_stop_lap is not None else max(driver_laps)
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
            # Read from reality rather than forced False: this range now runs
            # through the driver's next real stop, whose in-lap must survive.
            is_in_lap = real.is_in_lap
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
