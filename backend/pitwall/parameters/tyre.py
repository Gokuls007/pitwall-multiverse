"""Tyre degradation fitting, jointly with fuel effect and base pace (spec 6.2-6.4).

The confound spec 6.3 calls "the single most common error in tyre modelling":
fuel burn (car gets faster over a stint) and tyre degradation (car gets slower
over a stint) partially cancel unless the model can separate them. They are
separable *within a single regression* because tyre age resets at every pit
stop while lap number climbs monotonically for the whole race — two stints on
different compounds give the regression different variation to work with for
each term. This is mathematically the same identification argument spec 6.4
describes stagewise ("fitting across multiple stints identifies both terms"),
done here as one joint least-squares fit per driver rather than a sequential
two-step estimate, which avoids ordering-dependent bias. See DECISIONS.md and
`tests/test_parameters.py::test_joint_fit_recovers_known_fuel_and_tyre_coefficients`,
the load-bearing test that proves this recovers known coefficients.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pitwall.domain.driver import TyreModel
from pitwall.domain.enums import Compound

logger = logging.getLogger(__name__)

MIN_SAMPLES_PER_COMPOUND = 4
MIN_CLIFF_SEGMENT_SAMPLES = 3
CLIFF_SSE_IMPROVEMENT_THRESHOLD = 0.15

# Sanity bound (spec 6.3): even a fast-degrading soft on a high-thermal-load
# circuit rarely exceeds a few tenths of a second per lap. Anything above this
# is confound leakage from a near-degenerate fit (the same root cause as
# negative slopes, just landing on the other side of zero), not a real
# discovery — treated identically to a negative slope: fall back to the
# pooled cross-driver estimate, or flat (0.0) if none exists.
MAX_PLAUSIBLE_SLOPE_S_PER_LAP = 0.5

# Empirically chosen (not from the spec) by comparing drivers who genuinely
# repeated a compound (condition number ~7-10) against drivers who didn't
# (~1e15-1e16) on 2019 Hungary's real data — see DECISIONS.md. There's a huge
# gap between those two populations, so the exact cutoff isn't sensitive; 1e5
# sits comfortably in it.
CONDITION_NUMBER_THRESHOLD = 1e5


@dataclass(frozen=True)
class CompoundFit:
    offset: float | None
    slope: float | None
    n_observations: int


@dataclass(frozen=True)
class DriverJointFit:
    """Pass-1 result: one driver's own joint fuel/tyre/pace regression."""

    driver: str
    base_pace_s: float
    fuel_coef_s_per_lap: float  # this driver's own estimate; race-level value is aggregated (fuel.py)
    per_compound: dict[Compound, CompoundFit]
    overall_r2: float
    n_stints: int
    notes: tuple[str, ...]
    # Whether this driver's own regression is numerically trustworthy — see
    # `_condition_number` below. Defaults to True so hand-constructed
    # DriverJointFit fixtures in tests don't need to specify it.
    is_identified: bool = True


def _count_stints(compounds: pd.Series) -> int:
    """Number of contiguous same-compound runs — a proxy for stint count that
    doesn't require a `Stint` column, so this also works on synthetic data."""
    return int((compounds != compounds.shift()).sum())


