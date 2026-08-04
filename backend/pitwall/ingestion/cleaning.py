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
safety car / VSC, FastF1 inaccurate, sustained pace step (suspected damage),
MAD outlier. Everything else is usable.
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

# Sustained-pace-step (suspected damage) detection. Deliberately conservative
# — tuned up after an initial version (2.0s / 3 laps) produced 294 false
# positives across 8 drivers on 2019 Monaco, spanning almost entire long
# stints from early tyre life onward. Checked directly: those laps don't
# look like damage, they look like deliberate pace management on a one-stop
# strategy at a circuit where overtaking is nearly impossible (spec 6.3's
# cliff model and ordinary team-instructed tyre saving can both legitimately
# cost several seconds a lap, sustained, with zero recovery for the rest of
# a stint — the same shape a real damage event has). A materially higher bar
# (magnitude and duration both) is needed to have any chance of separating
# "car is physically compromised" from "team asked the driver to save tyres."
# This is a real limitation: lap times alone may not reliably distinguish the
# two even at this threshold (see DECISIONS.md) — treat a flagged lap as a
# candidate worth a human look, not a confirmed damage event.
_DAMAGE_STEP_THRESHOLD_S = 4.0
_DAMAGE_MIN_CONSECUTIVE = 5
_DAMAGE_MIN_BASELINE_LAPS = 4


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


def _flag_sustained_pace_step(laps: pd.DataFrame) -> pd.Series:
    """Flag laps after a sustained, discontinuous pace loss within a stint —
    e.g. a driver running with front-wing or floor damage for many laps
    before an unscheduled repair stop.

    This is a gap in spec 4.2's own filters: in/out laps, SC laps, and MAD
    outliers *within a stint* are all covered, but MAD compares each lap
    against its own stint's median — a car that is consistently slow for the
    rest of a stint after taking damage has that slow pace as its new stint
    norm, so MAD sees nothing unusual. Found concretely investigating 2019
    Japanese GP's Leclerc, who ran ~20 laps with a damaged front wing after a
    lap-1 collision before pitting for a new one (that race was dropped from
    the catalogue for unrelated reasons — a chequered-flag timing error — but
    this cleaning gap is general, not specific to it, and those damaged laps
    would otherwise have entered the pooled fuel regression and pooled
    compound slopes as if they were clean green-flag pace).

    Compares each candidate lap against a *rolling, local* baseline (the
    preceding `_DAMAGE_MIN_BASELINE_LAPS` laps), not the stint's very first
    laps — comparing against a fixed early-stint baseline would eventually
    flag ordinary, legitimate degradation too, since a long enough stint's
    cumulative pace loss crosses any fixed absolute threshold on its own. A
    rolling local baseline tracks a gradual (even accelerating, spec 6.3
    cliff-style) trend and only fires on a genuine discontinuity relative to
    the laps immediately before it.

    Only applied to laps that survived the structural checks. Groups smaller
    than `_DAMAGE_MIN_BASELINE_LAPS + _DAMAGE_MIN_CONSECUTIVE` are left alone
    — too short to establish a reliable rolling baseline.
    """
    reason = pd.Series(None, index=laps.index, dtype=object)
    candidates = laps[laps["ExclusionReason"].isna()]

    window = _DAMAGE_MIN_BASELINE_LAPS
    for (_driver, _stint), group in candidates.groupby(["Driver", "Stint"]):
        group = group.sort_values("LapNumber")
        times = group["LapTimeSeconds"].astype(float).to_numpy()
        n = len(times)
        if n < window + _DAMAGE_MIN_CONSECUTIVE:
            continue

        step_start = None
        for i in range(window, n - _DAMAGE_MIN_CONSECUTIVE + 1):
            local_baseline = np.median(times[i - window : i])
            upcoming = times[i : i + _DAMAGE_MIN_CONSECUTIVE]
            if np.all(upcoming - local_baseline > _DAMAGE_STEP_THRESHOLD_S):
                step_start = i
                break

        if step_start is not None:
            reason.loc[group.index[step_start:]] = "suspected_damage_sustained_pace_loss"

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

    damage_reason = _flag_sustained_pace_step(laps)
    laps["ExclusionReason"] = laps["ExclusionReason"].where(
        laps["ExclusionReason"].notna(), damage_reason
    )

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
