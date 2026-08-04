"""Phase 3 acceptance tests: the simulation engine (spec Part 7, Part 13).

Priorities per Part 13: unit tests per lap-time component, property tests
(monotonicity), the determinism test, and the safety-car compression case
from spec 6.8. The no-op-counterfactual test and full ensemble machinery are
Phase 4 scope (there is no counterfactual engine yet — Phase 3 only replays
real strategy).
"""

from __future__ import annotations

import numpy as np
import pytest

from pitwall.domain.driver import DriverParams, TyreModel
from pitwall.domain.enums import Compound
from pitwall.domain.race import DirtyAirModel
from pitwall.simulation import lap_time, overtake, position, safety_car
from pitwall.simulation.rng import make_rng


def _tyre_model(compound=Compound.MEDIUM, offset=0.0, slope=0.05) -> TyreModel:
    return TyreModel(
        compound=compound,
        base_offset_s=offset,
        linear_deg_s_per_lap=slope,
        cliff_lap=None,
        cliff_deg_s_per_lap=None,
        r_squared=0.8,
        n_observations=20,
    )


def _driver_params(base_pace_s=90.0, pace_std_s=0.0) -> DriverParams:
    return DriverParams(
        driver="XXX",
        base_pace_s=base_pace_s,
        pace_std_s=pace_std_s,
        tyre_models={
            Compound.SOFT: _tyre_model(Compound.SOFT, offset=-0.3, slope=0.08),
            Compound.MEDIUM: _tyre_model(Compound.MEDIUM, offset=0.0, slope=0.05),
            Compound.HARD: _tyre_model(Compound.HARD, offset=0.3, slope=0.02),
        },
        overtake_skill=0.5,
        defence_skill=0.5,
    )


# ---------------------------------------------------------------------------
# Per-component lap-time tests (spec 6.1, Part 13)
# ---------------------------------------------------------------------------


def test_base_pace_is_driver_params_value():
    dp = _driver_params(base_pace_s=91.5)
    assert lap_time.base_pace_s(dp) == 91.5


def test_tyre_degradation_increases_with_age():
    dp = _driver_params()
    d0 = lap_time.tyre_degradation_s(dp, Compound.MEDIUM, 0)
    d10 = lap_time.tyre_degradation_s(dp, Compound.MEDIUM, 10)
    d20 = lap_time.tyre_degradation_s(dp, Compound.MEDIUM, 20)
    assert d0 < d10 < d20


def test_tyre_degradation_missing_compound_raises():
    dp = _driver_params()
    with pytest.raises(ValueError):
        lap_time.tyre_degradation_s(dp, Compound.WET, 5)


def test_compound_offset_reflects_fitted_value():
    dp = _driver_params()
    assert lap_time.compound_offset_s(dp, Compound.SOFT) == -0.3
    assert lap_time.compound_offset_s(dp, Compound.HARD) == 0.3


def test_fuel_effect_is_negative_and_monotonic_in_lap_number():
    # Later laps (more fuel burned) must be faster (more negative contribution).
    early = lap_time.fuel_effect_s(0.05, lap_number=1)
    late = lap_time.fuel_effect_s(0.05, lap_number=50)
    assert early < 0
    assert late < early  # more negative = faster


def test_dirty_air_penalty_decreases_with_gap():
    model = DirtyAirModel(max_penalty_s=0.5, decay_scale_s=1.0, r_squared=0.2, n_observations=100)
    close = lap_time.dirty_air_and_traffic_penalty_s(model, 0.2)
    medium = lap_time.dirty_air_and_traffic_penalty_s(model, 1.0)
    far = lap_time.dirty_air_and_traffic_penalty_s(model, 5.0)
    none_ = lap_time.dirty_air_and_traffic_penalty_s(model, None)
    assert close > medium > far >= 0
    assert none_ == 0.0


def test_sc_vsc_multiplier_selection():
    assert lap_time.sc_vsc_multiplier(True, False, 1.5, 1.3) == 1.5
    assert lap_time.sc_vsc_multiplier(False, True, 1.5, 1.3) == 1.3
    assert lap_time.sc_vsc_multiplier(False, False, 1.5, 1.3) == 1.0