def fit_driver_joint(
    laps: pd.DataFrame, min_samples_per_compound: int = MIN_SAMPLES_PER_COMPOUND
) -> DriverJointFit:
    """Fit one driver's base pace, fuel effect, and per-compound offset/slope
    in a single joint least-squares regression.

    Expects columns `LapNumber`, `LapTimeSeconds`, `Compound`, `TyreAge`, and
    (if present) `IsUsableForFitting` — laps failing that flag are dropped.
    Design: `lap_time = const + fuel_col*lap_number + sum_c(age_c) + sum_c(dummy_c)`,
    where `age_c` is tyre age when the lap is on compound `c` (else 0) — only
    for compounds meeting `min_samples_per_compound` — and `dummy_c` is an
    offset indicator for every non-reference compound present at all.
    """
    driver = str(laps["Driver"].iloc[0]) if "Driver" in laps.columns else "?"
    if "IsUsableForFitting" in laps.columns:
        laps = laps[laps["IsUsableForFitting"]]
    laps = laps.dropna(subset=["LapTimeSeconds", "Compound", "TyreAge", "LapNumber"]).copy()

    notes: list[str] = []
    counts = laps["Compound"].value_counts()
    present = list(counts.index)
    reference = counts.idxmax()  # most-sampled compound anchors the offsets at 0

    eligible = [c for c in present if counts[c] >= min_samples_per_compound]
    for c in present:
        if c not in eligible:
            notes.append(
                f"{c}: insufficient samples ({counts[c]} < {min_samples_per_compound}) to fit "
                f"a compound-specific degradation slope; falls back to cross-driver pooling."
            )

    columns: list[str] = ["const", "lap_number"]
    X_parts = [np.ones(len(laps)), laps["LapNumber"].to_numpy(dtype=float)]

    for c in eligible:
        columns.append(f"age_{c}")
        X_parts.append(np.where(laps["Compound"] == c, laps["TyreAge"].to_numpy(dtype=float), 0.0))
    for c in present:
        if c != reference:
            columns.append(f"dummy_{c}")
            X_parts.append((laps["Compound"] == c).to_numpy(dtype=float))

    X = np.column_stack(X_parts)
    y = laps["LapTimeSeconds"].to_numpy(dtype=float)

    # An exact-rank check misses the case that actually dominates real data:
    # tyre age is *exactly* affine in lap number within any one contiguous
    # stint (age = lap_number - stint_offset), so unless some compound is
    # revisited at a different lap-number offset later in the race, the
    # design is a hair's breadth from singular — not exactly singular in
    # floating point (real cleaning exclusions, SC laps, MAD-dropped laps
    # break *exact* collinearity), but so ill-conditioned that lstsq's
    # minimum-norm solution splits the fuel/tyre confound essentially at
    # random, producing wild, unphysical coefficients (verified empirically
    # on 2019 Hungary: 17/20 drivers had condition numbers of 1e15-1e16 and
    # fuel estimates from -2.7 to +0.18 s/lap, while the 2 drivers who
    # actually repeated a compound had condition numbers of ~7-10 and
    # sensible estimates — see DECISIONS.md). Column-normalize before taking
    # the condition number so differing column scales (lap_number ~1-70 vs a
    # 0/1 dummy) don't themselves inflate it.
    column_norms = np.linalg.norm(X, axis=0)
    column_norms[column_norms == 0] = 1.0
    singular_values = np.linalg.svd(X / column_norms, compute_uv=False)
    condition_number = float(singular_values.max() / singular_values.min())
    is_identified = condition_number < CONDITION_NUMBER_THRESHOLD
    if not is_identified:
        notes.append(
            f"Design matrix is rank-deficient/ill-conditioned (condition number "
            f"{condition_number:.2e}): tyre age and lap number are collinear (or nearly so) "
            f"— no compound was revisited at a different lap-number offset, so fuel and tyre "
            f"effects cannot be reliably separated for this driver."
        )

    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    fitted = X @ coef
    residual = y - fitted
    sse = float(np.sum(residual**2))
    sst = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 0.0

    coef_by_col = dict(zip(columns, coef, strict=True))
    base_pace_s = float(coef_by_col["const"])
    fuel_coef_s_per_lap = -float(coef_by_col["lap_number"])
    if fuel_coef_s_per_lap < 0:
        notes.append(
            f"Fuel effect estimated non-positive ({fuel_coef_s_per_lap:.4f} s/lap) for this "
            f"driver — likely sampling noise on a short stint; expect cross-driver "
            f"aggregation (fuel.py) to smooth this out."
        )

    per_compound: dict[Compound, CompoundFit] = {}
    for c in present:
        offset = 0.0 if c == reference else float(coef_by_col.get(f"dummy_{c}", 0.0))
        slope = float(coef_by_col[f"age_{c}"]) if c in eligible else None
        if slope is not None and slope < 0:
            notes.append(
                f"{c}: fitted degradation slope is negative ({slope:.4f} s/lap) — tyres "
                f"getting faster with age is not physical; treat as a fit/data issue."
            )
        per_compound[Compound(c)] = CompoundFit(
            offset=offset, slope=slope, n_observations=int(counts[c])
        )

    return DriverJointFit(
        driver=driver,
        base_pace_s=base_pace_s,
        fuel_coef_s_per_lap=fuel_coef_s_per_lap,
        per_compound=per_compound,
        overall_r2=r2,
        n_stints=_count_stints(laps["Compound"]),
        notes=tuple(notes),
        is_identified=is_identified,
    )


