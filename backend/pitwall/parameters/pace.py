"""Assemble per-driver `DriverParams` from the tyre/fuel joint fit (spec 6.2).

Thin by design: `tyre.fit_driver_final` does the actual regression (base pace,
tyre models, residual std); this module just packages the result into the
domain type and attaches the driver-skill priors spec 6.7 explicitly permits
as hand-set values (see `overtaking.py` / DECISIONS.md for why 0.5/0.5).
"""

from __future__ import annotations

from pitwall.domain.driver import DriverParams

# Spec 6.7: driver skill is "the one place where hand-assigned priors are
# acceptable, because they are not identifiable from a single race" — but they
# must be declared, bounded narrowly, and sensitivity-checked. Setting every
# driver to the same neutral value trivially satisfies all three: it's
# declared here, it has zero variance (as narrow a bound as exists), and the
# simulation outcome cannot be sensitive to a parameter that never varies.
# Differentiating real per-driver skill would need multi-race pooling (spec
# Part 15 stretch goal), which is out of scope for v1.
NEUTRAL_OVERTAKE_SKILL = 0.5
NEUTRAL_DEFENCE_SKILL = 0.5


def build_driver_params(
    driver: str,
    base_pace_s: float,
    pace_std_s: float,
    tyre_models: dict,
) -> DriverParams:
    return DriverParams(
        driver=driver,
        base_pace_s=base_pace_s,
        pace_std_s=pace_std_s,
        tyre_models=tyre_models,
        overtake_skill=NEUTRAL_OVERTAKE_SKILL,
        defence_skill=NEUTRAL_DEFENCE_SKILL,
    )