def test_pit_lane_time_only_applies_on_in_or_out_lap():
    assert lap_time.pit_lane_time_s(20.0, is_in_lap=False, is_out_lap=False) == 0.0
    assert lap_time.pit_lane_time_s(20.0, is_in_lap=True, is_out_lap=False) == 10.0
    assert lap_time.pit_lane_time_s(20.0, is_in_lap=False, is_out_lap=True) == 10.0


def test_pit_lane_time_scaled_under_sc():
    # Spec 6.8 point 3: pit stops are much cheaper under SC.
    green = lap_time.pit_lane_time_s(20.0, True, False, sc_vsc_active_multiplier=1.0)
    under_sc = lap_time.pit_lane_time_s(20.0, True, False, sc_vsc_active_multiplier=1.5)
    assert under_sc == pytest.approx(green * 1.5)


def test_noise_is_deterministic_given_seed():
    rng1 = make_rng(123)
    rng2 = make_rng(123)
    assert lap_time.noise_s(rng1, 0.3) == lap_time.noise_s(rng2, 0.3)


def test_noise_zero_when_std_zero():
    rng = make_rng(1)
    assert lap_time.noise_s(rng, 0.0) == 0.0


def test_compose_lap_time_combines_all_terms_and_is_deterministic():
    dp = _driver_params(pace_std_s=0.2)
    model = DirtyAirModel(max_penalty_s=0.3, decay_scale_s=1.0, r_squared=0.1, n_observations=50)
    kwargs = dict(
        driver_params=dp,
        compound=Compound.MEDIUM,
        tyre_age=10,
        lap_number=20,
        fuel_effect_s_per_lap=0.05,
        dirty_air_model=model,
        gap_to_ahead_s=0.5,
        is_under_sc=False,
        is_under_vsc=False,
        sc_lap_time_multiplier=1.5,
        vsc_lap_time_multiplier=1.3,
        pit_lane_loss_s=20.0,
        is_in_lap=False,
        is_out_lap=False,
    )
    t1 = lap_time.compose_lap_time_s(rng=make_rng(99), **kwargs)
    t2 = lap_time.compose_lap_time_s(rng=make_rng(99), **kwargs)
    assert t1 == t2
    # Sanity: should be in the right ballpark (base ~90 + small terms), not
    # dominated by some runaway term.
    assert 85 < t1 < 95


# ---------------------------------------------------------------------------
# Overtake model (spec 6.7)
# ---------------------------------------------------------------------------


def test_pass_probability_zero_when_not_faster():
    assert overtake.pass_probability(0.0, overtake_difficulty=0.2) == 0.0
    assert overtake.pass_probability(-0.5, overtake_difficulty=0.2) == 0.0


def test_pass_probability_monotonic_increasing_in_pace_delta():
    low = overtake.pass_probability(0.1, overtake_difficulty=0.3)
    mid = overtake.pass_probability(0.5, overtake_difficulty=0.3)
    high = overtake.pass_probability(2.0, overtake_difficulty=0.3)
    assert low < mid < high


def test_pass_probability_monotonic_decreasing_in_difficulty():
    easy = overtake.pass_probability(1.0, overtake_difficulty=0.1)
    hard = overtake.pass_probability(1.0, overtake_difficulty=0.9)
    assert hard < easy


def test_pass_probability_bounded():
    prob = overtake.pass_probability(100.0, overtake_difficulty=0.0)
    assert 0.0 <= prob <= overtake.MAX_PASS_PROBABILITY


def test_resolve_pass_deterministic_given_seed():
    rng1 = make_rng(5)
    rng2 = make_rng(5)
    results1 = [overtake.resolve_pass(rng1, 0.5) for _ in range(20)]
    results2 = [overtake.resolve_pass(rng2, 0.5) for _ in range(20)]
    assert results1 == results2


# ---------------------------------------------------------------------------
# Safety car field compression (spec 6.8) — required Phase 3 test
# ---------------------------------------------------------------------------


