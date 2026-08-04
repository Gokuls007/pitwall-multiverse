"""Enumerations shared across the domain. Pure, no logic."""

from __future__ import annotations

from enum import StrEnum


class Compound(StrEnum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"

    @property
    def is_slick(self) -> bool:
        return self in (Compound.SOFT, Compound.MEDIUM, Compound.HARD)


# Slick compounds ordered soft -> hard. Used for sanity checks (softs must be
# faster than mediums faster than hards on a single lap; spec 6.3) and for
# offering compound alternatives in the UI.
SLICK_ORDER: tuple[Compound, ...] = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)


class TrackStatus(StrEnum):
    """Decoded track status for a lap. FastF1 encodes these as concatenated
    digit codes (see ingestion/safety_car.py); this is the decoded meaning the
    simulator reasons about."""

    GREEN = "GREEN"
    SC = "SC"
    VSC = "VSC"
    RED = "RED"


class SessionType(StrEnum):
    RACE = "R"
    QUALIFYING = "Q"
    SPRINT = "S"
    PRACTICE = "P"
