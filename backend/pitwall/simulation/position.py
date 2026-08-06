"""Gap tracking and position resolution (spec 7.1 step 3-4, 7.2).

Spec 7.2's subtle but important rule: gaps derived from cumulative time and
positions resolved by overtaking can disagree — a car can be "ahead on
cumulative time" while stuck behind on track. **Track position is
authoritative**; cumulative time is only the input to gap calculation and to
deciding whether a pass is *attempted*, never used to silently reorder the
field. Getting this backwards produces the classic bug where cars teleport
past each other with no overtake ever modelled. Every position change here
goes through `overtake.pass_probability` / `resolve_pass` — even when a
following car's cumulative time has already dropped below the car ahead's
(which reads as "gap <= 0"), that only makes the pass *more likely to be
attempted*, not automatic.
"""

from __future__ import annotations

import numpy as np

from pitwall.simulation.overtake import pass_probability, resolve_pass
from pitwall.simulation.rng import DrawTable


def _roll_for(draws: DrawTable | None, rng, driver: str, lap_number: int | None):
    """The attacker's overtake roll source for this lap."""
    if draws is None or lap_number is None:
        return rng
    return draws.passing(driver, lap_number)

# Reuses the exact threshold `parameters/overtaking.py` fits circuit
# overtake_difficulty against, so the simulator's notion of "close enough to
# attempt a pass" matches the data the difficulty parameter was measured from.
# This is deliberately *not* the same distance as MIN_FOLLOWING_GAP_S below:
# 1.5s is "is a pass plausible" (DRS-range-ish), not "is this car physically
# unable to close further." A car 1.4s back is still closing; a car 0.3s
# back is in the leader's gearbox. Conflating the two made the stuck-behind
# clamp fire on every lap two cars spent anywhere within 1.5s of each other
# (25-64% of all green-flag laps, measured on the catalogue) instead of only
# when a car was genuinely blocked.
CLOSE_PROXIMITY_GAP_S = 1.5

# Fitted: the 5th percentile of observed real `gap_to_ahead_s` across the
# catalogue (green-flag laps, positive recorded gap) — 0.580s over 5,435
# laps, with per-race p5 tightly clustered at 0.50-0.77s. See
# `scripts/fit_min_following_gap.py`, which re-fits and fails loudly if this
# constant drifts more than 0.05 from the pooled value.
#
# This is load-bearing for product output, not an internal detail: whenever
# a counterfactual succeeds in bringing a car into contention the clamp pins
# the gap here, so this value *is* the margin the tool reports. It spent
# several passes as a 0.3s placeholder whose only support was a 9-sample
# bucket with a 0.335s standard error. Notably 0.3 turned out to sit near
# the *1st* percentile (0.323s) — i.e. "as close as cars ever momentarily
# get", which as a *sustained* floor let the simulator hold cars closer than
# real cars actually sustain. p5 rather than p1 is the deliberate choice:
# it excludes the extreme tail (momentary same-corner readings, timing
# artifacts) while still representing genuine wheel-to-wheel running.
MIN_FOLLOWING_GAP_S = 0.58

# Not fitted — a declared prior (Part 14 rule 1): real F1 requires blue-flag
# compliance, so a lapped car yields to a car un-lapping/lapping it
# near-immediately, rather than contesting it like a genuine fight for
# position. Not exactly 1.0 since real compliance sometimes takes a lap or
# two, not one corner, and this project's ingestion has no per-incident
# blue-flag-compliance-time measurement to fit against. Spec 6.9 gestures at
# lapped traffic ("additional cost for laps spent unable to pass a car not
# racing for position") but never built a distinct rule for it — without one,
# the stuck-behind constraint below has no way to distinguish a lapped
# backmarker from a genuine rival, and treats both as an ~1%-per-lap fight
# under a high-`overtake_difficulty` circuit, letting a single slow
# backmarker anchor a whole train of faster cars behind it indefinitely.
BLUE_FLAG_YIELD_PROBABILITY = 0.9


