"""Counterfactual inputs (spec 5.3).

Every concrete `Decision` exposes `first_affected_lap` — the earliest lap
from which the simulation must be re-run; everything before that lap is
copied verbatim from reality (spec 9.1 steps 3-4). The fork-and-resimulate
machinery that applies these lives in `counterfactual/` (Phase 4).

Scope note, not a spec change: `ChangePitLap` is the only decision type
`counterfactual/strategy.py` currently applies. The others are declared
here (so `first_affected_lap` and the type shapes are settled and tested)
but `apply_decision` raises `NotImplementedError` for them — see that
module's docstring for why, and for `ChangeCompound` specifically, why it
should stay flagged as prior-driven even once implemented (spec 6.3: 61%
of adjacent-compound gaps across the catalogue sit at the declared 0.15s
floor, so for most drivers a compound-swap counterfactual would be
answering from the prior, not from that driver's own data).
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import Compound


@dataclass(frozen=True)
class Decision:
    """Base type. Every concrete decision must expose `first_affected_lap`
    (spec 5.3) — the earliest lap from which the simulation must be re-run."""

    @property
    def first_affected_lap(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class ChangePitLap(Decision):
    driver: str
    original_lap: int
    new_lap: int

    @property
    def first_affected_lap(self) -> int:
        # Whichever lap first differs from reality: pitting later leaves
        # `original_lap` as the last real green-flag lap and diverges from
        # there; pitting earlier turns `new_lap` itself into the in-lap.
        return min(self.original_lap, self.new_lap)


@dataclass(frozen=True)
class ChangeCompound(Decision):
    driver: str
    stint_number: int
    new_compound: Compound
    stint_start_lap: int

    @property
    def first_affected_lap(self) -> int:
        return self.stint_start_lap


@dataclass(frozen=True)
class AddPitStop(Decision):
    driver: str
    lap: int
    compound: Compound

    @property
    def first_affected_lap(self) -> int:
        return self.lap


@dataclass(frozen=True)
class RemovePitStop(Decision):
    driver: str
    lap: int

    @property
    def first_affected_lap(self) -> int:
        return self.lap


@dataclass(frozen=True)
class ShiftSafetyCar(Decision):
    period_index: int
    lap_delta: int  # negative = earlier
    original_start_lap: int

    @property
    def first_affected_lap(self) -> int:
        return min(self.original_start_lap, self.original_start_lap + self.lap_delta)


@dataclass(frozen=True)
class RemoveSafetyCar(Decision):
    period_index: int
    original_start_lap: int

    @property
    def first_affected_lap(self) -> int:
        return self.original_start_lap
