"""Replay a catalogue race exactly as it happened (spec Part 8.1): real
strategies, real safety cars, real retirements. `simulation/engine.py`
already only knows how to replay (Phase 3 doesn't have a counterfactual
engine yet), so this module is a thin ensemble wrapper — spec 6.10's "don't
trust a single stochastic run" applies to validation too, not just
counterfactuals in Phase 4.

`include_noise=False` by default: validation measures the deterministic
*pace prediction* against reality (spec 8.3's actual question), not a noisy
realisation of it. Mean-zero pace noise sampled into the compared value can
only inflate reported MAE, never reflect model accuracy — and accumulated
into cumulative time over a full race, iid per-lap noise is a random walk
(sigma * sqrt(n_laps), ~5s over 60 laps at a typical fitted pace_std_s) that
reshuffles the midfield on its own, independent of pace-model quality. The
ensemble is still meaningful with noise off: overtake resolution still draws
from `rng` as a genuinely modelled uncertain event, not a noise artifact.
See DECISIONS.md for the full diagnosis of what this replaced.
"""

from __future__ import annotations

from pitwall.domain.race import RaceParameters, RaceSnapshot
from pitwall.domain.result import SimulationResult
from pitwall.simulation.engine import simulate_replay

# Small ensemble, not the larger one Phase 4 counterfactuals will want —
# chosen to balance getting a representative (not one lucky/unlucky seed)
# picture of replay accuracy against keeping the Phase 3 validation run fast
# across 5 races. Revisit if metrics prove sensitive to this size.
DEFAULT_ENSEMBLE_SEEDS = tuple(range(10))


def replay_ensemble(
    snapshot: RaceSnapshot,
    race_params: RaceParameters,
    seeds: tuple[int, ...] = DEFAULT_ENSEMBLE_SEEDS,
    include_noise: bool = False,
) -> list[SimulationResult]:
    return [simulate_replay(snapshot, race_params, seed, include_noise=include_noise) for seed in seeds]