def _is_a_lap_down(
    driver: str, leader: str, cumulative_times: dict[str, float], lap_times_this_lap: dict[str, float]
) -> bool:
    if driver == leader:
        return False
    lap_estimate_s = lap_times_this_lap.get(leader, 0.0)
    if lap_estimate_s <= 0:
        return False
    return cumulative_times[driver] - cumulative_times[leader] >= lap_estimate_s


def resolve_positions(
    order: list[str],
    cumulative_times: dict[str, float],
    lap_times_this_lap: dict[str, float],
    overtake_difficulty: float,
    rng: np.random.Generator,
    clamped_this_lap: set[str] | None = None,
    # Common random numbers: when supplied, each attacker's overtake roll is
    # looked up by (driver, lap) instead of consumed from `rng` in call order,
    # so two paired runs draw the same number on any lap where nothing differs.
    # See simulation/rng.py. `rng` stays the fallback for callers without a
    # table (tests, and the noise-off validation replay where it never fires).
    draws: "DrawTable | None" = None,
    lap_number: int | None = None,
    pre_clamp_lap_times: dict[str, float] | None = None,
    clamp_penalty_this_lap: dict[str, float] | None = None,
) -> list[str]:
    """One left-to-right pass over adjacent pairs in current track-position
    order. Each pair is checked at most once per lap (no chained re-checks
    of a just-swapped pair) — simple, stable, and matches spec 7.1's "for
    each pair in close proximity" as a single resolution pass, not a fixed
    point iteration.

    Mutates `cumulative_times` and `lap_times_this_lap` in place for the
    stuck-behind constraint below — consistent with how `engine.py` already
    treats both as the running per-lap state (e.g. `compress_field_under_sc`
    reassigns `cumulative_times` entries the same way). `clamped_this_lap`,
    if given, is also mutated in place: the set of drivers the floor clamp
    actually fired for this call, for `LapState.stuck_behind_clamped` and
    for measuring the clamp's true firing rate directly rather than
    inferring it after the fact — an earlier attempt to infer it from
    exact-tied lap times was the equality clamp's signature, not this one's
    (the floor clamp only rarely produces an exact tie), and silently
    understated or overstated the rate depending on race. See DECISIONS.md.

    `pre_clamp_lap_times` and `clamp_penalty_this_lap`, if given, are also
    filled in place, closing two observability gaps that each cost a full
    review round:
      - The pass roll is evaluated on the *pre-clamp* lap time, but only the
        post-clamp value used to be recorded, so the deltas the rolls
        actually saw were unrecoverable afterwards and any attempt to
        reconstruct the win probability was structurally biased low.
      - The clamp's time addition is a *held-up penalty*, not pace, and
        accumulating it silently into `cumulative_times` meant a clamped
        driver's total time (and its ensemble variance) mixed the two
        together with no way to separate them. Reported separately so a
        confidence band on a counterfactual gap can distinguish "uncertainty
        about pace" from "how much traffic this car hit."

    A car that closes to within `MIN_FOLLOWING_GAP_S` of the car ahead
    without completing a pass is physically wheel-to-wheel: it cannot close
    *further* than that without actually passing. Above that floor, a
    following car closes at its own genuine pace, exactly like a real car —
    the constraint only ever stops a gap from crossing the floor, it never
    equalises lap times outright. (An earlier version of this constraint did
    exactly that — set the follower's lap time equal to the leader's
    whenever they were within `CLOSE_PROXIMITY_GAP_S` — which fired on
    25-64% of all green-flag laps, since two cars merely running together
    within 1.5s for an ordinary stretch of racing is completely normal, not
    a sign either one is blocked. See DECISIONS.md.) Without any floor at
    all, a follower can silently bank cumulative-time advantage lap after
    lap while never actually gaining track position — spec 6.9's
    "additional cost for laps spent unable to pass" (previously undisclosed
    as not separately modelled, folded into dirty air's penalty instead —
    see lap_time.py). That banked, invisible advantage is exactly what let
    a Monaco backmarker end up with lower cumulative time than the driver
    ahead of it despite never passing: `compress_field_under_sc`'s zero
    floor was a correct patch on the *symptom* (the negative gap it
    produced), not this cause.

    The blue-flag check below runs first for exactly this reason: without
    it, the clamp itself can pin a whole train of faster cars behind a
    single lapped backmarker, since each car in the train would otherwise
    be limited relative to the one directly ahead of it.
    """
    order = list(order)
    for i in range(1, len(order)):
        ahead, behind = order[i - 1], order[i]
        gap_s = cumulative_times[behind] - cumulative_times[ahead]

        if gap_s > CLOSE_PROXIMITY_GAP_S:
            continue  # not close enough on track for a pass attempt or the stuck-behind constraint

        leader = order[0]
        if _is_a_lap_down(ahead, leader, cumulative_times, lap_times_this_lap) and not _is_a_lap_down(
            behind, leader, cumulative_times, lap_times_this_lap
        ):
            # `ahead` is lapped traffic being caught by `behind`, not a rival
            # contesting the same position: blue flags apply, not the normal
            # difficulty-gated fight, and never the stuck-behind clamp (a
            # backmarker slow to move over doesn't force the faster car
            # behind it down to its pace).
            if resolve_pass(_roll_for(draws, rng, behind, lap_number), BLUE_FLAG_YIELD_PROBABILITY):
                order[i - 1], order[i] = order[i], order[i - 1]
            continue

        pace_delta_s = lap_times_this_lap[ahead] - lap_times_this_lap[behind]
        if pace_delta_s > 0:
            probability = pass_probability(pace_delta_s, overtake_difficulty)
            if resolve_pass(_roll_for(draws, rng, behind, lap_number), probability):
                order[i - 1], order[i] = order[i], order[i - 1]
                continue

            # Faster this lap but the pass failed: can still close ground
            # down to the minimum following distance, just not past it
            # without completing a pass.
            if gap_s < MIN_FOLLOWING_GAP_S:
                deficit = MIN_FOLLOWING_GAP_S - gap_s
                if pre_clamp_lap_times is not None:
                    pre_clamp_lap_times[behind] = lap_times_this_lap[behind]
                lap_times_this_lap[behind] += deficit
                cumulative_times[behind] += deficit
                if clamped_this_lap is not None:
                    clamped_this_lap.add(behind)
                if clamp_penalty_this_lap is not None:
                    clamp_penalty_this_lap[behind] = clamp_penalty_this_lap.get(behind, 0.0) + deficit

    return order


