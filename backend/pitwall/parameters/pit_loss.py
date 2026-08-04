"""Pit stop time-loss fitting (spec 6.5).

Total pit loss is measured relative to *modelled* expected pace (never the
driver's raw average lap time — spec 6.5's explicit warning, since an average
already contains tyre degradation and fuel effects that would otherwise get
absorbed into the pit-loss estimate) by comparing each in-lap/out-lap pair
against what the fitted pace/tyre/fuel model expects for that lap.

Honest limitation, recorded in DECISIONS.md: spec 6.5 wants stationary time
(the box stop itself) and pit-lane transit loss reported *separately*, but
that split requires telemetry (car speed through the pit lane) — and this
project deliberately loads `telemetry=False` for ingestion performance
(spec 4.1). Only their sum ("total pit loss") is identifiable from lap-level
timing data, so that's what's fitted; `pit_stop_stationary_s` is a declared,
bounded prior, not a fitted value (Part 14 rule 1 permits this explicitly for
values that genuinely cannot be fitted from the available data).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from pitwall.domain.driver import DriverParams
from pitwall.domain.race import RaceSnapshot

logger = logging.getLogger(__name__)

# Typical F1 stationary (box) time, well outside the noise floor of total pit
# loss (~18-30s depending on circuit) — declared prior per Part 14 rule 1,
# since telemetry is what would be needed to fit this component directly.
PIT_STOP_STATIONARY_PRIOR_S = 2.4

# A total pit loss outside this range is almost certainly not a normal stop
# (drive-through penalty, red flag pit entry, timing data glitch) and would
# distort the median if included silently.
PLAUSIBLE_TOTAL_LOSS_RANGE_S = (3.0, 90.0)


@dataclass(frozen=True)
class PitStopObservation:
    driver: str
    in_lap_number: int
    total_loss_s: float


def expected_clean_pace_s(
    params: DriverParams,
    fuel_effect_s_per_lap: float,
    compound,
    tyre_age: int,
    lap_number: int,
) -> float | None:
    tyre_model = params.tyre_models.get(compound)
    if tyre_model is None:
        return None
    return (
        params.base_pace_s
        + tyre_model.base_offset_s
        + tyre_model.degradation_s(tyre_age)
        - fuel_effect_s_per_lap * lap_number
    )


def fit_pit_loss(
    snapshot: RaceSnapshot,
    driver_params: dict[str, DriverParams],
    fuel_effect_s_per_lap: float,
) -> tuple[float, float, dict]:
    """Returns `(pit_lane_loss_s, pit_stop_stationary_s, diagnostics)`.

    `pit_lane_loss_s` is the robust (median) *total* measured pit loss across
    every stop in the race. `pit_stop_stationary_s` is the declared prior
    above — see module docstring for why it isn't fitted.
    """
    laps_by_driver: dict[str, list] = {}
    for lap in snapshot.laps:
        laps_by_driver.setdefault(lap.driver, []).append(lap)

    observations: list[PitStopObservation] = []
    excluded: list[str] = []

    for driver, laps in laps_by_driver.items():
        params = driver_params.get(driver)
        if params is None:
            continue
        laps_by_number = {lap.lap_number: lap for lap in laps}
        in_laps = sorted((lap for lap in laps if lap.is_in_lap), key=lambda lap: lap.lap_number)

        for in_lap in in_laps:
            out_lap = laps_by_number.get(in_lap.lap_number + 1)
            if out_lap is None or not out_lap.is_out_lap:
                excluded.append(f"{driver} L{in_lap.lap_number}: no matching out-lap found")
                continue
            if in_lap.lap_time_s is None or out_lap.lap_time_s is None:
                excluded.append(f"{driver} L{in_lap.lap_number}: missing in/out lap time")
                continue

            expected_in = expected_clean_pace_s(
                params, fuel_effect_s_per_lap, in_lap.compound, in_lap.tyre_life, in_lap.lap_number
            )
            expected_out = expected_clean_pace_s(
                params,
                fuel_effect_s_per_lap,
                out_lap.compound,
                out_lap.tyre_life,
                out_lap.lap_number,
            )
            if expected_in is None or expected_out is None:
                excluded.append(f"{driver} L{in_lap.lap_number}: no tyre model for compound used")
                continue

            total_loss = (in_lap.lap_time_s - expected_in) + (out_lap.lap_time_s - expected_out)

            low, high = PLAUSIBLE_TOTAL_LOSS_RANGE_S
            if not (low <= total_loss <= high):
                excluded.append(
                    f"{driver} L{in_lap.lap_number}: total loss {total_loss:.1f}s outside "
                    f"plausible range [{low}, {high}] — likely a penalty/glitch, not a normal stop"
                )
                continue

            observations.append(
                PitStopObservation(
                    driver=driver, in_lap_number=in_lap.lap_number, total_loss_s=total_loss
                )
            )

    diagnostics: dict = {
        "n_stops_used": len(observations),
        "n_stops_excluded": len(excluded),
        "exclusion_reasons": excluded,
    }

    if not observations:
        logger.warning(
            "No usable pit stops found for pit-loss fitting; race_key=%s. "
            "Falling back to RaceSnapshot.pit_lane_loss_s placeholder.",
            snapshot.race_key,
        )
        diagnostics["fallback_used"] = True
        return snapshot.pit_lane_loss_s, PIT_STOP_STATIONARY_PRIOR_S, diagnostics

    losses = np.array([o.total_loss_s for o in observations])
    diagnostics["fallback_used"] = False
    diagnostics["median_s"] = float(np.median(losses))
    diagnostics["std_s"] = float(np.std(losses))
    diagnostics["min_s"] = float(np.min(losses))
    diagnostics["max_s"] = float(np.max(losses))
    diagnostics["stationary_time_is_a_declared_prior_not_fitted"] = True

    return float(np.median(losses)), PIT_STOP_STATIONARY_PRIOR_S, diagnostics