def test_safety_car_closes_large_gap_at_bounded_rate_not_instantly():
    # A car twenty seconds behind cannot physically close that gap the
    # instant SC is shown (2019 Monaco: a real ~40s gap closed gradually
    # over the several laps of the SC period, not on the first lap of it).
    # One lap should close at most the declared max rate, not snap straight
    # to the following distance.
    times = [100.0, 120.0]
    compressed = safety_car.compress_field_under_sc(
        times, following_distance_s=1.5, max_gap_closure_s=15.0
    )
    assert compressed[1] - compressed[0] == pytest.approx(20.0 - 15.0)


def test_safety_car_does_not_widen_an_already_close_gap():
    times = [100.0, 100.8]
    compressed = safety_car.compress_field_under_sc(times, following_distance_s=1.5)
    assert compressed[1] - compressed[0] == pytest.approx(0.8)


def test_safety_car_never_overshoots_below_following_distance_in_one_lap():
    # A gap already within max_gap_closure_s of the following distance
    # should land exactly on the following distance, not undershoot past it.
    times = [100.0, 110.0]
    compressed = safety_car.compress_field_under_sc(
        times, following_distance_s=1.5, max_gap_closure_s=15.0
    )
    assert compressed[1] - compressed[0] == pytest.approx(1.5)


def test_safety_car_large_gap_converges_over_multiple_laps():
    # Reapplying compression lap after lap (as the engine does for the
    # duration of an SC period) should gradually converge a large gap down
    # to the following distance, never in a single step.
    gap = 40.0
    expected = [25.0, 10.0, 1.5]  # closes by 15 each lap, clamped at 1.5
    for expected_gap in expected:
        compressed = safety_car.compress_field_under_sc(
            [0.0, gap], following_distance_s=1.5, max_gap_closure_s=15.0
        )
        new_gap = compressed[1] - compressed[0]
        assert new_gap == pytest.approx(expected_gap)
        assert new_gap >= 1.5
        gap = new_gap


def test_safety_car_compresses_whole_field_sequentially():
    times = [0.0, 20.0, 40.0, 60.0]
    compressed = safety_car.compress_field_under_sc(
        times, following_distance_s=1.5, max_gap_closure_s=100.0
    )
    gaps = [compressed[i] - compressed[i - 1] for i in range(1, len(compressed))]
    assert all(g == pytest.approx(1.5) for g in gaps)


def test_safety_car_floors_gap_at_zero_when_track_order_disagrees_with_time():
    # Track position is authoritative and can legitimately disagree with raw
    # cumulative-time order (spec 7.2) — a car stuck behind can have a lower
    # cumulative time than the car ahead of it. Compression must never turn
    # that into a *decreasing* compressed time for the following car; that
    # would invert the very order the list represents and, since the result
    # is written back into running cumulative time, corrupt every later lap.
    times = [100.0, 99.0, 130.0]
    compressed = safety_car.compress_field_under_sc(times, following_distance_s=1.5)
    assert compressed[0] <= compressed[1] <= compressed[2]
    assert compressed[1] - compressed[0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Position resolution (spec 7.2) — track position authoritative
# ---------------------------------------------------------------------------


def test_position_resolution_is_probabilistic_not_automatic_on_time_crossover():
    # Even when the follower's cumulative time has already dropped below the
    # car ahead's (gap <= 0), the pass must go through resolve_pass, not an
    # automatic reorder — verified by driving probability to exactly 0 via
    # overtake_difficulty=1.0 (fully saturating) and confirming no swap.
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 99.0}  # B numerically ahead already
    lap_times = {"A": 91.0, "B": 89.0}  # B faster this lap
    rng = make_rng(1)
    new_order = position.resolve_positions(order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng)
    assert new_order == ["A", "B"]  # difficulty=1.0 -> ease=0 -> probability 0, no swap


