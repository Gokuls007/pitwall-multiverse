"""Dirty-air pace penalty fitting (spec 6.6).

For every *usable* lap with a recorded gap to the car ahead — usable laps
deliberately include traffic-affected laps (spec 4.2 point 4: excluding them
would remove exactly the data this model needs) — the lap-time excess over
the fitted clean-air expectation is regressed against that gap. Pooled across
drivers, per spec ("per-driver dirty-air sensitivity is not identifiable from
one race's data").

Fitted as single-exponential decay: `penalty(gap) = max_penalty_s *
exp(-gap/decay_scale_s)` — maximal at gap=0, saturating to ~0 by a few
seconds, matching the shape spec 6.6 describes. Fit via `scipy.optimize.curve_fit`
since it's nonlinear in `decay_scale_s`.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.optimize import curve_fit

from pitwall.domain.driver import DriverParams
from pitwall.domain.race import DirtyAirModel, RaceSnapshot
from pitwall.parameters.pit_loss import expected_clean_pace_s

logger = logging.getLogger(__name__)

# Spec 6.6's own sanity-check prior: "a few tenths of a second per lap at close
# following distances, tapering to negligible beyond roughly two seconds."
# Used only to bound the curve fit's initial guess and to flag (not silently
# accept) a fit that lands far outside this range.
SANITY_MAX_PENALTY_RANGE_S = (0.05, 3.0)
SANITY_DECAY_SCALE_RANGE_S = (0.2, 5.0)


def _exp_decay(gap: np.ndarray, max_penalty_s: float, decay_scale_s: float) -> np.ndarray:
    return max_penalty_s * np.exp(-gap / decay_scale_s)


def fit_dirty_air(
    snapshot: RaceSnapshot,
    driver_params: dict[str, DriverParams],
    fuel_effect_s_per_lap: float,
) -> tuple[DirtyAirModel, dict]:
    gaps: list[float] = []
    excess: list[float] = []
    skipped_no_params = 0
    skipped_no_gap = 0

    for lap in snapshot.laps:
        if not lap.is_usable_for_fitting or lap.lap_time_s is None:
            continue
        if lap.gap_to_ahead_s is None:
            skipped_no_gap += 1
            continue
        params = driver_params.get(lap.driver)
        if params is None:
            skipped_no_params += 1
            continue
        expected = expected_clean_pace_s(
            params, fuel_effect_s_per_lap, lap.compound, lap.tyre_life, lap.lap_number
        )
        if expected is None:
            skipped_no_params += 1
            continue
        gaps.append(lap.gap_to_ahead_s)
        excess.append(lap.lap_time_s - expected)

    diagnostics: dict = {
        "n_observations": len(gaps),
        "n_skipped_no_gap": skipped_no_gap,
        "n_skipped_no_driver_params": skipped_no_params,
    }

    if len(gaps) < 20:
        logger.warning(
            "Only %d gap observations for dirty-air fitting on %s; falling back to "
            "the spec 6.6 prior midpoint.",
            len(gaps),
            snapshot.race_key,
        )
        diagnostics["fallback_used"] = True
        fallback_max = float(np.mean(SANITY_MAX_PENALTY_RANGE_S))
        fallback_decay = float(np.mean(SANITY_DECAY_SCALE_RANGE_S))
        return DirtyAirModel(fallback_max, fallback_decay, float("nan"), len(gaps)), diagnostics

    gaps_arr = np.array(gaps)
    excess_arr = np.array(excess)

    try:
        (max_penalty, decay_scale), _ = curve_fit(
            _exp_decay,
            gaps_arr,
            excess_arr,
            p0=[0.3, 1.0],
            bounds=([0.0, 0.05], [5.0, 10.0]),
            maxfev=5000,
        )
    except RuntimeError as exc:
        logger.warning("Dirty-air curve fit failed to converge (%s); using prior fallback.", exc)
        diagnostics["fallback_used"] = True
        diagnostics["fit_error"] = str(exc)
        fallback_max = float(np.mean(SANITY_MAX_PENALTY_RANGE_S))
        fallback_decay = float(np.mean(SANITY_DECAY_SCALE_RANGE_S))
        return DirtyAirModel(fallback_max, fallback_decay, float("nan"), len(gaps)), diagnostics

    predicted = _exp_decay(gaps_arr, max_penalty, decay_scale)
    sse = float(np.sum((excess_arr - predicted) ** 2))
    sst = float(np.sum((excess_arr - excess_arr.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 0.0

    diagnostics["fallback_used"] = False
    diagnostics["r_squared"] = r2

    low_max, high_max = SANITY_MAX_PENALTY_RANGE_S
    if not (low_max <= max_penalty <= high_max):
        diagnostics.setdefault("warnings", []).append(
            f"Fitted max_penalty_s={max_penalty:.3f} outside spec 6.6's sanity prior "
            f"[{low_max}, {high_max}] — plausible on a low-degradation or very high-deg "
            f"circuit, but worth a manual look."
        )

    return DirtyAirModel(float(max_penalty), float(decay_scale), r2, len(gaps)), diagnostics
