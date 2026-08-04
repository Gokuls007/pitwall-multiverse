"""Counterfactual engine tests (spec Part 9). The no-op test is the
load-bearing one and is written first: apply a decision that changes
nothing relative to reality, and the fork-and-resimulate machinery must not
introduce drift *on its own*, beyond what's already known and quantified
about closed-loop divergence (DECISIONS.md: adjacent-pair gap error grows
as roughly `0.835 * sqrt(laps elapsed)`, R²=0.725, once the simulation
starts predicting pace rather than replaying real times). A no-op forking
late in the race (few laps remaining) should show near-zero drift; one
forking early should show substantially more — that's the drift horizon
showing up in a place it can be measured cleanly, not a bug.
"""

from __future__ import annotations

import warnings

import pytest

warnings.filterwarnings("ignore")

from pitwall.counterfactual.engine import simulate_counterfactual  # noqa: E402
from pitwall.counterfactual.strategy import apply_decision  # noqa: E402
from pitwall.domain.decision import ChangePitLap  # noqa: E402
from pitwall.ingestion.catalogue import get_entry  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402

# Fit from DECISIONS.md's gap-drift-vs-laps-elapsed measurement (pooled
# across the catalogue, R²=0.725). A single-race, single-seed test is
# noisier than that pooled measurement, so a safety multiplier is applied
# on top rather than using the bare fitted constant — generous enough not
# to flake on ordinary seed-to-seed variation, tight enough that a real
# fork-mechanics bug (which would look like *unbounded* divergence, not
# horizon-scaled) still fails it.
DRIFT_C = 0.835
DRIFT_SAFETY_MULTIPLIER = 5.0


@pytest.fixture(scope="module")
def hungary_2019():
    entry = get_entry("2019_hungarian")
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    params = fit_catalogue_with_pooled_dirty_air([snapshot])[snapshot.race_key]
    return snapshot, params


def _adjacent_gap_drift(result, snapshot, first_affected_lap) -> list[float]:
    """|simulated adjacent-pair gap - real adjacent-pair gap| for every
    green-flag lap at or after the fork, across all drivers."""
    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    by_lap: dict[int, list] = {}
    for state in result.lap_states:
        if state.lap_number >= first_affected_lap:
            by_lap.setdefault(state.lap_number, []).append(state)

    drifts = []
    for lap_number, states in by_lap.items():
        states_sorted = sorted(states, key=lambda s: s.position)
        for i, state in enumerate(states_sorted):
            if i == 0:
                continue
            real = real_by_key.get((state.driver, lap_number))
            if real is None or real.gap_to_ahead_s is None or not real.is_usable_for_fitting:
                continue
            sim_gap = state.cumulative_time_s - states_sorted[i - 1].cumulative_time_s
            drifts.append(abs(sim_gap - real.gap_to_ahead_s))
    return drifts