def test_stuck_behind_car_clamped_to_minimum_following_gap():
    # B is faster this lap and would end up within the minimum following
    # gap of A, but the pass fails (difficulty 1.0 -> probability 0). B is
    # wheel-to-wheel with A and physically cannot close any further than
    # MIN_FOLLOWING_GAP_S without actually completing a pass.
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 100.1}  # would-be gap of 0.1s, below the floor
    lap_times = {"A": 91.0, "B": 89.0}  # B two seconds faster this lap
    rng = make_rng(1)
    new_order = position.resolve_positions(order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng)
    assert new_order == ["A", "B"]
    assert cumulative_times["B"] - cumulative_times["A"] == pytest.approx(position.MIN_FOLLOWING_GAP_S)
    assert lap_times["B"] == pytest.approx(89.0 + (position.MIN_FOLLOWING_GAP_S - 0.1))


def test_clamped_this_lap_records_actual_clamp_firing_not_a_heuristic():
    # The clamp's firing rate must be measured directly (this set), not
    # inferred after the fact from exact-tied lap times -- the floor clamp
    # (unlike an earlier equality-based version) only rarely produces one.
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 100.1}
    lap_times = {"A": 91.0, "B": 89.0}
    rng = make_rng(1)
    clamped = set()
    position.resolve_positions(
        order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng, clamped_this_lap=clamped
    )
    assert clamped == {"B"}


def test_clamped_this_lap_empty_when_gap_above_floor():
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 101.0}
    lap_times = {"A": 91.0, "B": 89.0}
    rng = make_rng(1)
    clamped = set()
    position.resolve_positions(
        order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng, clamped_this_lap=clamped
    )
    assert clamped == set()


def test_car_within_close_proximity_but_above_floor_is_not_clamped():
    # B is faster this lap and close behind A (within CLOSE_PROXIMITY_GAP_S,
    # so a pass is attempted), but the resulting gap (1.0s) is still well
    # above MIN_FOLLOWING_GAP_S — B is closing normally, not blocked, and a
    # failed pass attempt at this range must not clamp its genuine pace.
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 101.0}
    lap_times = {"A": 91.0, "B": 89.0}
    rng = make_rng(1)
    new_order = position.resolve_positions(order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng)
    assert new_order == ["A", "B"]
    assert lap_times["B"] == pytest.approx(89.0)
    assert cumulative_times["B"] == pytest.approx(101.0)


def test_blue_flag_lapped_backmarker_yields_near_certainly():
    # BACK is a lap down relative to LEADER (order[0]) and CHASER isn't;
    # BACK and CHASER are close on track. This should go through the
    # near-deterministic blue-flag yield, not the normal difficulty-gated
    # fight, and swap the overwhelming majority of the time.
    order = ["LEADER", "BACK", "CHASER"]
    swaps = 0
    n_trials = 40
    for seed in range(n_trials):
        cumulative_times = {"LEADER": 1000.0, "BACK": 1090.0, "CHASER": 1089.0}
        lap_times = {"LEADER": 90.0, "BACK": 95.0, "CHASER": 80.0}
        rng = make_rng(seed)
        new_order = position.resolve_positions(
            list(order), cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng
        )
        if new_order == ["LEADER", "CHASER", "BACK"]:
            swaps += 1
    assert swaps / n_trials >= 0.75  # BLUE_FLAG_YIELD_PROBABILITY is 0.9


def test_blue_flag_does_not_apply_to_two_cars_on_the_same_lap():
    # RIVAL is close behind LEADER but within a genuine lap of them (not a
    # lap down) -- a leader catching a car on the same lap must still race
    # it through the normal difficulty-gated fight, not blue flags, even
    # though the gap to LEADER is large in absolute terms.
    order = ["LEADER", "RIVAL"]
    cumulative_times = {"LEADER": 1000.0, "RIVAL": 1000.2}  # both mid-lap-90, not a lap apart
    lap_times = {"LEADER": 90.0, "RIVAL": 88.0}  # RIVAL faster this lap
    rng = make_rng(1)
    position.resolve_positions(list(order), cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng)
    # difficulty=1.0 means any genuine fight attempt fails and falls through
    # to the stuck-behind clamp (not blue-flag's near-certain yield) --
    # confirmed by the clamp firing (RIVAL's cumulative time floored, not a
    # 90% yield probability outcome).
    assert cumulative_times["RIVAL"] - cumulative_times["LEADER"] == pytest.approx(position.MIN_FOLLOWING_GAP_S)


