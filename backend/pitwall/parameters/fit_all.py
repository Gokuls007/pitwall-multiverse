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


def _check_compound_ordering(driver_params: dict[str, DriverParams]) -> dict:
    """Sanity check (spec 6.3): softs should be faster than mediums faster
    than hards. Computed as a reference-independent per-driver difference
    (offset[fast] - offset[slow], which cancels whichever compound that
    driver's own regression happened to anchor at 0) so it's meaningful to
    average across drivers, then checked in aggregate — not per driver, since
    individual per-driver offsets are noisy enough (one ~15-25 lap stint) that
    many individual differences flip sign even when the model is unbiased.

    KNOWN LIMITATION (see DECISIONS.md): this aggregate check itself is
    frequently violated on real data, traced to a specific, understood cause:
    real track evolution is front-loaded (rapid early grip gain, then a
    plateau) while spec 6.1's `fuel_effect` is a single linear-in-lap-number
    coefficient. Since compound choice correlates with stint order (whichever
    compound is used *latest* benefits from track evolution the linear term
    under-corrects for), that compound systematically looks faster than it
    truly is. This is disclosed here rather than hidden; Phase 3's validation
    harness is where it gets properly stress-tested against real outcomes.
    """
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
        if mean_diff > 0:
            msg = (
                f"COMPOUND ORDERING VIOLATION: {fast.value} averages {mean_diff:.3f}s SLOWER "
                f"than {slow.value} across {len(diffs)} drivers (expected negative — {fast.value} "
                f"should be faster). Likely track-evolution/stint-order conflation with the "
                f"linear fuel_effect term — see DECISIONS.md. Not corrected; disclosed for Phase 3."
            )
            logger.warning(msg)
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
    for driver, frame in laps_frames.items():
        if driver in insufficient_data_drivers:
            continue
        base_pace_s, pace_std_s, tyre_models, notes = tyre.fit_driver_final(
            frame, fuel_effect_s_per_lap, pooled_compounds
        )
        driver_params[driver] = pace.build_driver_params(
            driver, base_pace_s, pace_std_s, tyre_models
        )
        if notes:
            tyre_notes[driver] = notes
    diagnostics["tyre_fallback_notes"] = tyre_notes

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