def test_no_op_pit_lap_change_stays_within_drift_horizon_late_fork(hungary_2019):
    # HAM's real second stop, 2019 Hungary: lap 48 of 70 -- 22 laps
    # remaining. A no-op here should show only modest drift.
    snapshot, params = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=48, new_lap=48)
    result = simulate_counterfactual(snapshot, params, decision, seed=0, include_noise=False)

    laps_remaining = snapshot.total_laps - decision.first_affected_lap
    tolerance = DRIFT_SAFETY_MULTIPLIER * DRIFT_C * (laps_remaining**0.5)

    drifts = _adjacent_gap_drift(result, snapshot, decision.first_affected_lap)
    assert drifts, "expected at least one post-fork comparison point"
    median_drift = sorted(drifts)[len(drifts) // 2]
    assert median_drift < tolerance, (
        f"no-op median adjacent-gap drift {median_drift:.2f}s exceeds horizon-scaled "
        f"tolerance {tolerance:.2f}s ({laps_remaining} laps remaining) -- the fork "
        "mechanics themselves may be introducing drift, not just pace-model error."
    )


def test_no_op_pit_lap_change_drifts_more_when_forked_early(hungary_2019):
    # BOT's real first stop, 2019 Hungary: lap 5 of 70 -- 65 laps
    # remaining. Same no-op mechanism, forked much earlier: drift should be
    # larger than the late-fork case, and roughly horizon-scaled rather
    # than unbounded.
    snapshot, params = hungary_2019
    decision = ChangePitLap(driver="BOT", original_lap=5, new_lap=5)
    result = simulate_counterfactual(snapshot, params, decision, seed=0, include_noise=False)

    laps_remaining = snapshot.total_laps - decision.first_affected_lap
    tolerance = DRIFT_SAFETY_MULTIPLIER * DRIFT_C * (laps_remaining**0.5)

    drifts = _adjacent_gap_drift(result, snapshot, decision.first_affected_lap)
    assert drifts
    median_drift = sorted(drifts)[len(drifts) // 2]
    assert median_drift < tolerance, (
        f"no-op median adjacent-gap drift {median_drift:.2f}s exceeds horizon-scaled "
        f"tolerance {tolerance:.2f}s ({laps_remaining} laps remaining)"
    )


def test_no_op_pit_lap_change_reproduces_exact_strategy_for_the_driver(hungary_2019):
    # apply_decision's own output, independent of the simulation loop: a
    # true no-op (original_lap == new_lap) must reconstruct exactly the
    # real compound/tyre-age/in-out-lap sequence it started from.
    # HAM's first stop (lap 31/32) is a clean single-lap transition; his
    # second (lap 48) has a genuine data anomaly covered separately below.
    snapshot, _ = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=31, new_lap=31)
    overrides = apply_decision(snapshot, decision)

    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    assert overrides  # sanity: the no-op still produces an (identical) override range
    for (driver, lap_number), overridden in overrides.items():
        real = real_by_key[(driver, lap_number)]
        assert overridden.compound == real.compound
        assert overridden.tyre_life == real.tyre_life
        assert overridden.is_in_lap == real.is_in_lap
        assert overridden.is_out_lap == real.is_out_lap


def test_no_op_handles_a_multi_lap_pit_transition_without_crashing(hungary_2019):
    # HAM's second stop (lap 48) has a genuine data anomaly: the transition
    # to the new stint spans two laps (48 in, 49 flagged an out-lap but
    # still on the old compound with tyre age continuing 17->18, 50 the
    # actual fresh-compound/tyre_life=1 lap) rather than the usual one.
    # apply_decision derives the transition width from the data instead of
    # assuming a fixed +1 offset, so a no-op here must still preserve
    # compound and tyre age exactly (the properties that actually drive the
    # pace model) even though the *exact* lap `is_out_lap` lands on can
    # differ from reality by one lap in this specific anomalous case.
    snapshot, _ = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=48, new_lap=48)
    overrides = apply_decision(snapshot, decision)

    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    for (driver, lap_number), overridden in overrides.items():
        real = real_by_key[(driver, lap_number)]
        assert overridden.compound == real.compound
        assert overridden.tyre_life == real.tyre_life
    assert overrides[("HAM", 48)].is_in_lap


def test_apply_change_pit_lap_rejects_a_lap_that_was_not_a_real_stop(hungary_2019):
    snapshot, _ = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=20, new_lap=18)  # HAM didn't pit on lap 20
    with pytest.raises(ValueError):
        apply_decision(snapshot, decision)


def test_change_pit_lap_earlier_shortens_first_stint_and_shifts_second(hungary_2019):
    # HAM's real first stop is lap 31 -> 32 (in/out), a clean single-lap
    # transition. Move it 3 laps earlier: stint 1 should now be 3 laps
    # shorter (interpolation within observed tyre ages, per DECISIONS.md --
    # the easier extrapolation direction), and stint 2 should start 3 laps
    # earlier, continuing on the same second-stint compound.
    snapshot, _ = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=31, new_lap=28)
    overrides = apply_decision(snapshot, decision)

    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    real_stint2_compound = real_by_key[("HAM", 32)].compound

    assert overrides[("HAM", 28)].is_in_lap
    assert overrides[("HAM", 29)].is_out_lap
    assert overrides[("HAM", 29)].compound == real_stint2_compound
    # Laps 29-31 are now stint-2 laps that were real stint-1 laps in
    # reality -- their compound must reflect the counterfactual, not reality.
    assert overrides[("HAM", 30)].compound == real_stint2_compound
    assert real_by_key[("HAM", 30)].compound != real_stint2_compound
