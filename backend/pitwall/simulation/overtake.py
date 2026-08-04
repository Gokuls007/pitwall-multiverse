"""Overtake resolution (spec 6.7). Being faster does not mean passing — this
is the most stochastic part of the model.

`pass_probability` is a function of: pace delta (dominant term), circuit
`overtake_difficulty` (fitted, spec 6.7), and driver skill (uniform 0.5/0.5
prior in this project — see `parameters/pace.py` and DECISIONS.md; kept as
explicit parameters here rather than hardcoded so the function is correct
if skill differentiation is ever added, e.g. via Part 15's multi-race
pooling stretch goal). DRS availability (spec 6.7's fourth factor) is not
modelled: this project doesn't ingest lap-level DRS-detection-point data.
"""

from __future__ import annotations

import numpy as np

# Not from the spec — chosen so a ~1s/lap pace advantage gets most of the way
# to its saturating ease-of-pass ceiling, matching the intuition that a full
# second a lap is a large, clearly-passing advantage at most circuits.
PACE_SCALE_S = 1.0

# Even a much faster car on the easiest circuit doesn't pass with certainty
# on a single lap in reality — following, DRS detection, and the move itself
# take more than one lap more often than not. Caps the per-lap probability.
MAX_PASS_PROBABILITY = 0.5


def pass_probability(
    pace_delta_s: float,
    overtake_difficulty: float,
    attacker_skill: float = 0.5,
    defender_skill: float = 0.5,
) -> float:
    """Probability the follower completes a pass *this lap*.

    Monotonic increasing in `pace_delta_s` (follower's clean-air pace
    advantage), monotonic decreasing in `overtake_difficulty`. Zero or
    negative pace delta (follower not actually faster) gives zero probability
    — pace is the dominant term (spec 6.7) and this project doesn't model a
    faster defender occasionally losing position by mistake.
    """
    ease = max(0.0, min(1.0, 1.0 - overtake_difficulty))
    pace_factor = 1.0 - np.exp(-max(pace_delta_s, 0.0) / PACE_SCALE_S)
    skill_factor = max(0.0, min(1.0, 0.5 + 0.5 * (attacker_skill - defender_skill)))
    prob = ease * pace_factor * (2.0 * skill_factor) * MAX_PASS_PROBABILITY
    return float(max(0.0, min(MAX_PASS_PROBABILITY, prob)))


def resolve_pass(rng: np.random.Generator, probability: float) -> bool:
    return bool(rng.random() < probability)
