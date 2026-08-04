"""Pit stop execution (spec 6.5). The deterministic pit-lane time cost
itself lives in `lap_time.pit_lane_time_s` (it's one term of the lap-time
composition); this module adds the stochastic part spec 6.5 asks for: "a
small probability of a slow stop, fitted from the spread of observed
stationary times."

Not fitted from a full distribution — only the median (`pit_lane_loss_s`)
and a same-race standard deviation are available from
`parameters/pit_loss.py`'s diagnostics, not per-stop data threaded through to
`RaceParameters`. `SLOW_STOP_PROBABILITY`/`SLOW_STOP_EXTRA_S` are declared,
bounded priors (Part 14 rule 1), not fitted values.
"""

from __future__ import annotations

import numpy as np

PIT_NOISE_STD_S = 0.5
SLOW_STOP_PROBABILITY = 0.05
SLOW_STOP_EXTRA_S = 3.0


def pit_stop_noise_s(rng: np.random.Generator) -> float:
    """Lap-to-lap variability in a pit stop, on top of the deterministic
    median cost — ordinary noise most of the time, occasionally a slow stop.
    """
    noise = float(rng.normal(0.0, PIT_NOISE_STD_S))
    if rng.random() < SLOW_STOP_PROBABILITY:
        noise += SLOW_STOP_EXTRA_S
    return noise
