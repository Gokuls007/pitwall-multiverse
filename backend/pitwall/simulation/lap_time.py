"""Lap time composition (spec 6.1). Each term is a separate, individually
testable pure function — "when validation shows the simulator is off, you
need to be able to isolate which term is wrong" (spec 6.1).

`simulation/` is pure: it takes domain objects (`DriverParams`,
`RaceParameters`, `Compound`, ...) and numbers, and returns numbers. No
FastF1, no I/O, nothing from `ingestion/` or `parameters/`'s fitting code —
only the *data* those layers produce (spec 2.2's architectural principle).

Deviations from a literal reading of the spec, recorded here and in
DECISIONS.md:
  - `sc_vsc_effect` is applied *multiplicatively* (lap_time * multiplier),
    not additively, because that's how `sc_lap_time_multiplier` /
    `vsc_lap_time_multiplier` were fitted (spec 6.8: "fit the multiplier"
    against the ratio of actual to expected pace) — SC/VSC pace is
    proportional to normal pace (speed-limit-driven), not a fixed additive
    penalty.
  - Dirty air (spec 6.6) and traffic (spec 6.9) share one curve
    (`DirtyAirModel.penalty_s`) rather than a separately-fitted traffic
    term — there is no separate traffic model in this project. This term
    was removed from the composition for one round of this project's
    history (per-race dirty-air fitting was always rejected — insufficient
    power from a single race's data — and the resulting undeclared prior
    measured as the largest systematic contributor to green-flag error) and
    superseded by `position.py`'s stuck-behind clamp and blue-flag rule.
    Restored once a *pooled cross-race* fit (`dirty_air.
    fit_pooled_dirty_air_across_races`) found real signal that per-race
    fitting couldn't: `expected_clean_pace_s`'s own fitted intercept
    absorbs the field's mean traffic exposure (most fitting-sample laps had
    a car somewhere ahead), so it's average-traffic pace, not zero-traffic
    pace, and every per-race attempt was fitting an exponential decaying to
    *zero* onto residuals whose true large-gap asymptote is around -0.47s —
    no parameter choice can do that. The clamp/blue-flag rule (an edge
    condition: physically cannot get closer than a minimum following
    distance) and this curve (the interior: a smooth penalty across the
    range of gaps) are the two halves of the same phenomenon, not
    competing models of it — see DECISIONS.md for the full derivation and
    the two rejected alternatives (deleting dirty air; a shadow lap-time
    value) that came before this.
"""

from __future__ import annotations

import numpy as np

from pitwall.domain.driver import DriverParams
from pitwall.domain.enums import Compound
from pitwall.domain.race import DirtyAirModel


def base_pace_s(driver_params: DriverParams) -> float:
    return driver_params.base_pace_s


def tyre_degradation_s(driver_params: DriverParams, compound: Compound, tyre_age: int) -> float:
    tyre_model = driver_params.tyre_models.get(compound)
    if tyre_model is None:
        raise ValueError(f"{driver_params.driver} has no fitted TyreModel for {compound}")
    return tyre_model.degradation_s(tyre_age)


def compound_offset_s(driver_params: DriverParams, compound: Compound) -> float:
    tyre_model = driver_params.tyre_models.get(compound)
    if tyre_model is None:
        raise ValueError(f"{driver_params.driver} has no fitted TyreModel for {compound}")
    return tyre_model.base_offset_s


def fuel_effect_s(fuel_effect_s_per_lap: float, lap_number: int) -> float:
    """Negative: fuel burns off as the race progresses, so later laps are
    faster. `base_pace_s` is fitted as the (extrapolated) lap-0, full-fuel
    baseline (see tyre.py's joint regression), so this term must use the
    same `lap_number` convention the fit used — not `laps_remaining`."""
    return -fuel_effect_s_per_lap * lap_number


def dirty_air_and_traffic_penalty_s(
    dirty_air_model: DirtyAirModel, gap_to_ahead_s: float | None
) -> float:
    """Spec 6.6 (dirty air) and 6.9 (traffic) share one curve here — see
    module docstring for why."""
    return dirty_air_model.penalty_s(gap_to_ahead_s)


def sc_vsc_multiplier(
    is_under_sc: bool,
    is_under_vsc: bool,
    sc_lap_time_multiplier: float,
    vsc_lap_time_multiplier: float,
) -> float:
    if is_under_sc:
        return sc_lap_time_multiplier
    if is_under_vsc:
        return vsc_lap_time_multiplier
    return 1.0


def pit_lane_time_s(
    pit_lane_loss_s: float,
    is_in_lap: bool,
    is_out_lap: bool,
    sc_vsc_active_multiplier: float = 1.0,
) -> float:
    """Total measured pit loss (spec 6.5) is split evenly between the in-lap
    and out-lap — matching how it was *measured* (excess on each of the two
    laps, summed). Spec 6.8 point 3: pit stops are much cheaper under SC/VSC
    because the whole field is running the same reduced pace, so the loss is
    scaled by the active multiplier, not held at the green-flag value.
    """
    if not (is_in_lap or is_out_lap):
        return 0.0
    return (pit_lane_loss_s / 2.0) * sc_vsc_active_multiplier


