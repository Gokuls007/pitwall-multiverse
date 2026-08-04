"""Phase 0 smoke tests: the package imports and the toolchain runs.

These are intentionally trivial. They exist so that `pytest` exits clean on a
fresh checkout (Phase 0 acceptance) and so CI has something to run before the
real simulation tests land in Phase 3.
"""

import importlib

import numpy as np

import pitwall


def test_package_version():
    assert pitwall.__version__ == "0.1.0"


def test_subpackages_importable():
    for name in [
        "pitwall.domain",
        "pitwall.ingestion",
        "pitwall.parameters",
        "pitwall.simulation",
        "pitwall.validation",
        "pitwall.counterfactual",
        "pitwall.api",
    ]:
        importlib.import_module(name)


def test_numpy_generator_is_deterministic(rng):
    """Same seed -> same draws. This is the smallest possible statement of the
    determinism guarantee the whole simulator depends on (spec 6.10)."""
    other = np.random.default_rng(20211212)
    assert (rng.random(5) == other.random(5)).all()