def test_blue_flag_pair_never_triggers_stuck_behind_clamp():
    # Even when the blue-flag roll fails and BACK doesn't yield this lap,
    # CHASER (faster this lap) must not be clamped down to BACK's pace —
    # a slow backmarker failing to move over yet doesn't force the faster
    # car behind it down to backmarker pace the way a genuine rival would.
    order = ["LEADER", "BACK", "CHASER"]
    found_a_failure = False
    for seed in range(60):
        cumulative_times = {"LEADER": 1000.0, "BACK": 1090.0, "CHASER": 1089.0}
        lap_times = {"LEADER": 90.0, "BACK": 95.0, "CHASER": 80.0}
        rng = make_rng(seed)
        new_order = position.resolve_positions(
            list(order), cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng
        )
        if new_order == order:  # blue-flag roll failed this seed
            found_a_failure = True
            assert lap_times["CHASER"] == pytest.approx(80.0)
            assert cumulative_times["CHASER"] == pytest.approx(1089.0)
    assert found_a_failure  # sanity: the test actually exercised the failure branch


def test_stuck_behind_constraint_does_not_apply_when_not_close():
    # Same pace delta, but far enough apart that neither a pass attempt nor
    # the stuck-behind constraint applies — B's genuine pace advantage from a
    # lap where it wasn't blocking anyone should be left alone.
    order = ["A", "B"]
    cumulative_times = {"A": 100.0, "B": 110.0}
    lap_times = {"A": 91.0, "B": 89.0}
    rng = make_rng(1)
    position.resolve_positions(order, cumulative_times, lap_times, overtake_difficulty=1.0, rng=rng)
    assert lap_times["B"] == pytest.approx(89.0)
    assert cumulative_times["B"] == pytest.approx(110.0)


def test_position_resolution_can_swap_when_pass_succeeds():
    # Try several seeds; with difficulty=0 and a big pace delta, at least one
    # should produce a pass (probability is bounded below MAX, not 1.0).
    # Fresh dicts each iteration: resolve_positions mutates cumulative_times/
    # lap_times_this_lap in place (the stuck-behind clamp), so reusing them
    # across iterations would carry a failed attempt's clamp into the next
    # independent trial of the same lap.
    swapped = False
    for seed in range(30):
        cumulative_times = {"A": 100.0, "B": 100.5}
        lap_times = {"A": 91.0, "B": 88.0}  # B much faster
        rng = make_rng(seed)
        new_order = position.resolve_positions(
            ["A", "B"], cumulative_times, lap_times, overtake_difficulty=0.0, rng=rng
        )
        if new_order == ["B", "A"]:
            swapped = True
            break
    assert swapped


def test_compute_gaps_to_leader():
    order = ["A", "B", "C"]
    cumulative_times = {"A": 100.0, "B": 105.0, "C": 112.0}
    gaps = position.compute_gaps_to_leader(order, cumulative_times)
    assert gaps == {"A": 0.0, "B": 5.0, "C": 12.0}


# ---------------------------------------------------------------------------
# Property test (spec Part 13): a driver with strictly better pace and
# identical strategy never finishes behind, checked over an ensemble since
# overtaking is stochastic.
# ---------------------------------------------------------------------------


