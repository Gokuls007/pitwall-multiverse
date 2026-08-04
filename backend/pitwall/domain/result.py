"""Simulation output (spec Part 5.4). Pure data, no logic — produced by
`simulation/engine.py`, consumed by `validation/` and (Phase 4) `counterfactual/`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decision import Decision
from .enums import Compound


@dataclass(frozen=True)
class LapState:
    lap_number: int
    driver: str
    lap_time_s: float
    cumulative_time_s: float
    gap_to_leader_s: float
    position: int
    compound: Compound
    tyre_age: int
    in_dirty_air: bool
    pitted_this_lap: bool
    under_sc: bool
    stuck_behind_clamped: bool  # position.py's MIN_FOLLOWING_GAP_S floor fired this lap
    # What the overtake roll actually saw. `lap_time_s` is post-clamp, but
    # `resolve_positions` evaluates the pass on the pre-clamp value, so
    # without this the deltas the rolls used are unrecoverable and any
    # after-the-fact reconstruction of win probability is biased low.
    # Equals `lap_time_s` when the clamp didn't fire.
    pre_clamp_lap_time_s: float
    # Running total of clamp ("held up behind a car you can't pass") time
    # added to this driver so far. Separated from pace because it's a
    # different quantity: a clamped driver's `cumulative_time_s` is pace plus
    # this, and reporting a confidence band on the sum conflates uncertainty
    # about pace with how much traffic the car happened to hit.
    cumulative_clamp_penalty_s: float


@dataclass(frozen=True)
class SimulationResult:
    race_key: str
    decisions_applied: tuple[Decision, ...]
    lap_states: tuple[LapState, ...]
    classification: tuple[tuple[str, int], ...]  # (driver, finish position)
    diverged_from_lap: int | None
    rng_seed: int
    notes: tuple[str, ...]  # warnings, e.g. "VER lapped traffic on L34"

    def laps_for(self, driver: str) -> tuple[LapState, ...]:
        return tuple(s for s in self.lap_states if s.driver == driver)

    def lap(self, lap_number: int) -> tuple[LapState, ...]:
        """Every driver's state at the end of a given lap, for a field snapshot."""
        return tuple(s for s in self.lap_states if s.lap_number == lap_number)
