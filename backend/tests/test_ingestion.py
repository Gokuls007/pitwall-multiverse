"""Phase 1 acceptance tests: FastF1 ingestion, cleaning, and the race catalogue.

Network/cache note: these tests call `fastf1.get_session(...).load(...)`. On a
cold machine the first run fetches from the FastF1 API; `scripts/prefetch_races.py`
warms `data/cache/` so CI and repeat runs are fast (verified Phase 1: ~1s/race
warm). Results are cached per-process via `_load` below so five test functions
touching the same race don't reload it five times.

Known-result assertions below (winners, top order, DNFs, SC laps) were checked
by hand against FastF1's own `session.results` / `race_control_messages` during
Phase 1 development (see DECISIONS.md) — this is exactly the "does ingestion
reproduce the real, known outcome" check Part 8 later formalises for the
simulator itself.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
import pytest

from pitwall.domain.enums import Compound
from pitwall.ingestion import cleaning
from pitwall.ingestion.catalogue import CATALOGUE
from pitwall.ingestion.loader import load_race
from pitwall.ingestion.safety_car import lap_is_red, lap_is_sc, lap_is_vsc


@lru_cache(maxsize=None)
def _load(year: int, event_identifier: str):
    return load_race(year, event_identifier)


# ---------------------------------------------------------------------------
# Catalogue-wide: every race loads and its classification matches reality.
# ---------------------------------------------------------------------------

# (race_key, total_laps, [ordered finisher codes for P1..P5], [(code, status) for DNFs])
#
# Abu Dhabi 2021 is deliberately NOT in the catalogue: its outcome hinged on a
# race-control judgement call (which lapped cars were waved through before the
# one-lap restart), not a modellable strategy or physics decision (see
# DECISIONS.md). It's kept as a hardcoded SC/VSC-extraction fixture below
# instead — a good test case for ingestion, a bad case for the counterfactual
# product itself.
EXPECTED = {
    "2019_mexican": (71, ["HAM", "VET", "BOT", "LEC", "ALB"], []),
    "2019_japanese": (53, ["BOT", "VET", "HAM", "ALB", "SAI"], []),
    "2019_monaco": (78, ["HAM", "VET", "BOT", "VER", "GAS"], []),
    "2019_hungarian": (70, ["HAM", "VER", "VET", "LEC", "SAI"], []),
    "2021_spanish": (66, ["HAM", "VER", "BOT", "LEC", "PER"], []),
}


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_catalogue_race_loads_without_error(entry):
    snapshot, report = _load(entry.year, entry.fastf1_event_identifier)
    assert len(snapshot.laps) > 0
    assert len(snapshot.drivers) == 20
    assert report.total_lap_rows == len(snapshot.laps)


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_catalogue_race_total_laps_matches_official(entry):
    snapshot, _ = _load(entry.year, entry.fastf1_event_identifier)
    expected_total_laps, _, _ = EXPECTED[entry.race_key]
    assert snapshot.total_laps == expected_total_laps


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_catalogue_race_classification_matches_official(entry):
    snapshot, _ = _load(entry.year, entry.fastf1_event_identifier)
    _, expected_top5, expected_dnfs = EXPECTED[entry.race_key]

    finishers = sorted(
        (d for d in snapshot.drivers if d.finish_position is not None),
        key=lambda d: d.finish_position,
    )
    actual_top5 = [d.code for d in finishers[:5]]
    assert actual_top5 == expected_top5

    for code, status in expected_dnfs:
        driver = next(d for d in snapshot.drivers if d.code == code)
        assert driver.finish_position is None
        assert driver.status == status


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_catalogue_race_is_dry(entry):
    """Selection criterion (spec 4.4): every catalogued race is dry for v1."""
    snapshot, _ = _load(entry.year, entry.fastf1_event_identifier)
    assert snapshot.had_rain is False


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_cleaning_report_accounts_for_every_lap(entry):
    """Never silently drop data (spec Part 14, rule 3): every lap row is counted
    as either usable or excluded-with-a-reason, and the two add up to the total."""
    snapshot, report = _load(entry.year, entry.fastf1_event_identifier)
    assert sum(report.exclusion_counts.values()) == report.total_lap_rows
    assert report.exclusion_counts.get("usable", 0) > 0
    for lap in snapshot.laps:
        if lap.is_usable_for_fitting:
            assert lap.exclusion_reason is None
        else:
            assert lap.exclusion_reason is not None


def test_safety_car_periods_match_documented_abu_dhabi_2021():
    """Abu Dhabi 2021 is the spec's own recommended SC test case (4.3): VSC for
    Alonso's/Sainz's... [Latifi's crash triggered the late SC; the mid-race VSC was
    for Sainz's engine cover]. Real timeline per race control messages:
    VSC lap 36-37, SC lap 53-57 (verified independently during Phase 1, see
    DECISIONS.md)."""
    snapshot, _ = _load(2021, "Abu Dhabi")
    periods_by_kind = {p.kind: p for p in snapshot.safety_car_periods}

    assert periods_by_kind["VSC"].start_lap == 36
    assert periods_by_kind["VSC"].end_lap == 37
    assert periods_by_kind["SC"].start_lap == 53
    assert periods_by_kind["SC"].end_lap == 57


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.race_key)
def test_no_safety_car_period_is_inverted(entry):
    """Regression test for the reconciliation clamp: race-control cross-checking
    must never produce a period whose end lap precedes its start lap."""
    snapshot, _ = _load(entry.year, entry.fastf1_event_identifier)
    for period in snapshot.safety_car_periods:
        assert period.end_lap >= period.start_lap


# ---------------------------------------------------------------------------
# Track status decoding (spec 4.3) — pure unit tests, no network.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expect_red,expect_sc,expect_vsc",
    [
        ("1", False, False, False),
        ("2", False, False, False),
        ("4", False, True, False),
        ("14", False, True, False),
        ("124", False, True, False),
        ("5", True, False, False),
        ("6", False, False, True),
        ("7", False, False, True),
        ("671", False, False, True),  # '6','7','1' -> VSC, no red/SC
        ("41", False, True, False),
    ],
)
def test_track_status_flag_decoding(status, expect_red, expect_sc, expect_vsc):
    assert lap_is_red(status) == expect_red
    assert lap_is_sc(status) == expect_sc
    assert lap_is_vsc(status) == expect_vsc


def test_track_status_handles_missing_value():
    assert lap_is_sc(None) is False
    assert lap_is_vsc(float("nan")) is False


# ---------------------------------------------------------------------------
# Cleaning exclusion rules (spec 4.2) — pure unit tests on synthetic data.
# ---------------------------------------------------------------------------


def _synthetic_laps(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "Driver": "XXX",
        "LapNumber": 2,
        "LapTimeSeconds": 90.0,
        "TrackStatus": "1",
        "PitInTime": pd.NaT,
        "PitOutTime": pd.NaT,
        "IsAccurate": True,
        "Stint": 1,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_first_lap_excluded():
    laps = _synthetic_laps([{"LapNumber": 1}])
    annotated = cleaning.annotate_usability(laps)
    assert annotated.iloc[0]["ExclusionReason"] == "first_lap"
    assert not annotated.iloc[0]["IsUsableForFitting"]


def test_in_lap_and_out_lap_excluded():
    laps = _synthetic_laps(
        [
            {"PitInTime": pd.Timestamp("2021-01-01 00:01:00")},
            {"PitOutTime": pd.Timestamp("2021-01-01 00:02:00")},
        ]
    )
    annotated = cleaning.annotate_usability(laps)
    assert (annotated["ExclusionReason"] == "in_or_out_lap").all()


def test_null_lap_time_excluded():
    laps = _synthetic_laps([{"LapTimeSeconds": None}])
    annotated = cleaning.annotate_usability(laps)
    assert annotated.iloc[0]["ExclusionReason"] == "null_lap_time"


def test_safety_car_and_vsc_laps_excluded():
    laps = _synthetic_laps([{"TrackStatus": "4"}, {"TrackStatus": "6"}, {"TrackStatus": "5"}])
    annotated = cleaning.annotate_usability(laps)
    assert list(annotated["ExclusionReason"]) == ["safety_car", "virtual_safety_car", "red_flag"]


def test_fastf1_inaccurate_lap_excluded():
    laps = _synthetic_laps([{"IsAccurate": False}])
    annotated = cleaning.annotate_usability(laps)
    assert annotated.iloc[0]["ExclusionReason"] == "fastf1_inaccurate"


def test_mad_outlier_detected_within_stint():
    # Five clean, consistent laps plus one wild outlier in the same stint.
    rows = [{"LapNumber": n, "LapTimeSeconds": 90.0 + n * 0.05} for n in range(2, 7)]
    rows.append({"LapNumber": 7, "LapTimeSeconds": 140.0})  # off-track excursion
    laps = _synthetic_laps(rows)
    annotated = cleaning.annotate_usability(laps)
    outlier_row = annotated[annotated["LapNumber"] == 7].iloc[0]
    assert outlier_row["ExclusionReason"] == "outlier_mad"
    assert (annotated[annotated["LapNumber"] != 7]["ExclusionReason"].isna()).all()


def test_exclusion_summary_counts_all_reasons():
    laps = _synthetic_laps([{"LapNumber": 1}, {"LapNumber": 2}, {"TrackStatus": "4", "LapNumber": 3}])
    annotated = cleaning.annotate_usability(laps)
    summary = cleaning.exclusion_summary(annotated)
    assert summary["first_lap"] == 1
    assert summary["safety_car"] == 1
    assert summary["usable"] == 1
    assert sum(summary.values()) == 3


def test_compound_enum_covers_synthetic_values():
    # Guards against the legacy pre-2019 naming (ULTRASOFT etc.) silently slipping
    # through unmapped — Compound() must only ever see the 5 relative/wet names.
    for value in ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"):
        assert Compound(value).value == value
