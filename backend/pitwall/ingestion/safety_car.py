"""Track status decoding and safety-car/VSC/red-flag period extraction (spec 4.3).

`TrackStatus` in FastF1 is a string of concatenated single-digit flag codes seen
during a lap (e.g. `"14"` means both "track clear" and "safety car" occurred
during that lap). Empirically verified against Abu Dhabi 2021 (Phase 1):

    lap 36-37: codes '16' / '671'  -> VSC deployed / VSC ending    (matches race
               control messages "VIRTUAL SAFETY CAR DEPLOYED" @ L36, "...ENDING" @ L37)
    lap 53-57: codes '124' ... '41' -> SC deployed ... SC ending   (matches race
               control "SAFETY CAR DEPLOYED" @ L53, "SAFETY CAR IN THIS LAP" @ L57)

This confirms the code table in the spec:
    1 clear, 2 yellow, 4 SC, 5 red, 6 VSC deployed, 7 VSC ending.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from pitwall.domain.race import SafetyCarPeriod

logger = logging.getLogger(__name__)

_SC_CODE = "4"
_RED_CODE = "5"
_VSC_CODES = ("6", "7")


def _codes(track_status: object) -> set[str]:
    """Split a TrackStatus cell (e.g. '671') into its constituent digit codes."""
    if track_status is None or (isinstance(track_status, float) and pd.isna(track_status)):
        return set()
    return set(str(track_status))


def lap_is_red(track_status: object) -> bool:
    return _RED_CODE in _codes(track_status)


def lap_is_sc(track_status: object) -> bool:
    return _SC_CODE in _codes(track_status)


def lap_is_vsc(track_status: object) -> bool:
    return bool(_codes(track_status) & set(_VSC_CODES))


def _lap_flag_kind(track_status: object) -> Literal["RED", "SC", "VSC", None]:
    """Priority order for a lap that shows multiple codes: RED > SC > VSC."""
    if lap_is_red(track_status):
        return "RED"
    if lap_is_sc(track_status):
        return "SC"
    if lap_is_vsc(track_status):
        return "VSC"
    return None


def _periods_from_track_status(laps: pd.DataFrame) -> tuple[SafetyCarPeriod, ...]:
    """Derive SC/VSC/RED lap ranges from the field's TrackStatus, primary source.

    A lap is classified by whether *any* driver's TrackStatus for that lap number
    shows the flag — a single driver's timing loop reliably catches the transition
    lap even if another driver's row is missing it (e.g. they pitted that lap).
    """
    by_lap = laps.groupby("LapNumber")["TrackStatus"].apply(
        lambda s: {code for cell in s for code in _codes(cell)}
    )

    kinds: dict[int, Literal["RED", "SC", "VSC"]] = {}
    for lap_number, codes in by_lap.items():
        if _RED_CODE in codes:
            kinds[int(lap_number)] = "RED"
        elif _SC_CODE in codes:
            kinds[int(lap_number)] = "SC"
        elif codes & set(_VSC_CODES):
            kinds[int(lap_number)] = "VSC"

    if not kinds:
        return ()

    periods: list[SafetyCarPeriod] = []
    sorted_laps = sorted(kinds)
    run_start = sorted_laps[0]
    run_kind = kinds[run_start]
    prev_lap = run_start

    for lap_number in sorted_laps[1:]:
        kind = kinds[lap_number]
        if kind == run_kind and lap_number == prev_lap + 1:
            prev_lap = lap_number
            continue
        periods.append(SafetyCarPeriod(kind=run_kind, start_lap=run_start, end_lap=prev_lap))
        run_start = lap_number
        run_kind = kind
        prev_lap = lap_number

    periods.append(SafetyCarPeriod(kind=run_kind, start_lap=run_start, end_lap=prev_lap))
    return tuple(periods)


@dataclass(frozen=True)
class _RaceControlEvent:
    kind: Literal["SC", "VSC", "RED"]
    boundary: Literal["start", "end"]
    lap: int


def _events_from_race_control(rc_messages: pd.DataFrame) -> list[_RaceControlEvent]:
    """Best-effort extraction of SC/VSC/red-flag start/end laps from race control text."""
    if rc_messages is None or len(rc_messages) == 0:
        return []

    events: list[_RaceControlEvent] = []
    for _, row in rc_messages.iterrows():
        message = str(row.get("Message", "")).upper()
        lap = row.get("Lap")
        if lap is None or (isinstance(lap, float) and pd.isna(lap)):
            continue
        lap = int(lap)

        if "VIRTUAL SAFETY CAR DEPLOYED" in message:
            events.append(_RaceControlEvent("VSC", "start", lap))
        elif "VIRTUAL SAFETY CAR ENDING" in message:
            events.append(_RaceControlEvent("VSC", "end", lap))
        elif "SAFETY CAR DEPLOYED" in message:
            events.append(_RaceControlEvent("SC", "start", lap))
        elif "SAFETY CAR IN THIS LAP" in message:
            events.append(_RaceControlEvent("SC", "end", lap))
        elif "RED FLAG" in message:
            events.append(_RaceControlEvent("RED", "start", lap))

    return events


def extract_safety_car_periods(
    laps: pd.DataFrame, rc_messages: pd.DataFrame
) -> tuple[tuple[SafetyCarPeriod, ...], tuple[str, ...]]:
    """Extract SC/VSC/RED periods, cross-checked against race control (spec 4.3).

    TrackStatus-derived periods are primary. Race control messages are used to
    verify both the start and end lap of each period; on disagreement, spec 4.3
    says to prefer race control and log the discrepancy — the returned period is
    adjusted accordingly and the discrepancy is included in the returned notes.
    """
    derived = _periods_from_track_status(laps)
    rc_events = _events_from_race_control(rc_messages)

    rc_laps_by_kind: dict[str, dict[str, list[int]]] = {
        kind: {"start": [], "end": []} for kind in ("SC", "VSC", "RED")
    }
    for event in rc_events:
        rc_laps_by_kind[event.kind][event.boundary].append(event.lap)

    notes: list[str] = []
    reconciled: list[SafetyCarPeriod] = []
    consumed: dict[str, dict[str, int]] = {
        kind: {"start": 0, "end": 0} for kind in ("SC", "VSC", "RED")
    }

    for period in derived:
        start_lap, end_lap = period.start_lap, period.end_lap

        for boundary, current_lap in (("start", start_lap), ("end", end_lap)):
            candidates = rc_laps_by_kind[period.kind][boundary]
            idx = consumed[period.kind][boundary]
            if idx >= len(candidates):
                notes.append(
                    f"{period.kind} period at laps {period.start_lap}-{period.end_lap}: "
                    f"no race control '{boundary}' message found to cross-check."
                )
                continue
            rc_lap = candidates[idx]
            consumed[period.kind][boundary] += 1
            if rc_lap != current_lap:
                notes.append(
                    f"{period.kind} period {boundary} lap: TrackStatus says {current_lap}, "
                    f"race control says {rc_lap}; using race control per spec 4.3."
                )
                if boundary == "start":
                    start_lap = rc_lap
                else:
                    end_lap = rc_lap

        if end_lap < start_lap:
            notes.append(
                f"{period.kind} period: reconciled start lap {start_lap} fell after end lap "
                f"{end_lap} (only one boundary had a race control match); clamping end to start."
            )
            end_lap = start_lap

        reconciled.append(SafetyCarPeriod(kind=period.kind, start_lap=start_lap, end_lap=end_lap))

    for note in notes:
        logger.warning("Safety car cross-check discrepancy: %s", note)

    return tuple(reconciled), tuple(notes)
