"""Counterfactual engine tests (spec Part 9). The no-op test is the
load-bearing one and is written first.

A no-op counterfactual (a `Decision` that changes nothing relative to
reality) forked at lap N is *the same computation* as `fork_and_simulate`
called directly with no overrides at all, forked at lap N, same seed, same
code path — the "closed-loop replay forked at lap N with the real
strategy" the fork machinery must reduce to when there's no actual
decision. These two must match byte-for-byte, not within a drift-horizon
tolerance: a tolerance built from the expected pace-model drift (DECISIONS.md:
adjacent-pair gap error grows as roughly `0.835 * sqrt(laps elapsed)`) would
only catch a fork-mechanics bug large enough to exceed that budget — e.g. a
~20s tolerance at a 22-laps-remaining fork would pass even if the fork
machinery lost a driver an entire pit stop's worth of time. Comparing
against the override-free reference directly isolates drift the fork
mechanics themselves introduce from drift that's inherent to simulating
forward at all, and would have caught both real bugs found while building
this (see DECISIONS.md) as a hard mismatch rather than a tolerance judgement.
"""

from __future__ import annotations

import warnings

import pytest

warnings.filterwarnings("ignore")

from pitwall.counterfactual.engine import fork_and_simulate, simulate_counterfactual  # noqa: E402
from pitwall.counterfactual.strategy import apply_decision  # noqa: E402
from pitwall.domain.decision import ChangePitLap  # noqa: E402
from pitwall.ingestion.catalogue import get_entry  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_catalogue_with_pooled_dirty_air  # noqa: E402


@pytest.fixture(scope="module")
def hungary_2019():
    entry = get_entry("2019_hungarian")
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    params = fit_catalogue_with_pooled_dirty_air([snapshot])[snapshot.race_key]
    return snapshot, params


def test_no_op_pit_lap_change_matches_override_free_fork_exactly_late(hungary_2019):
    # HAM's real second stop, 2019 Hungary: lap 48 of 70 -- 22 laps
    # remaining.
    snapshot, params = hungary_2019
    decision = ChangePitLap(driver="HAM", original_lap=48, new_lap=48)
    no_op_result = simulate_counterfactual(snapshot, params, decision, seed=0, include_noise=False)
    reference_result = fork_and_simulate(
        snapshot, params, overrides={}, first_affected_lap=decision.first_affected_lap, seed=0, include_noise=False
    )

    assert no_op_result.lap_states == reference_result.lap_states
    assert no_op_result.classification == reference_result.classification


def test_no_op_pit_lap_change_matches_override_free_fork_exactly_early(hungary_2019):
    # BOT's real first stop, 2019 Hungary: lap 5 of 70 -- 65 laps
    # remaining. Same exact-match requirement forked much earlier, where a
    # fork-mechanics bug would have more laps to compound and be easier to
    # spot if the assertion were loose instead of exact.
    snapshot, params = hungary_2019
    decision = ChangePitLap(driver="BOT", original_lap=5, new_lap=5)
    no_op_result = simulate_counterfactual(snapshot, params, decision, seed=0, include_noise=False)
    reference_result = fork_and_simulate(
        snapshot, params, overrides={}, first_affected_lap=decision.first_affected_lap, seed=0, include_noise=False
    )

    assert no_op_result.lap_states == reference_result.lap_states
    assert no_op_result.classification == reference_result.classification


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