def test_faster_driver_with_identical_strategy_usually_finishes_ahead():
    """Two synthetic drivers, identical tyre/strategy, one strictly faster.
    Started with the faster car behind (the harder direction to prove) on an
    easy-to-pass circuit; over an ensemble of seeds it must come out ahead
    the large majority of the time."""
    from pitwall.domain.enums import Compound as C

    fast = _driver_params(base_pace_s=88.0)
    fast = DriverParams(**{**fast.__dict__, "driver": "FAST"})
    slow = _driver_params(base_pace_s=91.0)
    slow = DriverParams(**{**slow.__dict__, "driver": "SLOW"})

    order = ["SLOW", "FAST"]  # faster car starts behind
    ahead_count = 0
    n_trials = 40
    for seed in range(n_trials):
        rng = make_rng(seed)
        cumulative = {"SLOW": 0.0, "FAST": 0.5}  # start almost level, close enough to attempt
        current_order = list(order)
        for lap in range(1, 21):
            lap_times = {
                "SLOW": lap_time.compose_lap_time_s(
                    driver_params=slow,
                    compound=C.MEDIUM,
                    tyre_age=lap,
                    lap_number=lap,
                    fuel_effect_s_per_lap=0.05,
                    dirty_air_model=DirtyAirModel(0.0, 1.0, 0.0, 0),
                    gap_to_ahead_s=None,
                    is_under_sc=False,
                    is_under_vsc=False,
                    sc_lap_time_multiplier=1.0,
                    vsc_lap_time_multiplier=1.0,
                    pit_lane_loss_s=0.0,
                    is_in_lap=False,
                    is_out_lap=False,
                    rng=rng,
                ),
                "FAST": lap_time.compose_lap_time_s(
                    driver_params=fast,
                    compound=C.MEDIUM,
                    tyre_age=lap,
                    lap_number=lap,
                    fuel_effect_s_per_lap=0.05,
                    dirty_air_model=DirtyAirModel(0.0, 1.0, 0.0, 0),
                    gap_to_ahead_s=None,
                    is_under_sc=False,
                    is_under_vsc=False,
                    sc_lap_time_multiplier=1.0,
                    vsc_lap_time_multiplier=1.0,
                    pit_lane_loss_s=0.0,
                    is_in_lap=False,
                    is_out_lap=False,
                    rng=rng,
                ),
            }
            for driver in current_order:
                cumulative[driver] += lap_times[driver]
            current_order = position.resolve_positions(
                current_order, cumulative, lap_times, overtake_difficulty=0.1, rng=rng
            )
        if current_order[0] == "FAST":
            ahead_count += 1

    assert ahead_count / n_trials >= 0.9


# ---------------------------------------------------------------------------
# Engine-level integration tests (real data) — determinism is the Phase 3
# acceptance criterion; the rest are basic sanity checks. Accuracy against
# reality is what validation/ (the real Phase 3 acceptance gate) checks.
# ---------------------------------------------------------------------------

from functools import lru_cache  # noqa: E402

from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402
from pitwall.parameters.fit_all import fit_race_parameters  # noqa: E402
from pitwall.simulation.engine import simulate_replay  # noqa: E402


@lru_cache(maxsize=None)
def _snapshot_and_params(race_key: str):
    entry = next(e for e in CATALOGUE if e.race_key == race_key)
    snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
    return snapshot, fit_race_parameters(snapshot)


def test_engine_is_deterministic_on_real_data():
    """Spec Part 13: same seed, same output, byte-identical."""
    snapshot, params = _snapshot_and_params(CATALOGUE[0].race_key)
    result_a = simulate_replay(snapshot, params, seed=42)
    result_b = simulate_replay(snapshot, params, seed=42)
    assert result_a.lap_states == result_b.lap_states
    assert result_a.classification == result_b.classification


def test_engine_different_seeds_can_differ_on_real_data():
    snapshot, params = _snapshot_and_params(CATALOGUE[0].race_key)
    result_a = simulate_replay(snapshot, params, seed=1)
    result_b = simulate_replay(snapshot, params, seed=2)
    assert result_a.lap_states != result_b.lap_states


def test_engine_produces_a_classification_for_every_driver_with_laps():
    snapshot, params = _snapshot_and_params(CATALOGUE[0].race_key)
    result = simulate_replay(snapshot, params, seed=1)
    drivers_with_laps = {lap.driver for lap in snapshot.laps}
    classified_drivers = {driver for driver, _position in result.classification}
    assert classified_drivers == drivers_with_laps


def test_engine_classification_positions_are_a_permutation():
    snapshot, params = _snapshot_and_params(CATALOGUE[0].race_key)
    result = simulate_replay(snapshot, params, seed=1)
    positions = sorted(p for _driver, p in result.classification)
    assert positions == list(range(1, len(positions) + 1))
