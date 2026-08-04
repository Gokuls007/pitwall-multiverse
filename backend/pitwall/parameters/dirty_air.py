"""Dirty-air pace penalty fitting (spec 6.6) — kept distinct from traffic (6.9).

For every *usable* lap with a recorded gap to the car ahead, the lap-time
excess over the fitted clean-air expectation is regressed against that gap.
Pooled across drivers, per spec ("per-driver dirty-air sensitivity is not
identifiable from one race's data").

Traffic vs dirty air, and why they must be separated before fitting: spec 6.6
(dirty air — aero wake from a car close ahead, whether or not it's racing you)
and spec 6.9 (traffic — losing time stuck behind a car "not racing for
position," e.g. a lapped backmarker) are explicitly two different mechanisms
in the spec's own lap-time composition (6.1 lists them as separate terms).
Fitting a single gap-vs-excess regression from *all* usable laps conflates
them: a following car close behind a genuine on-pace rival and a leader
about to lap a backmarker can show the same small `gap_to_ahead_s`, but the
backmarker case is a wildly different (much larger, differently-caused) pace
loss. On a street circuit (Monaco, Singapore) where the whole field is
bunched together for most of the race, most "close gap" observations are the
backmarker case, not genuine wheel-to-wheel dirty air — this is exactly why
those two races fitted implausibly large "dirty air" penalties (3-5 s/lap,
spec 6.6's own prior tops out around a few tenths) while other races
degenerated to a near-zero, negative-R2 fit: both are the same underlying
problem, one regressor trying to represent two effects.

Mitigation (not a full traffic model — that's Part 6.9's own territory,
future work): a lap only counts as a dirty-air observation if the car ahead
was running *similar* pace that lap (within `TRAFFIC_DISPARITY_THRESHOLD_S`).
A backmarker about to be lapped is, almost definitionally, running much
slower than the car catching it — this heuristic excludes exactly that case
without requiring a full lapped/not-lapped model.
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
_MAX_PENALTY_BOUNDS = (0.0, 5.0)
_DECAY_SCALE_BOUNDS = (0.05, 10.0)

# Not from the spec — chosen to separate "following a car racing at a similar
# pace" (dirty air, 6.6) from "closing on a car that isn't" (traffic, 6.9). A
# genuine on-pace rival's lap time is typically within a few tenths; a
# backmarker about to be lapped is usually 1.5s+ off the pace of the car
# catching it. See module docstring.
TRAFFIC_DISPARITY_THRESHOLD_S = 1.5

# A fit this poor (worse than, or barely better than, predicting the mean) is
# not a signal, regardless of how plausible-looking its parameters are — spec
# 6.3's "if a fit violates these, treat it as a data or method bug" logic
# extended to dirty air specifically because bound-pinned curve_fit results
# can look superficially legitimate (they converged, no exception) while
# being fit to noise. Held to the same standard as the tyre-model sanity
# bounds rather than left as a quieter "poor R2" footnote.
MIN_ACCEPTABLE_R_SQUARED = 0.05

# Reference gap beyond which dirty air is assumed negligible (spec 6.6:
# "negligible beyond roughly two seconds" — 5s gives margin). Used only to
# select the "isolated" subsample that anchors the asymptote below, not as a
# hard cutoff in the fitted curve itself.
ASYMPTOTE_REFERENCE_GAP_S = 5.0
MIN_ISOLATED_OBSERVATIONS = 30


def fit_pooled_dirty_air_across_races(
    races: list[tuple[RaceSnapshot, dict[str, DriverParams], float]],
) -> tuple[DirtyAirModel, float, dict]:
    """Pool (gap, excess) observations across every race in `races` — each
    entry `(snapshot, that race's already-fitted driver_params, that race's
    fuel_effect_s_per_lap)` — and fit one dirty-air curve plus a base-pace
    correction from the combined sample. `fit_dirty_air` above fits this per
    race and is rejected on every catalogue race (not enough power from one
    race's data, spec 6.6's own admission that per-driver sensitivity isn't
    identifiable from a single race, extended here to the curve itself); this
    is the cross-race pool that gives it enough.

    Critical correction this function makes that a naive pooled fit would
    miss: `expected_clean_pace_s`'s `base_pace_s` is the intercept of a
    regression fit on *all* usable green-flag laps, most of which had some
    car ahead — so it's average-traffic pace, not zero-traffic pace, and
    every gap bucket's raw excess is measured against the wrong zero point.
    Confirmed directly: pooling the same 5,752 laps that went into the
    per-driver fits gives a lap-weighted mean residual of -0.253s, not
    ~0 — a real, non-trivial shift baked in by the isotonic offset
    projection and pooled-cell fallbacks applied after the OLS fit, not
    noise. The isolated subsample (gap >= `ASYMPTOTE_REFERENCE_GAP_S`) is
    used as the empirical zero-traffic reference instead: excess is
    corrected by subtracting its mean (the "asymptote") before the curve is
    fit, and that same asymptote is returned separately so callers can shift
    `base_pace_s` back to genuinely represent clean-air pace. Without this,
    `fit_dirty_air`'s per-race attempts were fitting an exponential that
    decays to *zero* onto data whose true large-gap asymptote is around
    -0.47s — no parameter choice can do that, which is exactly how those
    attempts landed on negative R² and bound-pinned parameters. The model
    wasn't wrong about the phenomenon; it was missing the offset.

    Returns `(DirtyAirModel, base_pace_correction_s, diagnostics)`. Callers
    add `base_pace_correction_s` to every driver's `base_pace_s` (uniformly
    — this pooled fit has no per-driver resolution to offer) before using
    the returned model.
    """
    gaps: list[float] = []
    excess: list[float] = []

    for snapshot, driver_params, fuel_effect_s_per_lap in races:
        ahead_lap_time = _ahead_lap_time_by_driver_lap(snapshot)
        for lap in snapshot.laps:
            if not lap.is_usable_for_fitting or lap.lap_time_s is None:
                continue
            if lap.gap_to_ahead_s is None:
                continue
            ahead_time = ahead_lap_time.get((lap.driver, lap.lap_number))
            if ahead_time is None:
                continue
            if abs(lap.lap_time_s - ahead_time) > TRAFFIC_DISPARITY_THRESHOLD_S:
                continue
            params = driver_params.get(lap.driver)
            if params is None:
                continue
            expected = expected_clean_pace_s(
                params, fuel_effect_s_per_lap, lap.compound, lap.tyre_life, lap.lap_number
            )
            if expected is None:
                continue
            gaps.append(lap.gap_to_ahead_s)
            excess.append(lap.lap_time_s - expected)

    diagnostics: dict = {"n_pooled_observations": len(gaps)}
    if len(gaps) < 20:
        model, fb_diag = _fallback(f"only {len(gaps)} pooled dirty-air observations (<20)", len(gaps))
        return model, 0.0, {**diagnostics, **fb_diag}

    gaps_arr = np.array(gaps)
    excess_arr = np.array(excess)

    isolated_mask = gaps_arr >= ASYMPTOTE_REFERENCE_GAP_S
    n_isolated = int(isolated_mask.sum())
    diagnostics["n_isolated_observations"] = n_isolated
    diagnostics["n_tightest_bucket_lt_0.15s"] = int(np.sum(gaps_arr < 0.15))
    if n_isolated < MIN_ISOLATED_OBSERVATIONS:
        model, fb_diag = _fallback(
            f"only {n_isolated} isolated (gap>={ASYMPTOTE_REFERENCE_GAP_S}s) observations "
            f"to anchor the asymptote (<{MIN_ISOLATED_OBSERVATIONS})",
            len(gaps),
        )
        return model, 0.0, {**diagnostics, **fb_diag}

    asymptote_s = float(excess_arr[isolated_mask].mean())
    diagnostics["asymptote_s"] = asymptote_s
    corrected_excess = excess_arr - asymptote_s

    try:
        (max_penalty, decay_scale), _ = curve_fit(
            _exp_decay,
            gaps_arr,
            corrected_excess,
            p0=[0.5, 1.0],
            bounds=(
                [_MAX_PENALTY_BOUNDS[0], _DECAY_SCALE_BOUNDS[0]],
                [_MAX_PENALTY_BOUNDS[1], _DECAY_SCALE_BOUNDS[1]],
            ),
            maxfev=5000,
        )
    except RuntimeError as exc:
        model, fb_diag = _fallback(f"pooled curve_fit did not converge ({exc})", len(gaps))
        return model, 0.0, {**diagnostics, **fb_diag}

    predicted = _exp_decay(gaps_arr, max_penalty, decay_scale)
    sse = float(np.sum((corrected_excess - predicted) ** 2))
    sst = float(np.sum((corrected_excess - corrected_excess.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 0.0
    diagnostics["r_squared_before_acceptance_check"] = r2

    def _pinned(value: float, bounds: tuple[float, float]) -> bool:
        span = bounds[1] - bounds[0]
        return abs(value - bounds[0]) < 0.01 * span or abs(value - bounds[1]) < 0.01 * span

    max_pinned = _pinned(max_penalty, _MAX_PENALTY_BOUNDS)
    decay_pinned = _pinned(decay_scale, _DECAY_SCALE_BOUNDS)

    if r2 < MIN_ACCEPTABLE_R_SQUARED or max_pinned or decay_pinned:
        reason = (
            f"pooled fit r2={r2:.3f} (min acceptable {MIN_ACCEPTABLE_R_SQUARED}), "
            f"max_penalty_pinned={max_pinned}, decay_scale_pinned={decay_pinned} "
            f"— fit converged but is not a real signal"
        )
        model, fb_diag = _fallback(reason, len(gaps))
        return model, 0.0, {**diagnostics, **fb_diag}

    diagnostics["fallback_used"] = False
    diagnostics["r_squared"] = r2
    return DirtyAirModel(float(max_penalty), float(decay_scale), r2, len(gaps)), asymptote_s, diagnostics


def _exp_decay(gap: np.ndarray, max_penalty_s: float, decay_scale_s: float) -> np.ndarray:
    return max_penalty_s * np.exp(-gap / decay_scale_s)


def _ahead_lap_time_by_driver_lap(snapshot: RaceSnapshot) -> dict[tuple[str, int], float]:
    """For each (driver, lap_number), the lap time of the car immediately
    ahead in track position on that same lap — used to detect traffic."""
    by_lap: dict[int, list] = {}
    for lap in snapshot.laps:
        if lap.position > 0 and lap.lap_time_s is not None:
            by_lap.setdefault(lap.lap_number, []).append(lap)

    result: dict[tuple[str, int], float] = {}
    for lap_number, laps in by_lap.items():
        ordered = sorted(laps, key=lambda lap: lap.position)
        for i in range(1, len(ordered)):
            result[(ordered[i].driver, lap_number)] = ordered[i - 1].lap_time_s
    return result


def _fallback(reason: str, n_observations: int) -> tuple[DirtyAirModel, dict]:
    logger.warning("Dirty-air fit rejected (%s); falling back to spec 6.6 prior midpoint.", reason)
    fallback_max = float(np.mean(SANITY_MAX_PENALTY_RANGE_S))
    fallback_decay = float(np.mean(SANITY_DECAY_SCALE_RANGE_S))
    diagnostics = {"fallback_used": True, "fallback_reason": reason}
    return DirtyAirModel(fallback_max, fallback_decay, float("nan"), n_observations), diagnostics


def fit_dirty_air(
    snapshot: RaceSnapshot,
    driver_params: dict[str, DriverParams],
    fuel_effect_s_per_lap: float,
) -> tuple[DirtyAirModel, dict]:
    ahead_lap_time = _ahead_lap_time_by_driver_lap(snapshot)

    gaps: list[float] = []
    excess: list[float] = []
    skipped_no_params = 0
    skipped_no_gap = 0
    skipped_no_ahead_time = 0
    skipped_as_traffic = 0

    for lap in snapshot.laps:
        if not lap.is_usable_for_fitting or lap.lap_time_s is None:
            continue
        if lap.gap_to_ahead_s is None:
            skipped_no_gap += 1
            continue

        ahead_time = ahead_lap_time.get((lap.driver, lap.lap_number))
        if ahead_time is None:
            skipped_no_ahead_time += 1
            continue
        if abs(lap.lap_time_s - ahead_time) > TRAFFIC_DISPARITY_THRESHOLD_S:
            skipped_as_traffic += 1
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
        "n_skipped_no_ahead_time": skipped_no_ahead_time,
        "n_skipped_as_traffic": skipped_as_traffic,
        "n_skipped_no_driver_params": skipped_no_params,
    }

    if len(gaps) < 20:
        model, fb_diag = _fallback(f"only {len(gaps)} dirty-air observations (<20)", len(gaps))
        return model, {**diagnostics, **fb_diag}

    gaps_arr = np.array(gaps)
    excess_arr = np.array(excess)

    try:
        (max_penalty, decay_scale), _ = curve_fit(
            _exp_decay,
            gaps_arr,
            excess_arr,
            p0=[0.3, 1.0],
            bounds=(
                [_MAX_PENALTY_BOUNDS[0], _DECAY_SCALE_BOUNDS[0]],
                [_MAX_PENALTY_BOUNDS[1], _DECAY_SCALE_BOUNDS[1]],
            ),
            maxfev=5000,
        )
    except RuntimeError as exc:
        model, fb_diag = _fallback(f"curve_fit did not converge ({exc})", len(gaps))
        return model, {**diagnostics, **fb_diag}

    predicted = _exp_decay(gaps_arr, max_penalty, decay_scale)
    sse = float(np.sum((excess_arr - predicted) ** 2))
    sst = float(np.sum((excess_arr - excess_arr.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 0.0
    diagnostics["r_squared_before_acceptance_check"] = r2

    # Bound-pinned (within 1% of either edge) is the signature of curve_fit
    # finding no real signal and settling at whatever boundary minimizes SSE
    # least badly — a "successful" fit in the sense of not raising, but not a
    # real result. Held to the same standard as a low R2.
    def _pinned(value: float, bounds: tuple[float, float]) -> bool:
        span = bounds[1] - bounds[0]
        return abs(value - bounds[0]) < 0.01 * span or abs(value - bounds[1]) < 0.01 * span

    max_pinned = _pinned(max_penalty, _MAX_PENALTY_BOUNDS)
    decay_pinned = _pinned(decay_scale, _DECAY_SCALE_BOUNDS)

    if r2 < MIN_ACCEPTABLE_R_SQUARED or max_pinned or decay_pinned:
        reason = (
            f"r2={r2:.3f} (min acceptable {MIN_ACCEPTABLE_R_SQUARED}), "
            f"max_penalty_pinned={max_pinned}, decay_scale_pinned={decay_pinned} "
            f"— fit converged but is not a real signal"
        )
        model, fb_diag = _fallback(reason, len(gaps))
        return model, {**diagnostics, **fb_diag}

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
