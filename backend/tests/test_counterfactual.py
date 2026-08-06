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
from pitwall.counterfactual.strategy import add_pit_stop_extrapolation_laps, apply_decision  # noqa: E402
from pitwall.domain.decision import AddPitStop, ChangePitLap  # noqa: E402
from pitwall.domain.enums import Compound  # noqa: E402
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


# ---------------------------------------------------------------------------
# AddPitStop (spec 5.3). Built before RemovePitStop deliberately: adding a
# stop *shortens* the stints it splits, so every simulated lap sits at a
# tyre age the driver's own data already covers (interpolation), whereas
# removing one extrapolates past the longest observed stint. See
# DECISIONS.md and strategy.py's module docstring.
# ---------------------------------------------------------------------------


def test_add_pit_stop_splits_the_stint_and_resets_tyre_age(hungary_2019):
    # VER's real second stint runs laps 26-67 on HARDs. Adding a stop on
    # lap 50 should make 50 an in-lap on the old compound, then start a
    # fresh SOFT stint from 51 with tyre age counting from 1.
    snapshot, _ = hungary_2019
    decision = AddPitStop(driver="VER", lap=50, compound=Compound.SOFT)
    overrides = apply_decision(snapshot, decision)

    real_by_key = {(lap.driver, lap.lap_number): lap for lap in snapshot.laps}
    assert overrides[("VER", 50)].is_in_lap
    assert overrides[("VER", 50)].compound == real_by_key[("VER", 50)].compound  # still the old tyre
    assert overrides[("VER", 51)].is_out_lap
    assert overrides[("VER", 51)].compound == Compound.SOFT
    assert overrides[("VER", 51)].tyre_life == 1
    assert overrides[("VER", 55)].tyre_life == 5
    assert overrides[("VER", 55)].compound == Compound.SOFT


def test_add_pit_stop_shortened_original_stint_stays_within_observed_range(hungary_2019):
    # The part of "adding a stop is interpolation" that IS true: every lap
    # of the *shortened original* stint sits at a tyre age the driver
    # already ran, because shortening can only reduce the ages requested.
    snapshot, _ = hungary_2019
    decision = AddPitStop(driver="VER", lap=50, compound=Compound.SOFT)
    overrides = apply_decision(snapshot, decision)

    max_real_age_by_compound: dict[Compound, int] = {}
    for lap in snapshot.laps:
        if lap.driver != "VER":
            continue
        current = max_real_age_by_compound.get(lap.compound, 0)
        max_real_age_by_compound[lap.compound] = max(current, lap.tyre_life)

    original_stint_laps = {
        lap_number: o for (_, lap_number), o in overrides.items() if lap_number <= decision.lap
    }
    assert original_stint_laps
    for lap_number, overridden in original_stint_laps.items():
        observed_max = max_real_age_by_compound[overridden.compound]
        assert overridden.tyre_life <= observed_max, (
            f"lap {lap_number}: shortening a stint should never raise the tyre age requested, "
            f"but got {overridden.tyre_life} > observed max {observed_max}"
        )


def test_add_pit_stop_reports_new_stint_extrapolation_rather_than_hiding_it(hungary_2019):
    # The part that ISN'T true, pinned as a measured limitation: the new
    # stint runs to the next real stop and can far exceed the driver's real
    # sample on that compound. VER ran SOFT for only 6 laps in 2019 Hungary,
    # so a SOFT stint from lap 51 to 66 asks for ages well past that. This
    # must be reported, not silently answered.
    snapshot, _ = hungary_2019
    decision = AddPitStop(driver="VER", lap=50, compound=Compound.SOFT)

    extrapolated = add_pit_stop_extrapolation_laps(snapshot, decision)
    assert extrapolated > 0, "expected this case to extrapolate; if not, the premise here changed"

    # A short new stint on a compound the driver ran extensively should not
    # extrapolate at all -- confirms the helper discriminates rather than
    # always reporting a positive number.
    ver_hard_max = max(
        lap.tyre_life for lap in snapshot.laps if lap.driver == "VER" and lap.compound == Compound.HARD
    )
    assert ver_hard_max > 10  # sanity: VER's real HARD stint was long
    short_hard = AddPitStop(driver="VER", lap=60, compound=Compound.HARD)
    assert add_pit_stop_extrapolation_laps(snapshot, short_hard) == 0


