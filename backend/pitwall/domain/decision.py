"""Counterfactual inputs (spec 5.3) — the base type only.

Phase 3's engine only needs this to type `SimulationResult.decisions_applied`
(empty for a pure replay, which is all Phase 3 does). Concrete decision types
(`ChangePitLap`, `ChangeCompound`, `AddPitStop`, `RemovePitStop`,
`ShiftSafetyCar`, `RemoveSafetyCar`) and the fork-and-resimulate machinery
that applies them are Phase 4 (`counterfactual/`) scope — not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    """Base type. Every concrete decision must expose `first_affected_lap`
    (spec 5.3) — the earliest lap from which the simulation must be re-run."""

    @property
    def first_affected_lap(self) -> int:
        raise NotImplementedError
