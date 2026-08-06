"""Orchestrator: `RaceSnapshot` -> fitted `RaceParameters` (spec Part 12 Phase 2).

Fitting order matters and mirrors the dependency chain:
1. Per-driver joint pace/tyre/fuel regression (`tyre.fit_driver_joint`) —
   pass 1, gives each driver's own (noisy) fuel estimate.
2. Aggregate those into one race-level fuel effect (`fuel.aggregate_fuel_effect`).
3. Pool per-compound degradation across drivers, for the sparse-data fallback
   (`tyre.pool_compound_fits`).
4. Refit each driver's base pace + tyre models with the race-level fuel effect
   held fixed (`tyre.fit_driver_final`), falling back to a teammate's fit for
   drivers with too few laps to fit at all (spec 6.2).
5. Pit loss, dirty air, overtake difficulty, SC/VSC multipliers — each only
   needs the finished per-driver params and the race-level fuel effect.

Every fallback taken along the way is recorded in `RaceParameters.fit_diagnostics`
(spec 8.4: "Every fallback... must be recorded in diagnostics").
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from pitwall.domain.driver import DriverParams, TyreModel
from pitwall.domain.enums import Compound
from pitwall.domain.race import DirtyAirModel, RaceParameters, RaceSnapshot
from pitwall.parameters import dirty_air, fuel, overtaking, pace, pit_loss, tyre
from pitwall.parameters.pit_loss import expected_clean_pace_s

logger = logging.getLogger(__name__)

MIN_LAPS_FOR_OWN_FIT = 6

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FITTED_DIR = _REPO_ROOT / "data" / "fitted"

# Declared priors (Part 14 rule 1) used only when a race has no SC or no VSC
# laps at all to fit a multiplier from — most of this project's catalogue
# races have neither (see DECISIONS.md), so these are exercised often.
# Typical real-world magnitudes: full SC bunches the field more (slower) than
# a VSC, which asks drivers to hold a fixed delta rather than following a car.
SC_MULTIPLIER_PRIOR = 1.50
VSC_MULTIPLIER_PRIOR = 1.35


def _laps_frame(snapshot: RaceSnapshot, driver: str) -> pd.DataFrame:
    rows = [
        {
            "Driver": lap.driver,
            "LapNumber": lap.lap_number,
            "LapTimeSeconds": lap.lap_time_s,
            "Compound": lap.compound.value,
            "TyreAge": lap.tyre_life,
            "IsUsableForFitting": lap.is_usable_for_fitting,
        }
        for lap in snapshot.laps
        if lap.driver == driver
    ]
    return pd.DataFrame(rows)


def _sc_vsc_multipliers(
    snapshot: RaceSnapshot,
    driver_params: dict[str, DriverParams],
    fuel_effect_s_per_lap: float,
) -> tuple[float, float, dict]:
    """Spec 6.8: fit the SC/VSC lap-time multiplier from the race's own
    SC/VSC laps. Pit in/out laps are excluded (their extra time is pit loss,
    not the SC/VSC effect itself)."""
    sc_ratios: list[float] = []
    vsc_ratios: list[float] = []

    for lap in snapshot.laps:
        if lap.is_in_lap or lap.is_out_lap or lap.lap_time_s is None:
            continue
        codes = set(lap.track_status)
        is_sc = "4" in codes
        is_vsc = bool(codes & {"6", "7"})
        if not (is_sc or is_vsc):
            continue
        params = driver_params.get(lap.driver)
        if params is None:
            continue
        expected = expected_clean_pace_s(
            params, fuel_effect_s_per_lap, lap.compound, lap.tyre_life, lap.lap_number
        )
        if expected is None or expected <= 0:
            continue
        ratio = lap.lap_time_s / expected
        (sc_ratios if is_sc else vsc_ratios).append(ratio)

    diagnostics: dict = {
        "n_sc_laps": len(sc_ratios),
        "n_vsc_laps": len(vsc_ratios),
    }

    if sc_ratios:
        sc_mult = float(np.median(sc_ratios))
    else:
        sc_mult = SC_MULTIPLIER_PRIOR
        diagnostics["sc_multiplier_is_prior_fallback"] = True

    if vsc_ratios:
        vsc_mult = float(np.median(vsc_ratios))
    else:
        vsc_mult = VSC_MULTIPLIER_PRIOR
        diagnostics["vsc_multiplier_is_prior_fallback"] = True

    return sc_mult, vsc_mult, diagnostics


# Not identifiable from a single race's data (spec Part 14 rule 1's explicit
# escape hatch: a hand-set, bounded, declared prior where fitting isn't
# possible). Compound choice and race phase are collinear across the *entire*
# field — nearly everyone runs softs early and hards late — so no time-trend
# term, however shaped, can separate "compound identity" from "how far into
# the race" using only this race's own data (see DECISIONS.md: the pooled
# cross-driver fuel-effect fit didn't move the ordering-violation rate at all,
# which is what you'd expect from a collinearity, not an underestimated
# trend). The adjacent-compound gap is one of the few quantities that *is*
# reasonably well known independent of any single race, from tyre-manufacturer
# and historical data: consecutive dry compounds are roughly a few tenths of a
# second apart in clean-air single-lap pace. Used as an upper bound on how
# large the enforced gap between adjacent compounds may be — it does not
# inject a specific value; the isotonic projection below still uses this
# race's own fitted offsets as the target, just constrained to be monotonic.
MAX_ADJACENT_COMPOUND_GAP_S = 1.2

# Isotonic regression guarantees *ordering*, not *separation* — pool adjacent
# violators can and does project two compounds onto the same value when a
# driver's raw offsets were badly backwards (verified across the full
# catalogue: a large fraction of adjacent-compound gaps came out at exactly
# 0.000s post-correction, e.g. 14/20 drivers on 2021 Spain's SOFT-MEDIUM
# pair). Two compounds sharing an offset means the simulator treats them as
# interchangeable — no reason to ever choose one over the other — which
# breaks strategy modelling from a third direction, on top of the confound
# this whole correction exists to fix. Enforced as a floor on top of the
# isotonic projection: a conservative "a compound is genuinely a little
# faster," well below the "few tenths" typically quoted, rather than a
# specific claimed value.
MIN_ADJACENT_COMPOUND_GAP_S = 0.15


def _enforce_monotonic_compound_offsets(
    driver_params: dict[str, DriverParams],
) -> tuple[dict[str, DriverParams], dict]:
    """Project each driver's fitted compound offsets onto the
    known-externally, not-fit-from-this-race constraint that softs are faster
    than mediums are faster than hards (spec 6.3's ordering sanity check,
    treated as a declared prior per Part 14 rule 1 rather than a free
    parameter — see module-level comment above).

    Weighted isotonic regression (weights = each compound's own
    `n_observations`) is the least-squares-optimal monotonic sequence given a
    driver's own noisy/confounded fitted offsets — it moves the offsets as
    little as possible while guaranteeing the correct order, rather than
    substituting an external number. A generous adjacent-gap cap is applied
    on top as a sanity backstop (rarely triggered; isotonic projection alone
    handles the overwhelming majority of cases).
    """
    from sklearn.isotonic import IsotonicRegression

    from pitwall.domain.enums import SLICK_ORDER

    corrected: dict[str, DriverParams] = {}
    diagnostics: dict = {"drivers_corrected": {}, "n_drivers_checked": 0, "n_drivers_corrected": 0}

    for driver, dp in driver_params.items():
        present = [c for c in SLICK_ORDER if c in dp.tyre_models]
        if len(present) < 2:
            corrected[driver] = dp
            continue

        diagnostics["n_drivers_checked"] += 1
        ranks = np.array([SLICK_ORDER.index(c) for c in present], dtype=float)
        raw_offsets = np.array([dp.tyre_models[c].base_offset_s for c in present])
        weights = np.array([max(dp.tyre_models[c].n_observations, 1) for c in present])

        iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
        projected = iso.fit_transform(ranks, raw_offsets, sample_weight=weights)

        # Backstop: enforce a minimum *and* maximum adjacent gap. Isotonic
        # regression alone only guarantees non-decreasing order — it will
        # happily project two compounds onto the same value (or near it) when
        # the driver's raw offsets were badly backwards, which makes them
        # interchangeable in the simulator. Applied forward so each gap is
        # checked against the (possibly just-raised) previous value.
        for i in range(1, len(projected)):
            gap = projected[i] - projected[i - 1]
            if gap < MIN_ADJACENT_COMPOUND_GAP_S:
                projected[i] = projected[i - 1] + MIN_ADJACENT_COMPOUND_GAP_S
            elif gap > MAX_ADJACENT_COMPOUND_GAP_S:
                projected[i] = projected[i - 1] + MAX_ADJACENT_COMPOUND_GAP_S

        if not np.allclose(projected, raw_offsets, atol=1e-9):
            diagnostics["n_drivers_corrected"] += 1
            diagnostics["drivers_corrected"][driver] = {
                present[i].value: {"raw": float(raw_offsets[i]), "corrected": float(projected[i])}
                for i in range(len(present))
            }

        new_tyre_models = dict(dp.tyre_models)
        for i, compound in enumerate(present):
            model = new_tyre_models[compound]
            new_tyre_models[compound] = TyreModel(
                compound=model.compound,
                base_offset_s=float(projected[i]),
                linear_deg_s_per_lap=model.linear_deg_s_per_lap,
                cliff_lap=model.cliff_lap,
                cliff_deg_s_per_lap=model.cliff_deg_s_per_lap,
                r_squared=model.r_squared,
                n_observations=model.n_observations,
            )

        corrected[driver] = DriverParams(
            driver=dp.driver,
            base_pace_s=dp.base_pace_s,
            pace_std_s=dp.pace_std_s,
            tyre_models=new_tyre_models,
            overtake_skill=dp.overtake_skill,
            defence_skill=dp.defence_skill,
        )

    return corrected, diagnostics


def _check_compound_ordering(driver_params: dict[str, DriverParams]) -> dict:
    """Post-correction verification: after
    `_enforce_monotonic_compound_offsets`, softs should be faster than
    mediums faster than hards for every driver. Computed as a
    reference-independent per-driver difference (offset[fast] - offset[slow],
    which cancels whichever compound that driver's own regression happened to
    anchor at 0) and checked in aggregate. This should now report zero
    violations — if it doesn't, the monotonic projection has a bug, not the
    underlying fit (which is expected to be noisy/backwards pre-correction)."""
    pairs = [
        (Compound.SOFT, Compound.MEDIUM),
        (Compound.MEDIUM, Compound.HARD),
        (Compound.SOFT, Compound.HARD),
    ]
    result: dict = {}
    for fast, slow in pairs:
        diffs = [
            dp.tyre_models[fast].base_offset_s - dp.tyre_models[slow].base_offset_s
            for dp in driver_params.values()
            if fast in dp.tyre_models and slow in dp.tyre_models
        ]
        if not diffs:
            continue
        mean_diff = float(np.mean(diffs))
        result[f"{fast.value}_vs_{slow.value}_mean_offset_diff_s"] = mean_diff
        if mean_diff > 1e-9:
            msg = (
                f"COMPOUND ORDERING STILL VIOLATED AFTER CORRECTION: {fast.value} averages "
                f"{mean_diff:.3f}s slower than {slow.value} across {len(diffs)} drivers — this "
                f"indicates a bug in the monotonic projection, not the underlying fit."
            )
            logger.error(msg)
            result.setdefault("violations", []).append(msg)
    return result


def fit_race_parameters(
    snapshot: RaceSnapshot,
    *,
    dirty_air_override: DirtyAirModel | None = None,
    base_pace_correction_s: float = 0.0,
) -> RaceParameters:
    """`dirty_air_override` and `base_pace_correction_s` exist for
    `fit_catalogue_with_pooled_dirty_air`'s second pass (see that function's
    docstring for why per-race dirty-air fitting doesn't have enough power
    and needs pooling across the catalogue). Callers fitting a single race
    on its own — the default — get identical behaviour to before these
    parameters existed: dirty air fit (and rejected) per-race as always, no
    base-pace correction applied.

    `base_pace_correction_s` is a uniform additive shift applied to every
    driver's `base_pace_s` *before* pit loss is fit, so pit loss (itself
    `expected_clean_pace_s`-relative) is computed against the corrected
    baseline rather than inheriting the old bias — see DECISIONS.md for why
    this correction exists and why it must land before, not after, pit loss.
    """
    diagnostics: dict = {"per_driver_fallbacks": {}, "warnings": []}

    drivers_with_laps = sorted({lap.driver for lap in snapshot.laps})
    laps_frames = {d: _laps_frame(snapshot, d) for d in drivers_with_laps}

    # Pass 1: per-driver joint fit, for drivers with enough laps to attempt it.
    joint_fits: dict[str, tyre.DriverJointFit] = {}
    insufficient_data_drivers: list[str] = []
    for driver, frame in laps_frames.items():
        usable = frame[frame["IsUsableForFitting"]] if len(frame) else frame
        if len(usable) < MIN_LAPS_FOR_OWN_FIT:
            insufficient_data_drivers.append(driver)
            continue
        joint_fits[driver] = tyre.fit_driver_joint(frame)

    diagnostics["drivers_with_own_fit"] = list(joint_fits)
    diagnostics["drivers_needing_teammate_fallback"] = insufficient_data_drivers
    for driver in insufficient_data_drivers:
        diagnostics["per_driver_fallbacks"][driver] = (
            f"Only {len(laps_frames[driver])} usable laps (<{MIN_LAPS_FOR_OWN_FIT}); "
            f"cannot fit independently (spec 6.2) — using teammate fallback below."
        )

    # Race-level fuel effect. Primary: pool every driver into one regression
    # (far more identifying variation than any single driver's own stints —
    # see fuel.py). Fall back to the per-driver median only if the pooled fit
    # itself is rejected as ill-conditioned or implausible.
    fuel_effect_s_per_lap, pooled_fuel_diagnostics = fuel.fit_pooled_fuel_effect(laps_frames)
    if fuel_effect_s_per_lap is None:
        fuel_effect_s_per_lap, fallback_fuel_diagnostics = fuel.aggregate_fuel_effect(joint_fits)
        diagnostics["fuel"] = {
            "method": "per_driver_median_fallback",
            "pooled_attempt": pooled_fuel_diagnostics,
            **fallback_fuel_diagnostics,
        }
    else:
        diagnostics["fuel"] = {"method": "pooled_regression", **pooled_fuel_diagnostics}

    # Cross-driver pooled compound fits, for sparse (driver, compound) fallback.
    #
    # Built from a PRELIMINARY pass 2 (fuel effect fixed, no pool available) rather
    # than from pass 1's joint fits. The pass-1 version had a hole that put an
    # impossible number into the product -- it gated on `is_identified`, true for
    # only 2 of 20 drivers at Hungary, so SOFT never entered the pool and VER's
    # SOFT cell fell all the way through to a degradation rate of exactly zero.
    # See `tyre.pool_compound_fits_from_cells` for the full account.
    #
    # The extra pass is one lstsq per driver and buys correctly-signed,
    # correctly-ordered pooled slopes from every driver who ran the compound,
    # instead of from the handful who happened to revisit one.
    preliminary_cells: dict[Compound, list[tyre.CompoundFit]] = {}
    for driver, frame in laps_frames.items():
        if driver in insufficient_data_drivers:
            continue
        try:
            _, _, prelim_models, _, prelim_provenance = tyre.fit_driver_final(
                frame, fuel_effect_s_per_lap, {}
            )
        except Exception:  # noqa: BLE001 - a driver we can't prefit simply doesn't contribute
            continue
        for compound, cell in prelim_provenance.items():
            if cell.provenance != "own_fit":
                continue
            slope = cell.final_slope
            if not (0 <= slope <= tyre.MAX_PLAUSIBLE_SLOPE_S_PER_LAP):
                continue
            preliminary_cells.setdefault(compound, []).append(
                tyre.CompoundFit(
                    offset=prelim_models[compound].base_offset_s,
                    slope=slope,
                    n_observations=prelim_models[compound].n_observations,
                )
            )
    pooled_compounds = tyre.pool_compound_fits_from_cells(preliminary_cells)
    diagnostics["tyre_pool_source"] = {
        "method": "fuel_fixed_preliminary_pass2",
        "cells_by_compound": {c.value: len(v) for c, v in sorted(preliminary_cells.items(), key=lambda kv: kv[0].value)},
        "pooled_slope_s_per_lap": {c.value: round(f.slope, 5) for c, f in sorted(pooled_compounds.items(), key=lambda kv: kv[0].value)},
    }

    # Pass 2: finalize base pace + tyre models with the race-level fuel effect fixed.
    driver_params: dict[str, DriverParams] = {}
    tyre_notes: dict[str, tuple[str, ...]] = {}
    cell_provenance_by_driver: dict[str, dict] = {}
    for driver, frame in laps_frames.items():
        if driver in insufficient_data_drivers:
            continue
        base_pace_s, pace_std_s, tyre_models, notes, cell_provenance = tyre.fit_driver_final(
            frame, fuel_effect_s_per_lap, pooled_compounds
        )
        driver_params[driver] = pace.build_driver_params(
            driver, base_pace_s, pace_std_s, tyre_models
        )
        if notes:
            tyre_notes[driver] = notes
        cell_provenance_by_driver[driver] = {
            compound.value: {
                "provenance": cp.provenance,
                "raw_own_slope": cp.raw_own_slope,
                "final_slope": cp.final_slope,
            }
            for compound, cp in cell_provenance.items()
        }
    diagnostics["tyre_fallback_notes"] = tyre_notes

    # Per-cell fit provenance summary (spec 8.4: fit quality/fallbacks must be
    # surfaced, never hidden): what fraction of driver/compound cells actually
    # came from that driver's own regression vs a fallback tier. A race where
    # most cells need a fallback isn't well-fit no matter how plausible the
    # final (post-fallback) numbers look — this is what
    # `test_tyre_degradation_rates_are_positive` checks a ceiling against,
    # rather than only checking the post-fallback values are positive (which
    # is true by construction once the fallback chain exists).
    all_cells = [cp for driver_cells in cell_provenance_by_driver.values() for cp in driver_cells.values()]
    n_total_cells = len(all_cells)
    n_own_fit = sum(1 for cp in all_cells if cp["provenance"] == "own_fit")
    diagnostics["tyre_cell_provenance"] = {
        "by_driver": cell_provenance_by_driver,
        "n_total_cells": n_total_cells,
        "n_own_fit": n_own_fit,
        "n_fallback": n_total_cells - n_own_fit,
        "fallback_fraction": (n_total_cells - n_own_fit) / n_total_cells if n_total_cells else 0.0,
    }

    # Teammate fallback for drivers with too few laps to fit at all (spec 6.2).
    team_by_driver = {d.code: d.team for d in snapshot.drivers}
    for driver in insufficient_data_drivers:
        team = team_by_driver.get(driver)
        teammate = next(
            (
                code
                for code, t in team_by_driver.items()
                if t == team and code != driver and code in driver_params
            ),
            None,
        )
        if teammate is not None:
            source = driver_params[teammate]
            driver_params[driver] = DriverParams(
                driver=driver,
                base_pace_s=source.base_pace_s,
                pace_std_s=source.pace_std_s,
                tyre_models=source.tyre_models,
                overtake_skill=pace.NEUTRAL_OVERTAKE_SKILL,
                defence_skill=pace.NEUTRAL_DEFENCE_SKILL,
            )
            diagnostics["per_driver_fallbacks"][driver] += f" Copied teammate {teammate}'s fit."
        else:
            # No teammate has a usable fit either (e.g. both cars of a team retired
            # early) — fall back to the field median base pace, clearly the least
            # reliable case, logged loudly rather than silently defaulting to 0.
            if driver_params:
                field_median_pace = float(np.median([p.base_pace_s for p in driver_params.values()]))
                field_median_std = float(np.median([p.pace_std_s for p in driver_params.values()]))
            else:
                field_median_pace, field_median_std = 90.0, 0.3
            driver_params[driver] = DriverParams(
                driver=driver,
                base_pace_s=field_median_pace,
                pace_std_s=field_median_std,
                tyre_models={},
                overtake_skill=pace.NEUTRAL_OVERTAKE_SKILL,
                defence_skill=pace.NEUTRAL_DEFENCE_SKILL,
            )
            diagnostics["per_driver_fallbacks"][driver] += (
                " No teammate fit available either; used field-median base pace "
                "(least reliable fallback tier)."
            )
            diagnostics["warnings"].append(
                f"{driver}: no own data and no teammate fit — field-median fallback used."
            )

    driver_params, monotonic_diagnostics = _enforce_monotonic_compound_offsets(driver_params)
    diagnostics["compound_ordering_prior"] = monotonic_diagnostics
    diagnostics["compound_ordering_check"] = _check_compound_ordering(driver_params)

    if base_pace_correction_s != 0.0:
        # See DECISIONS.md: expected_clean_pace_s's own fitted intercept
        # absorbs the field's mean traffic exposure (most laps used to fit
        # it had some car ahead), so base_pace_s is biased slow field-wide
        # by roughly the asymptote of the gap-vs-residual curve. Applied
        # uniformly (not per-driver) since the pooled fit that produced this
        # correction has no per-driver resolution to offer.
        driver_params = {
            d: DriverParams(
                driver=dp.driver,
                base_pace_s=dp.base_pace_s + base_pace_correction_s,
                pace_std_s=dp.pace_std_s,
                tyre_models=dp.tyre_models,
                overtake_skill=dp.overtake_skill,
                defence_skill=dp.defence_skill,
            )
            for d, dp in driver_params.items()
        }
        diagnostics["base_pace_correction_s"] = base_pace_correction_s

    pit_lane_loss_s, pit_stop_stationary_s, pit_diagnostics = pit_loss.fit_pit_loss(
        snapshot, driver_params, fuel_effect_s_per_lap, dirty_air_model=dirty_air_override
    )
    diagnostics["pit_loss"] = pit_diagnostics

    if dirty_air_override is not None:
        dirty_air_model = dirty_air_override
        diagnostics["dirty_air"] = {"pooled_override": True, "n_observations": dirty_air_override.n_observations}
    else:
        dirty_air_model, dirty_air_diagnostics = dirty_air.fit_dirty_air(
            snapshot, driver_params, fuel_effect_s_per_lap
        )
        diagnostics["dirty_air"] = dirty_air_diagnostics

    overtake_difficulty, overtake_diagnostics = overtaking.fit_overtake_difficulty(snapshot)
    diagnostics["overtaking"] = overtake_diagnostics

    sc_mult, vsc_mult, sc_vsc_diagnostics = _sc_vsc_multipliers(
        snapshot, driver_params, fuel_effect_s_per_lap
    )
    diagnostics["sc_vsc"] = sc_vsc_diagnostics

    return RaceParameters(
        race_key=snapshot.race_key,
        drivers=driver_params,
        fuel_effect_s_per_lap=fuel_effect_s_per_lap,
        pit_lane_loss_s=pit_lane_loss_s,
        pit_stop_stationary_s=pit_stop_stationary_s,
        dirty_air=dirty_air_model,
        overtake_difficulty=overtake_difficulty,
        sc_lap_time_multiplier=sc_mult,
        vsc_lap_time_multiplier=vsc_mult,
        fitted_at=datetime.now(timezone.utc),
        fit_diagnostics=diagnostics,
    )


def driver_params_digest(params: RaceParameters) -> str:
    """A short stable digest of every per-driver fitted quantity.

    The generated fixtures carry a `paramFingerprint` so that a refit fails a
    test instead of quietly leaving stale numbers in the UI (Rule 3). That
    fingerprint listed the pit-lane loss, overtake difficulty, dirty-air pair,
    the following-gap floor and the AR(1) phi — and **not the tyre models**. So
    when the degradation fallback chain was corrected, every fixture in the
    catalogue became stale and no fingerprint test could have noticed: the change
    that mattered most was the one the guard did not cover.

    Covers the compound offsets, degradation slopes and cliffs — and also
    `base_pace_s` and `pace_std_s`, which live on `DriverParams` rather than on
    `TyreModel` and were missed by the first version of this digest. Both move
    whenever the degradation fit moves, since all three come out of the same
    pass-2 regression, so a digest over the tyre models alone could still have
    let a driver's base pace drift silently. `pace_std_s` matters twice over: it
    is the scale of the ensemble's pace noise, so it sets the width of every
    band the UI draws.

    Hashed rather than enumerated because there are ~40 cells per race and the
    fingerprint is stored on all 103 files. Rounded before hashing so
    floating-point noise below the level anyone would act on doesn't produce
    spurious staleness.
    """
    import hashlib

    parts: list[str] = []
    for driver in sorted(params.drivers):
        dp = params.drivers[driver]
        parts.append(f"{driver}|pace|{dp.base_pace_s:.5f}|{dp.pace_std_s:.5f}")
        for compound in sorted(dp.tyre_models, key=lambda c: c.value):
            m = dp.tyre_models[compound]
            parts.append(
                f"{driver}|{compound.value}|{m.base_offset_s:.5f}|{m.linear_deg_s_per_lap:.6f}|"
                f"{m.cliff_lap}|{'' if m.cliff_deg_s_per_lap is None else f'{m.cliff_deg_s_per_lap:.6f}'}"
            )
    return hashlib.sha256(";".join(parts).encode("utf-8")).hexdigest()[:16]


def fit_catalogue_with_pooled_dirty_air(snapshots: list[RaceSnapshot]) -> dict[str, RaceParameters]:
    """Two-pass fit across the whole catalogue (spec 6.6's own admission that
    dirty air isn't identifiable from one race's data, extended to the curve
    itself — see `dirty_air.fit_pooled_dirty_air_across_races`'s docstring
    for the full mechanism and derivation).

    Pass 1: fit every race independently exactly as `fit_race_parameters`
    always has (per-race dirty air fit and rejected, as before). Pass 2:
    pool dirty-air residuals across all of pass 1's results, then refit
    every race with the pooled `DirtyAirModel` and base-pace correction
    applied. Takes already-loaded snapshots (not a catalogue of entries to
    load) to keep `parameters/` free of `ingestion/` imports (spec 2.2) —
    callers (scripts) load the snapshots first.
    """
    first_pass = {snapshot.race_key: fit_race_parameters(snapshot) for snapshot in snapshots}

    pooled_model, base_pace_correction_s, pooled_diagnostics = dirty_air.fit_pooled_dirty_air_across_races(
        [
            (snapshot, first_pass[snapshot.race_key].drivers, first_pass[snapshot.race_key].fuel_effect_s_per_lap)
            for snapshot in snapshots
        ]
    )

    second_pass: dict[str, RaceParameters] = {}
    for snapshot in snapshots:
        params = fit_race_parameters(
            snapshot,
            dirty_air_override=pooled_model,
            base_pace_correction_s=base_pace_correction_s,
        )
        params.fit_diagnostics["pooled_dirty_air_fit"] = pooled_diagnostics
        second_pass[snapshot.race_key] = params

    return second_pass


# --------------------------------------------------------------------------
# Persistence (data/fitted/, committed — spec Part 3)
# --------------------------------------------------------------------------


def _tyre_model_to_dict(model: TyreModel) -> dict:
    d = asdict(model)
    d["compound"] = model.compound.value
    return d


def _tyre_model_from_dict(d: dict) -> TyreModel:
    d = dict(d)
    d["compound"] = Compound(d["compound"])
    return TyreModel(**d)


def _driver_params_to_dict(params: DriverParams) -> dict:
    return {
        "driver": params.driver,
        "base_pace_s": params.base_pace_s,
        "pace_std_s": params.pace_std_s,
        "tyre_models": {c.value: _tyre_model_to_dict(m) for c, m in params.tyre_models.items()},
        "overtake_skill": params.overtake_skill,
        "defence_skill": params.defence_skill,
    }


def _driver_params_from_dict(d: dict) -> DriverParams:
    return DriverParams(
        driver=d["driver"],
        base_pace_s=d["base_pace_s"],
        pace_std_s=d["pace_std_s"],
        tyre_models={
            Compound(c): _tyre_model_from_dict(m) for c, m in d["tyre_models"].items()
        },
        overtake_skill=d["overtake_skill"],
        defence_skill=d["defence_skill"],
    )


def to_json_dict(params: RaceParameters) -> dict:
    return {
        "race_key": params.race_key,
        "drivers": {code: _driver_params_to_dict(p) for code, p in params.drivers.items()},
        "fuel_effect_s_per_lap": params.fuel_effect_s_per_lap,
        "pit_lane_loss_s": params.pit_lane_loss_s,
        "pit_stop_stationary_s": params.pit_stop_stationary_s,
        "dirty_air": asdict(params.dirty_air),
        "overtake_difficulty": params.overtake_difficulty,
        "sc_lap_time_multiplier": params.sc_lap_time_multiplier,
        "vsc_lap_time_multiplier": params.vsc_lap_time_multiplier,
        "fitted_at": params.fitted_at.isoformat(),
        "fit_diagnostics": params.fit_diagnostics,
    }


def from_json_dict(d: dict) -> RaceParameters:
    return RaceParameters(
        race_key=d["race_key"],
        drivers={code: _driver_params_from_dict(p) for code, p in d["drivers"].items()},
        fuel_effect_s_per_lap=d["fuel_effect_s_per_lap"],
        pit_lane_loss_s=d["pit_lane_loss_s"],
        pit_stop_stationary_s=d["pit_stop_stationary_s"],
        dirty_air=DirtyAirModel(**d["dirty_air"]),
        overtake_difficulty=d["overtake_difficulty"],
        sc_lap_time_multiplier=d["sc_lap_time_multiplier"],
        vsc_lap_time_multiplier=d["vsc_lap_time_multiplier"],
        fitted_at=datetime.fromisoformat(d["fitted_at"]),
        fit_diagnostics=d["fit_diagnostics"],
    )


def save_race_parameters(params: RaceParameters, directory: Path | None = None) -> Path:
    directory = Path(directory) if directory is not None else DEFAULT_FITTED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{params.race_key}.json"
    path.write_text(json.dumps(to_json_dict(params), indent=2), encoding="utf-8")
    return path


def load_race_parameters(race_key: str, directory: Path | None = None) -> RaceParameters:
    directory = Path(directory) if directory is not None else DEFAULT_FITTED_DIR
    path = directory / f"{race_key}.json"
    return from_json_dict(json.loads(path.read_text(encoding="utf-8")))