def test_add_pit_stop_rejects_a_lap_already_in_a_real_pit_sequence(hungary_2019):
    snapshot, _ = hungary_2019
    with pytest.raises(ValueError):
        apply_decision(snapshot, AddPitStop(driver="VER", lap=67, compound=Compound.SOFT))  # real in-lap


def test_add_pit_stop_rejects_a_lap_with_no_room_before_the_next_real_stop(hungary_2019):
    # VER's next real stop after his lap-26 out-lap is lap 67; adding one on
    # lap 66 leaves no room for an out-lap before it.
    snapshot, _ = hungary_2019
    with pytest.raises(ValueError):
        apply_decision(snapshot, AddPitStop(driver="VER", lap=66, compound=Compound.SOFT))


def test_add_pit_stop_runs_end_to_end_and_costs_time_in_the_near_term(hungary_2019):
    # An extra stop is a real time loss on the laps around it. Checked
    # deterministically (noise off) so this asserts the mechanism, not a
    # lucky sample: VER's cumulative time a few laps after the added stop
    # must exceed the override-free fork's at the same lap.
    snapshot, params = hungary_2019
    decision = AddPitStop(driver="VER", lap=50, compound=Compound.SOFT)
    with_stop = simulate_counterfactual(snapshot, params, decision, seed=0, include_noise=False)
    without = fork_and_simulate(
        snapshot, params, overrides={}, first_affected_lap=decision.first_affected_lap, seed=0, include_noise=False
    )

    def cumulative(result, lap_number):
        return next(
            (s.cumulative_time_s for s in result.lap_states if s.driver == "VER" and s.lap_number == lap_number),
            None,
        )

    with_stop_t, without_t = cumulative(with_stop, 53), cumulative(without, 53)
    assert with_stop_t is not None and without_t is not None
    assert with_stop_t > without_t, "an added pit stop must cost time in the laps immediately following it"


def test_shifting_a_stop_renumbers_the_following_stint_through_its_own_in_lap(hungary_2019):
    """The affected range must include the driver's *next* real stop, because
    that lap belongs to the stint being shifted.

    Found by auditing generated fixtures: 2019 Hungary BOT really stopped on
    laps 5 and 46. Shifting the first stop to lap 20 renumbered the HARD stint
    from lap 21 (age 1) but stopped at lap 45 (age 25), leaving lap 46 with
    reality's age of 41 — a tyre ageing 16 laps in one lap, and a lap simulated
    at the wrong pace on every candidate that moves a stop with another stop
    after it.

    The stop must still happen exactly where reality put it. Both halves are
    asserted: contiguous ages, and the in-lap preserved.
    """
    snapshot, _ = hungary_2019
    overrides = apply_decision(snapshot, ChangePitLap(driver="BOT", original_lap=5, new_lap=20))

    real = {lap.lap_number: lap for lap in snapshot.laps if lap.driver == "BOT"}
    effective = {lap: overrides.get(("BOT", lap), real.get(lap)) for lap in sorted(real)}

    # Lap 46 is BOT's next real stop and must still be an in-lap.
    assert effective[46].is_in_lap, "the following real stop was overwritten"
    assert ("BOT", 46) in overrides, "the following stop's lap was never renumbered"

    # Tyre age must advance by exactly one lap at a time within a stint.
    for lap in range(21, 47):
        previous, current = effective[lap - 1], effective[lap]
        if previous.compound == current.compound and not previous.is_in_lap:
            assert current.tyre_life == previous.tyre_life + 1, (
                f"lap {lap}: tyre age jumped {previous.tyre_life} -> {current.tyre_life}"
            )
