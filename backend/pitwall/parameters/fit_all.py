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


def fit_race_parameters(snapshot: RaceSnapshot) -> RaceParameters:
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
    pooled_compounds = tyre.pool_compound_fits(joint_fits)

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

    pit_lane_loss_s, pit_stop_stationary_s, pit_diagnostics = pit_loss.fit_pit_loss(
        snapshot, driver_params, fuel_effect_s_per_lap
    )
    diagnostics["pit_loss"] = pit_diagnostics

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
