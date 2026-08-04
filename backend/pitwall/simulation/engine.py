"""The lap-by-lap simulation loop (spec 7.1).

Phase 3 scope: **replay only** — simulate a race using the exact real
strategy (real pit laps, real compounds, real SC/VSC periods, real
retirements) and compare the result against reality (`validation/`). This is
deliberately not yet the generic fork-and-resimulate-from-a-`Decision`
counterfactual engine (spec Part 9) — that's Phase 4's `counterfactual/`
package, built on top of this same lap-time/position/overtake machinery.

Pure: takes `RaceSnapshot` + `RaceParameters` (both plain data) and a seed,
returns a `SimulationResult`. No I/O, no FastF1, no parameters-fitting code.
"""

from __future__ import annotations

from pitwall.domain.race import RaceParameters, RaceSnapshot
from pitwall.domain.result import LapState, SimulationResult
from pitwall.simulation.lap_time import compose_lap_time_s
from pitwall.simulation.pit import pit_stop_noise_s
from pitwall.simulation.position import compute_gaps_to_leader, reorder_pitting_drivers, resolve_positions
from pitwall.simulation.rng import make_rng
from pitwall.simulation.safety_car import compress_field_under_sc

# Spec 6.6: dirty-air penalties taper to negligible "beyond roughly two
# seconds" — used only for the informational `LapState.in_dirty_air` flag,
# not for the penalty itself (which uses the full continuous curve).
DIRTY_AIR_FLAG_THRESHOLD_S = 2.0


def _track_status_for_lap(snapshot: RaceSnapshot, lap_number: int) -> tuple[bool, bool]:
    """Returns (is_under_sc, is_under_vsc) for a lap. RED periods (none in
    the current catalogue) are folded into `is_under_sc` as the closest
    fitted analogue — an untested simplification, flagged rather than
    silently assumed correct."""
    is_sc = False
    is_vsc = False
    for period in snapshot.safety_car_periods:
        if not period.covers(lap_number):
            continue
        if period.kind in ("SC", "RED"):
            is_sc = True
        elif period.kind == "VSC":
            is_vsc = True
    return is_sc, is_vsc


def _final_classification(
    lap_states: tuple[LapState, ...],
) -> tuple[tuple[str, int], ...]:
    """More laps completed ranks higher (a retiree never outranks a
    finisher); within the same last lap, rank by track position at that lap.
    """
    last_state: dict[str, LapState] = {}
    for state in lap_states:
        current = last_state.get(state.driver)
        if current is None or state.lap_number > current.lap_number:
            last_state[state.driver] = state

    ranked = sorted(last_state.values(), key=lambda s: (-s.lap_number, s.position))
    return tuple((state.driver, position) for position, state in enumerate(ranked, start=1))


