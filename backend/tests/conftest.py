"""Shared pytest fixtures.

`pythonpath = ["backend"]` in pyproject.toml puts `pitwall` on the import path,
so tests import it directly (e.g. `from pitwall.domain import ...`).
"""

import numpy as np
import pytest


@pytest.fixture
def rng() -> np.random.Generator:
    """A seeded generator. Determinism is mandatory (spec 6.10) — every test that
    touches randomness must draw from an explicitly seeded generator, never the
    module-level numpy global."""
    return np.random.default_rng(20211212)
