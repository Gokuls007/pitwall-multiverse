"""Race-level fuel effect aggregation (spec 6.4).

Primary method: `fit_pooled_fuel_effect` pools *every* driver into one
regression with a per-driver intercept, shared compound offsets, shared
per-compound age slopes, and one shared lap-number coefficient. This is a
materially stronger design than asking any single driver's own stints to
identify the trend: different drivers pit at different laps, so at any given
lap number the field is a mix of tyre ages and compounds — variation no
single driver's own race can offer, which is exactly what breaks the
fuel/tyre collinearity `tyre.fit_driver_joint` (single-driver) so often runs
into (see DECISIONS.md and tyre.py's module docstring).

This was added after `aggregate_fuel_effect` (median of per-driver estimates,
kept below as a documented fallback) turned out to systematically
*underestimate* the true lap-number trend on real data: the residual,
unmodeled part of that trend (which also folds in track evolution — rubber
laid down over the race — since spec 6.1's lap-time composition has no
separate term for it and a single lap-number coefficient can't tell the two
apart) was leaking into whichever compound a driver happened to use *later*
in the race, making it look artificially fast and breaking the expected
soft-faster-than-medium-faster-than-hard offset ordering on roughly half of
all driver/compound pairs across the catalogue. Pooling drivers fixes this by
giving the trend term far more identifying variation to work with.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from pitwall.parameters.tyre import MIN_SAMPLES_PER_COMPOUND, DriverJointFit

logger = logging.getLogger(__name__)

MIN_STINTS_TO_TRUST = 2

# Spec 6.4: "a commonly cited magnitude is on the order of a few hundredths of
# a second per lap" — used only as a last-resort fallback when no driver's own
# fit is trustworthy enough to aggregate, never as a default that silently
# overrides real data. Declared here as a bounded prior per Part 14 rule 1.
FALLBACK_FUEL_EFFECT_S_PER_LAP = 0.05

# Sanity bound (spec 6.3: "if a fit violates these, treat it as a data or
# method bug, not a discovery"). `is_identified`'s condition-number check
# catches the clearly-degenerate cases but not all of them: a compound with
# just a handful of usable laps (too few to earn its own age term, so it
# contributes only a dummy) can numerically "unstick" the condition number
# from astronomical without actually giving the regression enough real
# information to pin down the fuel effect — found on 2018 Australian GP's
# Leclerc, whose 3-stint MEDIUM-HARD-SOFT race (no repeated compound; HARD
# had only 3 post-cleaning laps) passed the condition-number check yet still
# produced fuel_coef_s_per_lap=2.13 s/lap — 40x the plausible range. This bound
# is deliberately wide (mild negative noise around a true near-zero value is
# expected and should still count towards the median) — it only rejects
# order-of-magnitude confound-leakage artifacts, not ordinary noise.
PLAUSIBLE_FUEL_EFFECT_RANGE_S_PER_LAP = (-0.3, 0.5)


def fit_pooled_fuel_effect(
    laps_by_driver: dict[str, pd.DataFrame],
    min_samples_per_compound: int = MIN_SAMPLES_PER_COMPOUND,
) -> tuple[float, dict]:
    """Primary fuel-effect fit: one regression across every driver at once,
    with a per-driver intercept (one dummy column per driver, no separate
    global constant, so no arbitrary "reference driver" is needed), shared
    per-compound age columns, and shared compound-offset dummies. Returns
    `(fuel_effect_s_per_lap, diagnostics)`.
    """
    frames = []
    for driver, frame in laps_by_driver.items():
        f = frame[frame["IsUsableForFitting"]] if "IsUsableForFitting" in frame.columns else frame
        f = f.dropna(subset=["LapTimeSeconds", "Compound", "TyreAge", "LapNumber"])
        if len(f):
            frames.append(f.assign(Driver=driver))

    diagnostics: dict = {"fallback_prior_used": False, "clipped_to_prior": False}
    if not frames:
        diagnostics["fallback_prior_used"] = True
        diagnostics["reason"] = "no usable laps across any driver"
        return FALLBACK_FUEL_EFFECT_S_PER_LAP, diagnostics

    laps = pd.concat(frames, ignore_index=True)
    drivers = sorted(laps["Driver"].unique())
    counts = laps["Compound"].value_counts()
    present = list(counts.index)
    reference = counts.idxmax()
    eligible = [c for c in present if counts[c] >= min_samples_per_compound]

    columns: list[str] = []
    X_parts = []
    for driver in drivers:
        columns.append(f"driver_{driver}")
        X_parts.append((laps["Driver"] == driver).to_numpy(dtype=float))
    columns.append("lap_number")
    X_parts.append(laps["LapNumber"].to_numpy(dtype=float))
    for c in eligible:
        columns.append(f"age_{c}")
        X_parts.append(np.where(laps["Compound"] == c, laps["TyreAge"].to_numpy(dtype=float), 0.0))
    for c in present:
        if c != reference:
            columns.append(f"dummy_{c}")
            X_parts.append((laps["Compound"] == c).to_numpy(dtype=float))

    X = np.column_stack(X_parts)
    y = laps["LapTimeSeconds"].to_numpy(dtype=float)

    column_norms = np.linalg.norm(X, axis=0)
    column_norms[column_norms == 0] = 1.0
    singular_values = np.linalg.svd(X / column_norms, compute_uv=False)
    condition_number = float(singular_values.max() / singular_values.min())
    diagnostics["condition_number"] = condition_number
    diagnostics["n_drivers_pooled"] = len(drivers)
    diagnostics["n_laps_pooled"] = len(laps)

    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    coef_by_col = dict(zip(columns, coef, strict=True))
    fuel_coef_s_per_lap = -float(coef_by_col["lap_number"])

    fitted = X @ coef
    sse = float(np.sum((y - fitted) ** 2))
    sst = float(np.sum((y - y.mean()) ** 2))
    diagnostics["r_squared"] = 1.0 - sse / sst if sst > 0 else 0.0

    low, high = PLAUSIBLE_FUEL_EFFECT_RANGE_S_PER_LAP
    if not (low <= fuel_coef_s_per_lap <= high) or condition_number > 1e6:
        logger.warning(
            "Pooled fuel-effect regression gave an implausible or ill-conditioned result "
            "(coef=%.4f, condition_number=%.2e); falling back to per-driver aggregation.",
            fuel_coef_s_per_lap,
            condition_number,
        )
        diagnostics["pooled_fit_rejected"] = True
        return None, diagnostics  # type: ignore[return-value]  -- caller falls back on None

    diagnostics["pooled_fit_rejected"] = False
    return max(fuel_coef_s_per_lap, 0.0), diagnostics


def aggregate_fuel_effect(
    per_driver_fits: dict[str, DriverJointFit], min_stints: int = MIN_STINTS_TO_TRUST
) -> tuple[float, dict]:
    """Fallback fuel-effect estimate: median of each driver's own joint-fit
    coefficient, trusted only where that driver's own regression was
    identifiable. Kept as a documented fallback for the (expected to be rare)
    case where `fit_pooled_fuel_effect` itself is rejected as ill-conditioned
    or implausible; clipped to a non-negative prior on disagreement with
    physics (spec Part 14 rule 1: never report a fabricated/impossible value).
    """
    low, high = PLAUSIBLE_FUEL_EFFECT_RANGE_S_PER_LAP
    trusted = {
        driver: fit.fuel_coef_s_per_lap
        for driver, fit in per_driver_fits.items()
        if fit.n_stints >= min_stints and fit.is_identified and low <= fit.fuel_coef_s_per_lap <= high
    }

    diagnostics: dict = {
        "n_drivers_used": len(trusted),
        "n_drivers_total": len(per_driver_fits),
        "per_driver_values": trusted,
        "fallback_prior_used": False,
        "clipped_to_prior": False,
    }

    if not trusted:
        logger.warning(
            "No driver had >=%d stints to trust for fuel effect fitting; "
            "using documented fallback prior %.3f s/lap.",
            min_stints,
            FALLBACK_FUEL_EFFECT_S_PER_LAP,
        )
        diagnostics["fallback_prior_used"] = True
        return FALLBACK_FUEL_EFFECT_S_PER_LAP, diagnostics

    median = float(np.median(list(trusted.values())))
    if median < 0:
        logger.warning(
            "Median fuel effect across %d drivers is non-positive (%.4f s/lap) — "
            "physically implausible (fuel burn cannot make cars slower); falling back "
            "to the documented prior %.3f s/lap rather than a hard-coded 0.0.",
            len(trusted),
            median,
            FALLBACK_FUEL_EFFECT_S_PER_LAP,
        )
        diagnostics["clipped_to_prior"] = True
        diagnostics["raw_median_s_per_lap"] = median
        return FALLBACK_FUEL_EFFECT_S_PER_LAP, diagnostics

    return median, diagnostics
