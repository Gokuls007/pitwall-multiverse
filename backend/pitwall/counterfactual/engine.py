"""Fork-and-resimulate counterfactual engine (spec Part 9.1).

Everything before `decision.first_affected_lap` is copied verbatim from
reality (steps 3-4); simulation state (cumulative time, track position,
active drivers) is initialised from real values at the end of the lap
before that (step 5) — this is what gives the counterfactual its
credibility per spec 9.1's own framing: divergence is attributable to the
decision, not to accumulated simulation drift from lap 1. Built on the same
lap-time/position/overtake machinery as `simulation/engine.py`'s replay
loop, not a separate reimplementation of it.
"""

from __future__ import annotations

from pitwall.counterfactual.strategy import apply_decision
from pitwall.domain.decision import Decision
from pitwall.domain.race import RaceParameters, RaceSnapshot
from pitwall.domain.result import LapState, SimulationResult
from pitwall.simulation.engine import DIRTY_AIR_FLAG_THRESHOLD_S, _final_classification, _track_status_for_lap
from pitwall.simulation.lap_time import compose_lap_time_s
from pitwall.simulation.pit import pit_stop_noise_s
from pitwall.simulation.position import compute_gaps_to_leader, reorder_pitting_drivers, resolve_positions
from pitwall.simulation.rng import make_rng
from pitwall.simulation.safety_car import compress_field_under_sc
from pitwall.validation.metrics import real_cumulative_times


def simulate_counterfactual(
    snapshot: RaceSnapshot,
    race_params: RaceParameters,
    decision: Decision,
    seed: int,
    include_noise: bool = False,
) -> SimulationResult:
    """`include_noise` defaults to False here, opposite of
    `simulation.engine.simulate_replay` — a counterfactual answer is the
    model's deterministic pace prediction plus genuinely modelled overtake
    uncertainty (still drawn from `rng` regardless), not a noisy
    realisation of it; see `lap_time.compose_lap_time_s`'s docstring.
    """
    rng = make_rng(seed)
    overrides = apply_decision(snapshot, decision)
    first_affected_lap = decision.first_affected_lap

    real_by_driver_lap = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    drivers_with_laps = sorted({lap.driver for lap in snapshot.laps})
    grid_position = {d.code: d.grid_position for d in snapshot.drivers}
    retired_on_lap = {d.code: d.retired_on_lap for d in snapshot.drivers}
    real_cum = real_cumulative_times(snapshot)

    lap_states: list[LapState] = []
    notes: list[str] = [f"Applied {decision!r}, diverging from lap {first_affected_lap}."]

    # --- Verbatim real portion (spec 9.1 step 4): laps before the fork ---
    for lap in snapshot.laps:
        if lap.lap_number >= first_affected_lap or lap.lap_time_s is None:
            continue
        gap_ahead = lap.gap_to_ahead_s
        lap_states.append(
            LapState(
                lap_number=lap.lap_number,
                driver=lap.driver,
                lap_time_s=lap.lap_time_s,
                cumulative_time_s=real_cum[lap.driver][lap.lap_number],
                gap_to_leader_s=(
                    real_cum[lap.driver][lap.lap_number]
                    - min(real_cum[d][lap.lap_number] for d in real_cum if lap.lap_number in real_cum[d])
                ),
                position=lap.position,
                compound=lap.compound,
                tyre_age=lap.tyre_life,
                in_dirty_air=(gap_ahead is not None and gap_ahead < DIRTY_AIR_FLAG_THRESHOLD_S),
                pitted_this_lap=lap.is_in_lap,
                under_sc=_track_status_for_lap(snapshot, lap.lap_number)[0],
                stuck_behind_clamped=False,
            )
        )

    # --- Initialise forward-simulation state from real values at the end
    # of the lap immediately before the fork (spec 9.1 step 5) ---
    fork_reference_lap = first_affected_lap - 1
    active = {
        driver
        for driver in drivers_with_laps
        if retired_on_lap.get(driver) is None or retired_on_lap[driver] >= fork_reference_lap
    }
    if fork_reference_lap >= 1:
        cumulative_time_s = {driver: real_cum.get(driver, {}).get(fork_reference_lap, 0.0) for driver in active}
        # Track position is authoritative (spec 7.2), not a re-sort of raw
        # cumulative time — the two can legitimately disagree. Use the real
        # classification position recorded on that lap, exactly as reality
        # had it, rather than re-deriving an order our own sort might get
        # subtly wrong.
        real_position_at_fork = {
            lap.driver: lap.position
            for lap in snapshot.laps
            if lap.lap_number == fork_reference_lap and lap.driver in active and lap.position > 0
        }
        order = sorted(active, key=lambda d: real_position_at_fork.get(d, 999))
        prev_gap_to_ahead: dict[str, float | None] = {}
        for i, driver in enumerate(order):
            prev_gap_to_ahead[driver] = (
                None if i == 0 else cumulative_time_s[driver] - cumulative_time_s[order[i - 1]]
            )
    else:
        # Fork at or before lap 1: nothing real to anchor to, start from grid.
        cumulative_time_s = dict.fromkeys(active, 0.0)
        order = sorted(active, key=lambda d: grid_position.get(d, 999))
        prev_gap_to_ahead = dict.fromkeys(active, None)

    # --- Forward simulation from the fork (spec 9.1 step 6) ---
    for lap_number in range(max(first_affected_lap, 1), snapshot.total_laps + 1):
        is_under_sc, is_under_vsc = _track_status_for_lap(snapshot, lap_number)
        this_lap_time_s: dict[str, float] = {}
        retiring_this_lap: list[str] = []
        pitted_this_lap: set[str] = set()

        for driver in order:
            if driver not in active:
                continue
            record = overrides.get((driver, lap_number), real_by_driver_lap.get((driver, lap_number)))
            if record is None:
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
                    notes.append(f"{driver}: no fitted TyreModel at all, skipped lap {lap_number}")
                    continue
                fallback_model = max(driver_params.tyre_models.values(), key=lambda tm: tm.n_observations)
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

        if pitted_this_lap:
            raced_this_lap = reorder_pitting_drivers(raced_this_lap, cumulative_time_s, pitted_this_lap)

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
            record = overrides.get((driver, lap_number), real_by_driver_lap[(driver, lap_number)])
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
        decisions_applied=(decision,),
        lap_states=tuple(lap_states),
        classification=classification,
        diverged_from_lap=first_affected_lap,
        rng_seed=seed,
        notes=tuple(notes),
    )