def _detect_cliff(
    ages: np.ndarray, residuals: np.ndarray
) -> tuple[int | None, float | None, float]:
    """Test whether a piecewise-linear (cliff) model fits a compound's
    age-vs-residual-time data materially better than a single linear slope
    (spec 6.3 point 3). Returns (cliff_lap, cliff_deg_s_per_lap, r_squared)
    for whichever model wins; cliff_lap is None if linear wins.
    """
    n = len(ages)
    order = np.argsort(ages)
    ages_sorted, resid_sorted = ages[order], residuals[order]

    # Baseline: single linear slope through the origin-relative residuals.
    X_linear = np.column_stack([np.ones(n), ages_sorted])
    coef_linear, _, _, _ = np.linalg.lstsq(X_linear, resid_sorted, rcond=None)
    sse_linear = float(np.sum((resid_sorted - X_linear @ coef_linear) ** 2))

    if n < 2 * MIN_CLIFF_SEGMENT_SAMPLES + 1:
        sst = float(np.sum((resid_sorted - resid_sorted.mean()) ** 2))
        r2 = 1.0 - sse_linear / sst if sst > 0 else 0.0
        return None, None, r2

    best_breakpoint = None
    best_sse = sse_linear
    best_coef = None
    min_age, max_age = int(ages_sorted.min()), int(ages_sorted.max())
    for breakpoint in range(min_age + MIN_CLIFF_SEGMENT_SAMPLES, max_age - MIN_CLIFF_SEGMENT_SAMPLES + 1):
        post = np.maximum(ages_sorted - breakpoint, 0.0)
        n_post = int(np.sum(ages_sorted > breakpoint))
        n_pre = int(np.sum(ages_sorted <= breakpoint))
        if n_post < MIN_CLIFF_SEGMENT_SAMPLES or n_pre < MIN_CLIFF_SEGMENT_SAMPLES:
            continue
        X_piecewise = np.column_stack([np.ones(n), ages_sorted, post])
        coef, _, _, _ = np.linalg.lstsq(X_piecewise, resid_sorted, rcond=None)
        sse = float(np.sum((resid_sorted - X_piecewise @ coef) ** 2))
        if sse < best_sse:
            best_sse = sse
            best_breakpoint = breakpoint
            best_coef = coef

    sst = float(np.sum((resid_sorted - resid_sorted.mean()) ** 2))
    if best_breakpoint is None:
        r2 = 1.0 - sse_linear / sst if sst > 0 else 0.0
        return None, None, r2

    improvement = (sse_linear - best_sse) / sse_linear if sse_linear > 0 else 0.0
    pre_slope = float(best_coef[1])
    cliff_slope = pre_slope + float(best_coef[2])
    physically_sensible = cliff_slope > pre_slope

    if improvement > CLIFF_SSE_IMPROVEMENT_THRESHOLD and physically_sensible:
        r2 = 1.0 - best_sse / sst if sst > 0 else 0.0
        return best_breakpoint, cliff_slope, r2

    r2 = 1.0 - sse_linear / sst if sst > 0 else 0.0
    return None, None, r2


@dataclass(frozen=True)
class PooledCompoundFit:
    offset: float
    slope: float
    r_squared: float
    n_observations: int
    n_drivers: int


