"""Determinism (spec 6.10): all randomness flows through one seeded
`numpy.random.Generator`, passed explicitly down the call chain. No module-level
`random`/`np.random` calls anywhere in `simulation/` — grep for `np.random.`
outside this file if that's ever in doubt.

**Common random numbers.** For a *paired* comparison — a counterfactual against
the override-free fork of the same race at the same lap with the same seed —
drawing sequentially from one stream is not enough. The moment the decision
changes a lap time, the two runs stop consuming the generator in step: one takes
a pit-noise draw the other doesn't, an overtake resolves differently, and from
there every subsequent draw in the two runs is a different number. The paired
difference then contains draw-order divergence on top of the decision's actual
effect, and the p10–p90 band reports the sum of the two as if it were
uncertainty about the decision.

`DrawTable` fixes that by making the draws a *function of position in the race*
rather than of call order. Every random quantity is indexed by
`(seed, driver, lap, channel)`, so any lap on which nothing differs between two
runs draws an identical number in both, and the band collapses to genuinely
decision-driven divergence. This is the standard variance-reduction technique for
paired simulation.

Implemented as pre-drawn arrays rather than by constructing a generator per
`(driver, lap)`. Keying a fresh `default_rng` per draw is the obvious approach and
is far too slow here: it would be roughly 1,400 `SeedSequence` spawns per
simulation across 485,100 simulations. Drawing five `(n_drivers, n_laps)` arrays
up front costs about 7,000 doubles per simulation, which is cheaper than the
per-call draws it replaces.

Each channel gets its own spawned substream, so adding a channel later cannot
shift the numbers an existing one produces.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def make_rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


@dataclass(frozen=True)
class _NormalDraw:
    """A single pre-drawn standard normal, presented as the slice of the
    `Generator` interface its call site uses.

    Exists so `lap_time.noise_s`, `lap_time.ar1_noise_s` and `pit.pit_stop_noise_s`
    keep taking "something with `.normal`/`.random`" and need no signature change
    — which also means every existing test that hands them a real `Generator`
    still exercises the same code path.
    """

    z: float
    u: float

    def normal(self, loc: float = 0.0, scale: float = 1.0) -> float:
        return loc + self.z * scale

    def random(self) -> float:
        return self.u


class DrawTable:
    """All of one simulation's randomness, indexed by `(driver, lap, channel)`.

    Channels are separate because two draws taken on the same lap by the same
    driver must not be the same number: a pit stop takes a normal *and* a
    uniform, and an overtake roll must be independent of both.
    """

    # Order is part of the reproducibility contract: changing it changes every
    # simulation's numbers. Append only.
    _CHANNELS = ("pace", "pit_noise", "pit_slow", "pass_roll")

    def __init__(self, seed: int, drivers: list[str] | tuple[str, ...], total_laps: int):
        # Sorted, so the table a driver sees does not depend on the order the
        # caller happened to collect the field in.
        self._row = {driver: i for i, driver in enumerate(sorted(drivers))}
        # +2 so lap numbers are usable directly as an index, including a
        # one-past-the-end lap without bounds arithmetic at every call site.
        shape = (max(1, len(self._row)), total_laps + 2)
        substreams = np.random.SeedSequence(seed).spawn(len(self._CHANNELS))
        self._pace = np.random.default_rng(substreams[0]).standard_normal(shape)
        self._pit_noise = np.random.default_rng(substreams[1]).standard_normal(shape)
        self._pit_slow = np.random.default_rng(substreams[2]).random(shape)
        self._pass_roll = np.random.default_rng(substreams[3]).random(shape)
        self._shape = shape

    def _cell(self, array: np.ndarray, driver: str, lap: int) -> float:
        row = self._row.get(driver)
        if row is None or not (0 <= lap < self._shape[1]):
            # A driver or lap outside the table (synthetic data, or a lap past
            # the race distance) falls back to a deterministic zero rather than
            # raising: the alternative is a crash in a Monte Carlo run, and a
            # zero draw is the mean of every channel here.
            return 0.0
        return float(array[row, lap])

    def pace(self, driver: str, lap: int) -> _NormalDraw:
        """Pace noise for one driver-lap. Shared by the iid and AR(1) paths."""
        return _NormalDraw(z=self._cell(self._pace, driver, lap), u=0.0)

    def pit(self, driver: str, lap: int) -> _NormalDraw:
        """Pit-stop noise: a normal for the ordinary variability, a uniform for
        the slow-stop roll."""
        return _NormalDraw(
            z=self._cell(self._pit_noise, driver, lap),
            u=self._cell(self._pit_slow, driver, lap),
        )

    def passing(self, driver: str, lap: int) -> _NormalDraw:
        """The attacker's single overtake roll for this lap.

        One per driver-lap is enough: `resolve_positions` gives each car at most
        one roll per lap — the blue-flag yield and the normal difficulty-gated
        attempt are mutually exclusive branches, and a car that has just been
        passed becomes `ahead` for the next comparison rather than rolling again.
        """
        return _NormalDraw(z=0.0, u=self._cell(self._pass_roll, driver, lap))
