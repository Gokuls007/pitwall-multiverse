"""Fitted per-driver parameters (spec Part 5.2). Pure data, no I/O.

`DriverEntry` (raw session data: grid slot, finish position, status) lives in
`race.py`, not here — a Phase 0 layout deviation recorded in DECISIONS.md.
`DriverParams` (this file) is the *fitted* counterpart: what `parameters/`
learns about a driver from their actual laps, consumed by `simulation/`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import Compound


@dataclass(frozen=True)
class TyreModel:
    """Lap time penalty as a function of tyre age, for one compound (spec 6.3)."""

    compound: Compound
    base_offset_s: float  # pace offset vs the reference compound
    linear_deg_s_per_lap: float
    cliff_lap: int | None  # age at which degradation accelerates
    cliff_deg_s_per_lap: float | None
    r_squared: float  # fit quality — surfaced, never hidden (spec 8.4)
    n_observations: int

    def degradation_s(self, tyre_age: int) -> float:
        """Lap time penalty (seconds) at this tyre age, relative to age 0."""
        if self.cliff_lap is None or tyre_age <= self.cliff_lap:
            return self.linear_deg_s_per_lap * tyre_age
        pre_cliff = self.linear_deg_s_per_lap * self.cliff_lap
        post_cliff = self.cliff_deg_s_per_lap * (tyre_age - self.cliff_lap)
        return pre_cliff + post_cliff


@dataclass(frozen=True)
class DriverParams:
    driver: str
    base_pace_s: float  # clean-air, fresh-tyre, low-fuel reference lap
    pace_std_s: float  # lap-to-lap consistency
    tyre_models: dict[Compound, TyreModel]
    overtake_skill: float  # 0..1, see spec 6.7
    defence_skill: float  # 0..1