def pool_compound_fits(
    per_driver_fits: dict[str, DriverJointFit],
) -> dict[Compound, PooledCompoundFit]:
    """Cross-driver pooled fallback for a (driver, compound) pair with too few
    of that driver's own laps (spec 6.3 point 4). Pools every driver's own
    fitted offset/slope for a compound (only where that driver had enough
    data to fit it directly) via a simple unweighted mean — deliberately
    simple since this is already a fallback path, not the primary estimate.
    """
    by_compound: dict[Compound, list[CompoundFit]] = {}
    for fit in per_driver_fits.values():
        if not fit.is_identified:
            continue  # this driver's own slope estimates aren't trustworthy either
        for compound, compound_fit in fit.per_compound.items():
            # Exclude physically-impossible (negative or absurdly large)
            # individual slopes from the pool itself — otherwise one noisy
            # driver drags the weighted mean for everyone who falls back to it
            # (spec 6.3's positivity + sanity-bound prior).
            if compound_fit.slope is not None and 0 <= compound_fit.slope <= MAX_PLAUSIBLE_SLOPE_S_PER_LAP:
                by_compound.setdefault(compound, []).append(compound_fit)

    pooled = {}
    for compound, fits in by_compound.items():
        offsets = [f.offset for f in fits]
        slopes = [f.slope for f in fits]
        weights = [f.n_observations for f in fits]
        total_n = sum(weights)
        weighted_slope = sum(s * w for s, w in zip(slopes, weights, strict=True)) / total_n
        weighted_offset = sum(o * w for o, w in zip(offsets, weights, strict=True)) / total_n
        pooled[compound] = PooledCompoundFit(
            offset=weighted_offset,
            slope=weighted_slope,
            r_squared=float("nan"),  # pooled across drivers; no single residual set to score
            n_observations=total_n,
            n_drivers=len(fits),
        )
    return pooled


