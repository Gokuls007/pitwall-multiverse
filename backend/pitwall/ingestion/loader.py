"""FastF1 session -> `RaceSnapshot` (spec Part 4, Part 5.1).

This is the assembly point: FastF1's messy per-driver-per-lap DataFrame becomes
the frozen domain objects that `simulation/` and `parameters/` deal in. Nothing
outside `ingestion/` ever sees a FastF1 session or a pandas DataFrame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import fastf1
import pandas as pd

from pitwall.domain.enums import Compound
from pitwall.domain.race import DriverEntry, LapRecord, RaceSnapshot, SafetyCarPeriod, Stint
from pitwall.ingestion import cleaning
from pitwall.ingestion.cache import enable_cache
from pitwall.ingestion.safety_car import extract_safety_car_periods

logger = logging.getLogger(__name__)

# Pre-2019 seasons named dry compounds absolutely (softest -> hardest) rather than
# relative to the race weekend's nomination, e.g. 2018 Australian GP ran
# ULTRASOFT/SUPERSOFT/SOFT. The domain model (Part 5.1) only knows the post-2019
# relative SOFT/MEDIUM/HARD scheme FastF1 itself unified on. Deviation from spec
# 4.1's column table, recorded in DECISIONS.md: remap legacy names to relative
# ones by rank among the compounds actually nominated for that race weekend.
_LEGACY_SOFTNESS_ORDER = (
    "HYPERSOFT",
    "ULTRASOFT",
    "SUPERSOFT",
    "SOFT",
    "MEDIUM",
    "HARD",
    "SUPERHARD",
)
_RELATIVE_NAMES = ("SOFT", "MEDIUM", "HARD")


def _remap_legacy_compounds(laps: pd.DataFrame) -> pd.DataFrame:
    dry_used = [c for c in _LEGACY_SOFTNESS_ORDER if c in set(laps["Compound"].dropna())]
    if set(dry_used) <= set(_RELATIVE_NAMES):
        return laps  # already the relative scheme, nothing to do

    if len(dry_used) > 3:
        logger.warning(
            "More than 3 legacy dry compounds nominated (%s) — using the 3 most "
            "common by lap count for the SOFT/MEDIUM/HARD remap.",
            dry_used,
        )
        dry_used = (
            laps["Compound"][laps["Compound"].isin(dry_used)]
            .value_counts()
            .index[:3]
            .tolist()
        )
        dry_used = [c for c in _LEGACY_SOFTNESS_ORDER if c in dry_used]

    mapping = dict(zip(dry_used, _RELATIVE_NAMES[: len(dry_used)], strict=False))
    logger.info("Legacy compound remap applied: %s", mapping)
    laps = laps.copy()
    laps["Compound"] = laps["Compound"].replace(mapping)
    return laps


@dataclass
class IngestionReport:
    """Diagnostics for one race load — the Phase 1 cleaning report (spec 4.2)."""

    race_key: str
    total_lap_rows: int
    exclusion_counts: dict[str, int]
    safety_car_periods: tuple[SafetyCarPeriod, ...]
    safety_car_discrepancies: tuple[str, ...]
    drivers_missing_lap_data: tuple[str, ...]

    def print_summary(self) -> None:
        print(f"--- Ingestion report: {self.race_key} ---")
        print(f"Total lap rows: {self.total_lap_rows}")
        for reason, count in sorted(self.exclusion_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {reason}: {count}")
        print(f"Safety car / VSC / red periods: {len(self.safety_car_periods)}")
        for period in self.safety_car_periods:
            print(f"  {period.kind} laps {period.start_lap}-{period.end_lap}")
        if self.safety_car_discrepancies:
            print("Safety car cross-check discrepancies:")
            for note in self.safety_car_discrepancies:
                print(f"  {note}")
        if self.drivers_missing_lap_data:
            print(
                "Drivers with no lap data (withdrew before the race started): "
                + ", ".join(self.drivers_missing_lap_data)
            )


def race_key_for(year: int, event_name: str) -> str:
    slug = event_name.lower().replace("grand prix", "").strip()
    slug = "_".join(slug.split())
    return f"{year}_{slug}"


def _parse_compound(value: object) -> Compound:
    if pd.notna(value):
        try:
            return Compound(value)
        except ValueError:
            logger.warning("Unrecognised compound %r, defaulting to MEDIUM", value)
    return Compound.MEDIUM


def _build_driver_entries(results: pd.DataFrame, laps: pd.DataFrame) -> tuple[DriverEntry, ...]:
    entries = []
    for _, row in results.iterrows():
        code = row["Abbreviation"]
        finish_position = row["Position"]
        finish_position = int(finish_position) if pd.notna(finish_position) else None
        status = str(row["Status"])

        driver_laps = laps[laps["Driver"] == code]
        did_not_finish = status != "Finished" and not status.startswith("+")
        retired_on_lap = int(driver_laps["LapNumber"].max()) if did_not_finish and len(driver_laps) else None

        entries.append(
            DriverEntry(
                code=code,
                number=int(row["DriverNumber"]),
                team=str(row["TeamName"]),
                grid_position=int(row["GridPosition"]) if pd.notna(row["GridPosition"]) else 0,
                finish_position=finish_position,
                status=status,
                retired_on_lap=retired_on_lap,
            )
        )
    return tuple(entries)


def _build_lap_records(laps: pd.DataFrame) -> tuple[LapRecord, ...]:
    records = []
    for _, row in laps.iterrows():
        records.append(
            LapRecord(
                driver=row["Driver"],
                lap_number=int(row["LapNumber"]),
                lap_time_s=(
                    float(row["LapTimeSeconds"]) if pd.notna(row["LapTimeSeconds"]) else None
                ),
                compound=_parse_compound(row["Compound"]),
                tyre_life=int(row["TyreLife"]) if pd.notna(row["TyreLife"]) else 0,
                is_fresh_tyre=bool(row["FreshTyre"]) if pd.notna(row["FreshTyre"]) else False,
                stint=int(row["Stint"]) if pd.notna(row["Stint"]) else 0,
                position=int(row["Position"]) if pd.notna(row["Position"]) else 0,
                is_in_lap=pd.notna(row["PitInTime"]),
                is_out_lap=pd.notna(row["PitOutTime"]),
                track_status=str(row["TrackStatus"]) if pd.notna(row["TrackStatus"]) else "",
                gap_to_ahead_s=(
                    float(row["GapToAheadS"]) if pd.notna(row["GapToAheadS"]) else None
                ),
                is_usable_for_fitting=bool(row["IsUsableForFitting"]),
                exclusion_reason=(
                    row["ExclusionReason"] if pd.notna(row["ExclusionReason"]) else None
                ),
            )
        )
    return tuple(records)


def _build_stints(laps: pd.DataFrame) -> tuple[Stint, ...]:
    stints = []
    for (driver, stint_number), group in laps.groupby(["Driver", "Stint"]):
        if pd.isna(stint_number) or stint_number == 0:
            continue
        compound_counts = group["Compound"].dropna().value_counts()
        if not len(compound_counts):
            continue
        compound = _parse_compound(compound_counts.idxmax())
        first_row = group.sort_values("LapNumber").iloc[0]
        stints.append(
            Stint(
                driver=driver,
                stint_number=int(stint_number),
                compound=compound,
                start_lap=int(group["LapNumber"].min()),
                end_lap=int(group["LapNumber"].max()),
                started_fresh=(
                    bool(first_row["FreshTyre"]) if pd.notna(first_row["FreshTyre"]) else False
                ),
            )
        )
    return tuple(sorted(stints, key=lambda s: (s.driver, s.stint_number)))


def load_race(year: int, event_identifier: str) -> tuple[RaceSnapshot, IngestionReport]:
    """Load one race session into a validated, immutable `RaceSnapshot`.

    `event_identifier` is whatever `fastf1.get_session` accepts as the `gp`
    argument (verified against the installed 3.8.3 API, DECISIONS.md) — e.g.
    "Abu Dhabi".
    """
    enable_cache()
    session = fastf1.get_session(year, event_identifier, "R")
    session.load(laps=True, telemetry=False, weather=True, messages=True)

    laps = session.laps.copy()
    laps = _remap_legacy_compounds(laps)
    # Convert LapTime (a pandas Timedelta) to float seconds immediately at the
    # ingestion boundary (spec 4.1) — nothing inward of this module ever sees a Timedelta.
    laps["LapTimeSeconds"] = laps["LapTime"].dt.total_seconds()

    laps["GapToAheadS"] = cleaning.compute_gap_to_ahead(laps)
    laps = cleaning.annotate_usability(laps)

    race_key = race_key_for(year, session.event["EventName"])
    sc_periods, sc_notes = extract_safety_car_periods(laps, session.race_control_messages)

    drivers = _build_driver_entries(session.results, laps)
    lap_records = _build_lap_records(laps)
    stints = _build_stints(laps)

    weather = session.weather_data
    have_weather = weather is not None and len(weather) > 0
    air_temp = float(weather["AirTemp"].mean()) if have_weather else 0.0
    track_temp = float(weather["TrackTemp"].mean()) if have_weather else 0.0

    # The FastF1 `Rainfall` sensor flag is noisy — verified (Phase 1) that 2019 Monaco
    # shows Rainfall=True on 63% of samples despite the entire race being run on slicks.
    # Whether any non-slick compound was actually fitted is the reliable "had rain
    # that mattered" signal; see DECISIONS.md.
    had_rain = bool(laps["Compound"].isin(["INTERMEDIATE", "WET"]).any())

    total_laps = int(laps["LapNumber"].max()) if len(laps) else 0

    snapshot = RaceSnapshot(
        year=year,
        event_name=session.event["EventName"],
        circuit=str(session.event["Location"]),
        total_laps=total_laps,
        drivers=drivers,
        laps=lap_records,
        stints=stints,
        safety_car_periods=sc_periods,
        air_temp_c=air_temp,
        track_temp_c=track_temp,
        had_rain=had_rain,
        pit_lane_loss_s=0.0,  # fitted in Phase 2 (parameters/pit_loss.py), spec 6.5
    )

    drivers_with_laps = set(laps["Driver"].unique())
    drivers_missing = tuple(sorted(d.code for d in drivers if d.code not in drivers_with_laps))

    report = IngestionReport(
        race_key=race_key,
        total_lap_rows=len(laps),
        exclusion_counts=cleaning.exclusion_summary(laps),
        safety_car_periods=sc_periods,
        safety_car_discrepancies=sc_notes,
        drivers_missing_lap_data=drivers_missing,
    )

    return snapshot, report
