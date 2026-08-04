"""Safety car / VSC field effects on gaps (spec 6.8), simulation side —
distinct from `ingestion/safety_car.py`, which extracts real SC/VSC periods
from FastF1 data. This module has no I/O and knows nothing about FastF1.

Full SC compresses the field toward a fixed following distance (spec 6.8
point 2 — "a driver who was twenty seconds ahead is suddenly a car length
ahead"). VSC does *not* compress: it's handled entirely by
`lap_time.sc_vsc_multiplier` scaling every driver's lap time by the same
factor, which preserves relative gaps without an explicit adjustment here
(spec 6.8 point 4 — "VSC... drivers hold a delta"). Pit stops becoming cheap
under SC/VSC (point 3) is handled in `lap_time.pit_lane_time_s`.
"""

from __future__ import annotations

# Not fitted — a generic bunched-pack following distance under a real safety
# car. Declared prior per Part 14 rule 1; spec 6.8 doesn't ask this to be
# fitted from data (there's no lap-level following-distance measurement in
# this project's ingestion), only that compression itself be modelled.
SC_FOLLOWING_DISTANCE_S = 1.5

# Not fitted — a declared prior (Part 14 rule 1) bounding how much of a gap
# can close in a *single* SC lap. A backmarker many seconds down cannot
# physically close that gap the instant SC is shown; real bunching happens
# because a car not yet caught up to the queue can hold close to normal race
# pace while the queue itself is held to SC pace, so the gap closes at
# roughly (normal_pace - sc_pace) per lap, not instantaneously. 15s/lap is a
# rough, disclosed estimate — this project's ingestion has no per-lap
# bunching-rate measurement to fit against. Found concretely on 2019 Monaco:
# without a closure cap, a car ~40s behind on the road was snapped to a
# ~1.5s gap on the very first SC lap, when real telemetry shows that same
# gap closing gradually over the SC period's several laps (42s -> 25s ->
# ... -> 5s across four laps), not in one step.
MAX_GAP_CLOSURE_PER_LAP_S = 15.0


def compress_field_under_sc(
    ordered_cumulative_times_s: list[float],
    following_distance_s: float = SC_FOLLOWING_DISTANCE_S,
    max_gap_closure_s: float = MAX_GAP_CLOSURE_PER_LAP_S,
) -> list[float]:
    """`ordered_cumulative_times_s` must be in current *track position* order
    (P1 first — position is authoritative, spec 7.2). Any gap to the car
    immediately ahead larger than `following_distance_s` is closed toward it
    by at most `max_gap_closure_s` this lap, never overshooting past the
    following distance; smaller gaps (already bunched closer) are left
    alone. Applied every lap the field is under full SC, not just on
    deployment — since the result is written back into each driver's
    running cumulative time, a gap larger than `max_gap_closure_s` takes
    multiple SC laps to fully bunch up, matching how real safety car periods
    actually converge (see `MAX_GAP_CLOSURE_PER_LAP_S`'s comment).

    Track position is allowed to disagree with raw cumulative-time order
    (spec 7.2 — a car stuck behind can have lower cumulative time than the
    car ahead of it; that's the whole point of "gap <= 0 isn't an automatic
    pass"). So `natural_gap` for an adjacent pair can legitimately come out
    at or below zero here. That case is floored to a 0 gap rather than
    closed further — without the floor, a negative gap would propagate as a
    *decrease* in compressed cumulative time, inverting the order the list
    is supposed to represent, and, because the result is written back into
    the driver's running cumulative time, corrupt every following lap's
    gaps too. Found concretely on 2019 Monaco: a real SC-period ordering
    inversion produced a cumulative-time collapse that let a backmarker end
    up simulated as race leader.
    """
    if not ordered_cumulative_times_s:
        return []
    compressed = [ordered_cumulative_times_s[0]]
    for i in range(1, len(ordered_cumulative_times_s)):
        natural_gap = ordered_cumulative_times_s[i] - ordered_cumulative_times_s[i - 1]
        if natural_gap <= following_distance_s:
            gap = max(0.0, natural_gap)
        else:
            closure = min(max_gap_closure_s, natural_gap - following_distance_s)
            gap = natural_gap - closure
        compressed.append(compressed[-1] + gap)
    return compressed