def fit_driver_final(
    laps: pd.DataFrame,
    fuel_effect_s_per_lap: float,
    pooled: dict[Compound, PooledCompoundFit],
    min_samples_per_compound: int = MIN_SAMPLES_PER_COMPOUND,
) -> tuple[float, float, dict[Compound, TyreModel], tuple[str, ...]]:
    """Pass 2: refit base pace and per-compound tyre models with the
    race-level fuel effect held fixed (spec 6.3 point 2 — "having first
    removed the fuel effect"), falling back to pooled cross-driver estimates
    for compounds this driver didn't sample enough of.

    Offset and degradation slope are fit *jointly* per compound (one age_c
    column plus one dummy_c column per eligible compound, all in the same
    regression) rather than offset-then-slope in two separate steps. An
    earlier two-step version computed each compound's offset as a plain group
    mean of fuel-adjusted lap time, which silently conflates pace with however
    much tyre wear that compound's *sampled* laps happened to average — found
    on 2019 Hungary's Hamilton, whose HARD laps averaged tyre age 9 against
    MEDIUM's 15, making HARD look faster than MEDIUM in the naive group mean
    even though HARD is the physically slower compound. Controlling for age
    in the same regression that estimates the offset removes that bias — see
    DECISIONS.md.

    Returns (base_pace_s, pace_std_s, tyre_models, notes).
    """
    if "IsUsableForFitting" in laps.columns:
        laps = laps[laps["IsUsableForFitting"]]
    laps = laps.dropna(subset=["LapTimeSeconds", "Compound", "TyreAge", "LapNumber"]).copy()

    notes: list[str] = []
    # Remove the (race-level, now-fixed) fuel contribution so what's left is
    # purely base pace + compound offset + tyre age, per compound.
    laps["FuelAdjusted"] = laps["LapTimeSeconds"] + fuel_effect_s_per_lap * laps["LapNumber"]

    counts = laps["Compound"].value_counts()
    present = list(counts.index)
    reference = counts.idxmax()
    eligible = [c for c in present if counts[c] >= min_samples_per_compound]

    columns = ["const"]
    X_parts = [np.ones(len(laps))]
    for c in eligible:
        columns.append(f"age_{c}")
        X_parts.append(np.where(laps["Compound"] == c, laps["TyreAge"].to_numpy(dtype=float), 0.0))
    for c in present:
        if c != reference:
            columns.append(f"dummy_{c}")
            X_parts.append((laps["Compound"] == c).to_numpy(dtype=float))

    X = np.column_stack(X_parts)
    y = laps["FuelAdjusted"].to_numpy(dtype=float)
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    coef_by_col = dict(zip(columns, coef, strict=True))

    base_pace_s = float(coef_by_col["const"])
    residual = y - X @ coef
    pace_std_s = float(np.std(residual))
    sst = float(np.sum((y - y.mean()) ** 2))

    tyre_models: dict[Compound, TyreModel] = {}
    for c in present:
        offset = 0.0 if c == reference else float(coef_by_col.get(f"dummy_{c}", 0.0))
        compound_mask = (laps["Compound"] == c).to_numpy()
        n_obs = int(counts[c])

        if c in eligible:
            linear_slope = float(coef_by_col[f"age_{c}"])
            compound_resid = residual[compound_mask]
            ages = laps.loc[compound_mask, "TyreAge"].to_numpy(dtype=float)
            compound_sse = float(np.sum(compound_resid**2))
            r2 = 1.0 - compound_sse / sst if sst > 0 else 0.0
            cliff_lap, cliff_slope, _ = _detect_cliff(ages, compound_resid + linear_slope * ages)

            # Spec 6.3: "degradation rates should be positive... if a fit violates
            # these, treat it as a data or method bug, not a discovery. Log it
            # loudly." Out-of-bounds is common on noisy small samples (low r2)
            # or near-degenerate fits — this driver's own slope estimate is
            # simply wrong (sign or magnitude), not a real discovery. Prefer the
            # cross-driver pooled estimate for *this* compound if it's
            # physically sensible; only default to flat (0.0) if no pooled
            # estimate exists either.
            implausible = linear_slope < 0 or linear_slope > MAX_PLAUSIBLE_SLOPE_S_PER_LAP
            if implausible:
                pooled_fit = pooled.get(Compound(c))
                pooled_is_sensible = (
                    pooled_fit is not None and 0 <= pooled_fit.slope <= MAX_PLAUSIBLE_SLOPE_S_PER_LAP
                )
                if pooled_is_sensible:
                    notes.append(
                        f"{c}: this driver's own fit gave an implausible degradation slope "
                        f"({linear_slope:.4f} s/lap, r2={r2:.3f}, n={n_obs}) — not physical; "
                        f"using the cross-driver pooled slope ({pooled_fit.slope:.4f} s/lap, "
                        f"{pooled_fit.n_drivers} drivers) instead."
                    )
                    linear_slope = pooled_fit.slope
                    cliff_lap, cliff_slope = None, None
                else:
                    notes.append(
                        f"{c}: this driver's own fit gave an implausible degradation slope "
                        f"({linear_slope:.4f} s/lap, r2={r2:.3f}, n={n_obs}) and no physically "
                        f"sensible pooled fallback was available either; defaulting to flat "
                        f"(0.0 s/lap) rather than reporting a physically impossible value."
                    )
                    linear_slope = 0.0
                    cliff_lap, cliff_slope = None, None
        elif Compound(c) in pooled:
            pooled_fit = pooled[Compound(c)]
            linear_slope = pooled_fit.slope
            offset = pooled_fit.offset  # pooled offset is more reliable than this driver's own 1-2 laps
            cliff_lap, cliff_slope, r2 = None, None, pooled_fit.r_squared
            notes.append(
                f"{c}: using cross-driver pooled degradation ({pooled_fit.n_drivers} drivers, "
                f"{pooled_fit.n_observations} laps) — this driver had only {counts[c]} laps on it."
            )
        else:
            linear_slope = 0.0
            cliff_lap, cliff_slope, r2 = None, None, float("nan")
            notes.append(
                f"{c}: no cross-driver pooled data available either ({counts[c]} laps, no other "
                f"driver had enough); degradation slope defaulted to 0.0 — treat as unreliable."
            )

        tyre_models[Compound(c)] = TyreModel(
            compound=Compound(c),
            base_offset_s=offset,
            linear_deg_s_per_lap=linear_slope,
            cliff_lap=cliff_lap,
            cliff_deg_s_per_lap=cliff_slope,
            r_squared=r2,
            n_observations=n_obs,
        )

    return base_pace_s, pace_std_s, tyre_models, tuple(notes)