def noise_s(rng: np.random.Generator, pace_std_s: float) -> float:
    if pace_std_s <= 0:
        return 0.0
    return float(rng.normal(0.0, pace_std_s))


# Fitted, not a declared prior — an earlier version of this comment called
# it undeclarable and picked 0.5 by feel, which was exactly the Rule 1
# violation this project has spent several passes stamping out elsewhere.
# It's directly measurable: the lag-1 autocorrelation of open-loop
# green-flag residuals (real lap time minus the deterministic clean-air
# prediction) between consecutive laps *within the same stint* (a stint
# boundary resets tyre/compound state, so residuals either side of one
# aren't the same persistence process). Pooled across all 5 catalogue
# races, 5,373 consecutive-lap pairs: phi = 0.622. See
# `scripts/fit_noise_autocorrelation.py` for the exact computation.
#
# This also means an earlier claim in this codebase was backwards: positive
# autocorrelation *increases* cumulative variance relative to iid, it
# doesn't dampen it. For a stationary AR(1) process summed over n laps,
# Var(sum) ~= n * sigma^2 * (1+phi)/(1-phi) for large n — at phi=0.622 that
# factor is ~4.3, i.e. ~2.1x the iid standard deviation over the same
# number of laps, not less. The correction is still the right one (real
# lap-time scatter is measurably persistent, and modelling it as iid is
# simply wrong), but it was adopted for the wrong stated reason — see
# DECISIONS.md for the retraction and what it changes about how the
# counterfactual ensemble's drift should be read.
AR1_PHI = 0.622


def ar1_noise_s(rng: np.random.Generator, pace_std_s: float, prev_noise_s: float, phi: float = AR1_PHI) -> float:
    """Autocorrelated pace noise: `new = phi * prev + innovation`, with the
    innovation's own standard deviation scaled so the *stationary* variance
    still equals `pace_std_s` — i.e. at any single lap in isolation this
    has the same spread as `noise_s`'s iid draw, but consecutive laps are
    correlated (see `AR1_PHI`'s comment for why that increases, not
    decreases, cumulative spread over many laps relative to iid — this is
    matching a real, measured property of lap-time scatter, not adopting
    it to shrink drift). Used by `counterfactual/engine.py` for ensemble
    stochasticity, not by `simulation/engine.py`'s replay (Phase 3
    validation runs noise off entirely — see `compose_lap_time_s`'s
    docstring — so this never engages there regardless).
    """
    if pace_std_s <= 0:
        return 0.0
    innovation_std = pace_std_s * (1.0 - phi**2) ** 0.5
    return phi * prev_noise_s + float(rng.normal(0.0, innovation_std))


def compose_lap_time_s(
    *,
    driver_params: DriverParams,
    compound: Compound,
    tyre_age: int,
    lap_number: int,
    fuel_effect_s_per_lap: float,
    dirty_air_model: DirtyAirModel,
    gap_to_ahead_s: float | None,
    is_under_sc: bool,
    is_under_vsc: bool,
    sc_lap_time_multiplier: float,
    vsc_lap_time_multiplier: float,
    pit_lane_loss_s: float,
    is_in_lap: bool,
    is_out_lap: bool,
    rng: np.random.Generator,
    include_noise: bool = True,
) -> float:
    """Spec 6.1's full composition, assembled from the individual terms
    above. This is the only function `simulation/engine.py` calls directly;
    everything else here exists to be unit-tested in isolation.

    `include_noise=False` returns the deterministic pace *prediction* with
    no sampled residual — this is what spec 8.3's lap-time-accuracy
    threshold is actually asking about. Mean-zero noise sampled into a value
    that is then compared against reality can only inflate the reported MAE
    (E[|noise|] = pace_std_s * sqrt(2/pi) ≈ 0.8 * pace_std_s, added on top
    regardless of how good the underlying prediction is) — it never
    improves it, so scoring the noisy realisation measures something other
    than what 8.3 asks for. See DECISIONS.md: an earlier version of the
    validation harness did exactly this and reported an inflated MAE as if
    it were pace-model error.
    """
    racing_pace = (
        base_pace_s(driver_params)
        + tyre_degradation_s(driver_params, compound, tyre_age)
        + compound_offset_s(driver_params, compound)
        + fuel_effect_s(fuel_effect_s_per_lap, lap_number)
        + dirty_air_and_traffic_penalty_s(dirty_air_model, gap_to_ahead_s)
        + (noise_s(rng, driver_params.pace_std_s) if include_noise else 0.0)
    )
    multiplier = sc_vsc_multiplier(
        is_under_sc, is_under_vsc, sc_lap_time_multiplier, vsc_lap_time_multiplier
    )
    pit_time = pit_lane_time_s(pit_lane_loss_s, is_in_lap, is_out_lap, multiplier)
    return racing_pace * multiplier + pit_time
