"""Lap data cleaning (spec 4.2).

Real timing data is dirty. Every exclusion is recorded and countable — never
silently dropped (spec Part 14, rule 3). This module adds two columns to the
laps DataFrame: `IsUsableForFitting` (bool) and `ExclusionReason` (str | None).

Traffic-affected laps are deliberately *not* excluded here (4.2 point 4) — a lap
spent stuck behind a slower car is exactly what the dirty-air model (Part 6.6)
needs to fit on, so those laps stay usable and their gap-to-car-ahead is what
`loader.py` records via `LapRecord.gap_to_ahead_s`.

Precedence when several rules could apply to the same lap (first match wins,
checked in this order): first lap, in/out lap, null lap time, red flag,
safety car / VSC, FastF1 inaccurate, MAD outlier. Everything else is usable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.ingestion.safety_car import lap_is_red, lap_is_sc, lap_is_vsc

# Median Absolute Deviation multiplier for outlier detection within a stint.
# 1.4826 * MAD approximates a standard deviation for normally-distributed data;
# a lap more than this many scaled-MADs from its stint's median is an outlier.
# Chosen generously (rather than a fixed-second threshold) because green-flag
# pace varies enormously by circuit (spec 4.2 point 5).
_MAD_SCALE = 1.4826
_MAD_THRESHOLD = 4.0


def _structural_reason(row: pd.Series) -> str | None:
    if row["LapNumber"] == 1:
        return "first_lap"
    if pd.notna(row.get("PitInTime")) or pd.notna(row.get("PitOutTime")):
        return "in_or_out_lap"
    if pd.isna(row.get("LapTimeSeconds")):
        return "null_lap_time"
    if lap_is_red(row.get("TrackStatus")):
        return "red_flag"
    if lap_is_sc(row.get("TrackStatus")):
        return "safety_car"
    if lap_is_vsc(row.get("TrackStatus")):
        return "virtual_safety_car"
    if row.get("IsAccurate") is False:
        return "fastf1_inaccurate"
    return None


def _flag_mad_outliers(laps: pd.DataFrame) -> pd.Series:
    """Flag outlier lap times via MAD within each (driver, stint) group.

    Only applied to laps that survived the structural checks — i.e. candidate
    green-flag pace laps. Groups smaller than 4 laps are left alone;
    MAD is not meaningful on a near-empty sample.
    """
    reason = pd.Series(None, index=laps.index, dtype=object)
    candidates = laps[laps["ExclusionReason"].isna()]

    for (_driver, _stint), group in candidates.groupby(["Driver", "Stint"]):
        if len(group) < 4:
            continue
        times = group["LapTimeSeconds"].astype(float)
        median = times.median()
        mad = (times - median).abs().median()
        if mad == 0 or pd.isna(mad):
            continue
        scaled_deviation = (times - median).abs() / (mad * _MAD_SCALE)
        outliers = scaled_deviation[scaled_deviation > _MAD_THRESHOLD]
        reason.loc[outliers.index] = "outlier_mad"

    return reason


def annotate_usability(laps: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `laps` with `IsUsableForFitting` and `ExclusionReason` added.

    Expects `laps` to already have a `LapTimeSeconds` float column (LapTime
    timedeltas converted at the ingestion boundary, spec 4.1) and the raw
    FastF1 columns `TrackStatus`, `PitInTime`, `PitOutTime`, `IsAccurate`,
    `Driver`, `Stint`, `LapNumber`.
    """
    laps = laps.copy()
    laps["ExclusionReason"] = laps.apply(_structural_reason, axis=1)

    outlier_reason = _flag_mad_outliers(laps)
    laps["ExclusionReason"] = laps["ExclusionReason"].where(
        laps["ExclusionReason"].notna(), outlier_reason
    )

    laps["IsUsableForFitting"] = laps["ExclusionReason"].isna()
    return laps


def exclusion_summary(laps: pd.DataFrame) -> dict[str, int]:
    """Usable vs excluded lap counts with reasons — the Phase 1 cleaning report."""
    counts = laps["ExclusionReason"].fillna("usable").value_counts().to_dict()
    return {str(k): int(v) for k, v in counts.items()}


def compute_gap_to_ahead(laps: pd.DataFrame) -> pd.Series:
    """Gap (seconds) to the car ahead on track at the end of each lap.

    Needed even for excluded/traffic laps so the dirty-air model (6.6) can be
    fitted on them — this is *not* part of the usability decision.

    Approximated from cumulative race time at `Time` (session-relative lap end
    timestamp) grouped by lap number and ordered by `Position`. Laps with a
    missing `Time` or `Position` (retirements, data gaps) get a NaN gap.
    """
    gaps = pd.Series(np.nan, index=laps.index, dtype=float)

    for _lap_number, group in laps.groupby("LapNumber"):
        ordered = group.dropna(subset=["Position", "Time"]).sort_values("Position")
        if len(ordered) < 2:
            continue
        times = ordered["Time"]
        gap_seconds = times.diff().dt.total_seconds()
        gaps.loc[ordered.index] = gap_seconds.to_numpy()

    return gaps
