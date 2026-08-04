"""Determinism (spec 6.10): all randomness flows through one seeded
`numpy.random.Generator`, passed explicitly down the call chain. No module-level
`random`/`np.random` calls anywhere in `simulation/` — grep for `np.random.`
outside this file if that's ever in doubt.
"""

from __future__ import annotations

import numpy as np


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)