def simulate_replay(
    snapshot: RaceSnapshot,
    race_params: RaceParameters,
    seed: int,
    include_noise: bool = True,
) -> SimulationResult:
    """`include_noise=False` gives the deterministic pace prediction with no
    sampled residual (pace noise *and* pit-stop noise) — see
    `lap_time.compose_lap_time_s`'s docstring for why validation's
    lap-time-accuracy metric must use this mode, not the default. Overtake
    resolution still draws from `rng` regardless (a genuinely modelled
    uncertain event, not a noise artifact), so an ensemble of seeds is still
    meaningful with noise off.
    """
    rng = make_rng(seed)

    laps_by_driver_lap = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    drivers_with_laps = sorted({lap.driver for lap in snapshot.laps})
    grid_position = {d.code: d.grid_position for d in snapshot.drivers}
    retired_on_lap = {d.code: d.retired_on_lap for d in snapshot.drivers}

    order = sorted(drivers_with_laps, key=lambda d: grid_position.get(d, 999))
    active = set(drivers_with_laps)
    cumulative_time_s: dict[str, float] = dict.fromkeys(drivers_with_laps, 0.0)
    prev_gap_to_ahead: dict[str, float | None] = dict.fromkeys(drivers_with_laps, None)

    lap_states: list[LapState] = []
    notes: list[str] = []

    for lap_number in range(1, snapshot.total_laps + 1):
        is_under_sc, is_under_vsc = _track_status_for_lap(snapshot, lap_number)

        this_lap_time_s: dict[str, float] = {}
        retiring_this_lap: list[str] = []
        pitted_this_lap: set[str] = set()

        for driver in order:
            if driver not in active:
                continue
            record = laps_by_driver_lap.get((driver, lap_number))
            if record is None or record.lap_time_s is None:
                if retired_on_lap.get(driver) is not None and lap_number > retired_on_lap[driver]:
                    active.discard(driver)
                continue

            driver_params = race_params.drivers.get(driver)
            if driver_params is None:
                notes.append(f"{driver}: no fitted DriverParams, skipped lap {lap_number}")
                continue

            modeling_compound = record.compound
            if modeling_compound not in driver_params.tyre_models:
                if not driver_params.tyre_models:
                    notes.append(
                        f"{driver}: no fitted TyreModel at all, skipped lap {lap_number}"
                    )
                    continue
                # A compound the driver barely used (e.g. a single splash-and-dash
                # lap) can be entirely absent from tyre_models: Phase 2's
                # fitting only builds an entry for compounds present among a
                # driver's *usable* laps, and a single-lap stint is almost
                # always structurally excluded (first-lap/in-out-lap rules,
                # spec 4.2). Rather than crash mid-replay over a lap that
                # barely affects overall pace, substitute the driver's most-
                # sampled fitted compound for this one lap's modelling only —
                # the real compound is still recorded on the LapState.
                fallback_model = max(
                    driver_params.tyre_models.values(), key=lambda tm: tm.n_observations
                )
                modeling_compound = fallback_model.compound
                notes.append(
                    f"{driver} L{lap_number}: no fitted TyreModel for {record.compound.value} "
                    f"(rarely used); substituted {modeling_compound.value} model for this lap only"
                )

            lap_time = compose_lap_time_s(
                driver_params=driver_params,
                compound=modeling_compound,
                tyre_age=record.tyre_life,
                lap_number=lap_number,
                fuel_effect_s_per_lap=race_params.fuel_effect_s_per_lap,
                dirty_air_model=race_params.dirty_air,
                gap_to_ahead_s=prev_gap_to_ahead.get(driver),
                is_under_sc=is_under_sc,
                is_under_vsc=is_under_vsc,
                sc_lap_time_multiplier=race_params.sc_lap_time_multiplier,
                vsc_lap_time_multiplier=race_params.vsc_lap_time_multiplier,
                pit_lane_loss_s=race_params.pit_lane_loss_s,
                is_in_lap=record.is_in_lap,
                is_out_lap=record.is_out_lap,
                rng=rng,
                include_noise=include_noise,
            )
            if (record.is_in_lap or record.is_out_lap) and include_noise:
                lap_time += pit_stop_noise_s(rng)
            if record.is_in_lap or record.is_out_lap:
                pitted_this_lap.add(driver)

            cumulative_time_s[driver] += lap_time
            this_lap_time_s[driver] = lap_time

            if retired_on_lap.get(driver) == lap_number:
                retiring_this_lap.append(driver)

        raced_this_lap = [d for d in order if d in this_lap_time_s]
        if not raced_this_lap:
            continue

        # Pit stops are a mechanical time loss, not a contested on-track
        # battle — reorder by cumulative time directly, unconditionally
        # (including under SC/VSC, before compression below assumes correct
        # track-position order). Without this, a driver who loses 20+
        # seconds in the pits only falls behind a following car if that car
        # "wins" a proximity-gated probabilistic pass against them, and the
        # gap between them is enormous immediately after the stop — so that
        # attempt almost never triggers. See position.reorder_pitting_drivers.
        if pitted_this_lap:
            raced_this_lap = reorder_pitting_drivers(raced_this_lap, cumulative_time_s, pitted_this_lap)

        # Real F1 prohibits overtaking under SC/VSC; skip resolution so the
        # only lap-time effect during those periods is pace (and, under full
        # SC, compression below), not position changes.
        clamped_this_lap: set[str] = set()
        if not (is_under_sc or is_under_vsc):
            raced_this_lap = resolve_positions(
                raced_this_lap,
                cumulative_time_s,
                this_lap_time_s,
                race_params.overtake_difficulty,
                rng,
                clamped_this_lap=clamped_this_lap,
            )

        if is_under_sc:
            compressed = compress_field_under_sc([cumulative_time_s[d] for d in raced_this_lap])
            for driver, new_time in zip(raced_this_lap, compressed, strict=True):
                cumulative_time_s[driver] = new_time

        gaps = compute_gaps_to_leader(raced_this_lap, cumulative_time_s)

        for position, driver in enumerate(raced_this_lap, start=1):
            record = laps_by_driver_lap[(driver, lap_number)]
            gap_ahead = prev_gap_to_ahead.get(driver)
            lap_states.append(
                LapState(
                    lap_number=lap_number,
                    driver=driver,
                    lap_time_s=this_lap_time_s[driver],
                    cumulative_time_s=cumulative_time_s[driver],
                    gap_to_leader_s=gaps[driver],
                    position=position,
                    compound=record.compound,
                    tyre_age=record.tyre_life,
                    in_dirty_air=(gap_ahead is not None and gap_ahead < DIRTY_AIR_FLAG_THRESHOLD_S),
                    pitted_this_lap=record.is_in_lap,
                    under_sc=is_under_sc,
                    stuck_behind_clamped=driver in clamped_this_lap,
                )
            )

        for driver in retiring_this_lap:
            active.discard(driver)
            notes.append(f"{driver}: retired after lap {lap_number} (real retirement, held exogenous)")

        order = [d for d in raced_this_lap if d in active] + [
            d for d in order if d not in raced_this_lap and d in active
        ]

        prev_gap_to_ahead = {}
        for i, driver in enumerate(raced_this_lap):
            prev_gap_to_ahead[driver] = (
                None if i == 0 else cumulative_time_s[driver] - cumulative_time_s[raced_this_lap[i - 1]]
            )

    classification = _final_classification(tuple(lap_states))

    return SimulationResult(
        race_key=snapshot.race_key,
        decisions_applied=(),
        lap_states=tuple(lap_states),
        classification=classification,
        diverged_from_lap=None,
        rng_seed=seed,
        notes=tuple(notes),
    )
