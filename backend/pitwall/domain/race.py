"""Immutable ground-truth race data structures (spec Part 5.1).

All frozen. Immutability matters: the counterfactual engine forks state
repeatedly, and shared mutable state produces bugs that are hard to trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .enums import Compound


@dataclass(frozen=True)
class LapRecord:
    """One driver's one lap, as it actually happened."""

    driver: str
    lap_number: int
    lap_time_s: float | None
    compound: Compound
    tyre_life: int
    is_fresh_tyre: bool
    stint: int
    position: int
    is_in_lap: bool
    is_out_lap: bool
    track_status: str
    gap_to_ahead_s: float | None  # derived, needed for dirty-air fitting
    is_usable_for_fitting: bool  # set by cleaning, with reason recorded
    exclusion_reason: str | None


@dataclass(frozen=True)
class Stint:
    driver: str
    stint_number: int
    compound: Compound
    start_lap: int
    end_lap: int
    started_fresh: bool

    @property
    def length(self) -> int:
        return self.end_lap - self.start_lap + 1


@dataclass(frozen=True)
class SafetyCarPeriod:
    kind: Literal["SC", "VSC", "RED"]
    start_lap: int
    end_lap: int

    def covers(self, lap: int) -> bool:
        return self.start_lap <= lap <= self.end_lap


@dataclass(frozen=True)
class DriverEntry:
    code: str
    number: int
    team: str
    grid_position: int
    finish_position: int | None  # None if DNF
    status: str  # "Finished", "+1 Lap", "Accident", etc.
    retired_on_lap: int | None


@dataclass(frozen=True)
class RaceSnapshot:
    """Everything known about a real race. The immutable ground truth.

    Note: `pit_lane_loss_s` is fitted (Part 6.5). It lives here because it is a
    property of the circuit/race and is convenient to carry alongside the raw
    data, but it is produced by the parameters layer, not by ingestion.
    """

    year: int
    event_name: str
    circuit: str
    total_laps: int
    drivers: tuple[DriverEntry, ...]
    laps: tuple[LapRecord, ...]
    stints: tuple[Stint, ...]
    safety_car_periods: tuple[SafetyCarPeriod, ...]
    air_temp_c: float
    track_temp_c: float
    had_rain: bool
    pit_lane_loss_s: float  # fitted, see Part 6.5; 0.0 until parameters run

    @property
    def race_key(self) -> str:
        """Stable slug, e.g. '2021_abu_dhabi'."""
        slug = self.event_name.lower().replace("grand prix", "").strip()
        slug = "_".join(slug.split())
        return f"{self.year}_{slug}"

    def laps_for(self, driver: str) -> tuple[LapRecord, ...]:
        return tuple(lap for lap in self.laps if lap.driver == driver)

    def usable_laps(self) -> tuple[LapRecord, ...]:
        return tuple(lap for lap in self.laps if lap.is_usable_for_fitting)