def reorder_pitting_drivers(
    order: list[str], cumulative_times: dict[str, float], pitted_this_lap: set[str]
) -> list[str]:
    """A driver who pitted this lap is mechanically re-inserted into track
    position by cumulative time — there is no contested on-track battle
    during a pit stop (the car is off the racing line), so this bypasses
    `resolve_positions`'s probabilistic model entirely.

    This matters: without it, a driver who loses 20+ seconds in the pits
    only falls behind a following car if that car "wins" a proximity-gated
    probabilistic pass against them — but the gap between them is enormous
    (tens of seconds) immediately after the stop, so `resolve_positions`'s
    `CLOSE_PROXIMITY_GAP_S` check almost never lets that attempt happen at
    all. Found concretely on 2019 Hungary: a real 5th-to-20th pit-stop drop
    showed as no position change whatsoever in the simulation before this
    fix. Non-pitting drivers keep their relative order here (their genuine
    on-track battles are still resolved by `resolve_positions`, called
    separately).
    """
    non_pitters = [d for d in order if d not in pitted_this_lap]
    pitters = [d for d in order if d in pitted_this_lap]

    result = list(non_pitters)
    for driver in pitters:
        insert_at = len(result)
        for i, other in enumerate(result):
            if cumulative_times[driver] < cumulative_times[other]:
                insert_at = i
                break
        result.insert(insert_at, driver)
    return result


def compute_gaps_to_leader(order: list[str], cumulative_times: dict[str, float]) -> dict[str, float]:
    if not order:
        return {}
    leader_time = cumulative_times[order[0]]
    return {driver: cumulative_times[driver] - leader_time for driver in order}
