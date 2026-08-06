#!/usr/bin/env python
"""Fit the catalogue-wide pooled tyre degradation slopes.

These are the **terminal tier** of the degradation fallback chain in
`parameters/tyre.py`. They exist because that chain used to end in
`flat_zero` — a degradation rate of exactly 0.0 s/lap — which is the one value a
degradation rate can never take. A tyre that does not wear is not a conservative
estimate; it is a physically impossible one, and it produced the largest
counterfactual in the catalogue: 2019 Hungary VER on softs the model believed
never wore, "gaining" a minute over a race distance.

The chain now runs:

    own fit  ->  this race's pooled cell  ->  catalogue-wide pooled slope

and never reaches a value that cannot be true.

Why these are a committed constant rather than computed on demand: `fit_all` is
called one race at a time (`build_fixtures.py` fits per race, deliberately, so
that a race's parameters depend only on that race). A catalogue-wide quantity is
therefore not available at fit time. So it is fitted here, once, and pinned by
`test_compound_slope_priors_match_the_catalogue` — the same drift-guard pattern
as `fit_min_following_gap.py` and `fit_noise_autocorrelation.py`.

Method: the observation-weighted mean, across every catalogued race, of every
driver's own per-compound slope from a pass-2 fit with that race's fuel effect
held fixed. Fuel-fixed rather than joint, because the joint fits are collinear
for any driver who never revisited a compound, and that collinearity biases the
slope negative — at Hungary five drivers' joint SOFT slopes came out between
-0.63 and -1.90 s/lap, and were then discarded by the positivity filter as
"noisy" when they were in fact confounded. Held fixed, all 34 cells at Hungary
are physically plausible.

Usage:
    python backend/scripts/fit_compound_slope_priors.py
"""

from __future__ import annotations

import sys
import warnings
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

from pitwall.parameters import fit_all, tyre  # noqa: E402
from pitwall.ingestion.catalogue import CATALOGUE  # noqa: E402
from pitwall.ingestion.loader import load_race  # noqa: E402


def fit_priors() -> dict[str, tuple[float, int, int]]:
    """compound -> (weighted slope, contributing cells, total observations)."""
    cells: dict[str, list[tuple[float, int]]] = defaultdict(list)

    for entry in sorted(CATALOGUE, key=lambda e: e.race_key):
        snapshot, _ = load_race(entry.year, entry.fastf1_event_identifier)
        params = fit_all.fit_catalogue_with_pooled_dirty_air([snapshot])[entry.race_key]
        fuel_effect = params.fuel_effect_s_per_lap

        for driver in sorted({lap.driver for lap in snapshot.laps}):
            try:
                frame = fit_all._laps_frame(snapshot, driver)
                _, _, models, _, provenance = tyre.fit_driver_final(frame, fuel_effect, {})
            except Exception:  # noqa: BLE001 - a driver we can't fit doesn't contribute
                continue
            for compound, cell in provenance.items():
                # Only this driver's OWN estimate contributes; pooled or
                # fallback cells would make the prior partly self-referential.
                if cell.provenance != "own_fit":
                    continue
                slope = cell.final_slope
                if not (0 <= slope <= tyre.MAX_PLAUSIBLE_SLOPE_S_PER_LAP):
                    continue
                cells[compound.value].append((slope, models[compound].n_observations))

    priors: dict[str, tuple[float, int, int]] = {}
    for compound, items in cells.items():
        total = sum(n for _, n in items)
        weighted = sum(s * n for s, n in items) / total
        priors[compound] = (weighted, len(items), total)
    return priors


def main() -> int:
    priors = fit_priors()
    if not priors:
        print("no usable cells across the catalogue", file=sys.stderr)
        return 1

    print(f"{'compound':<14}{'slope s/lap':>13}{'cells':>8}{'laps':>8}")
    for compound, (slope, n_cells, n_obs) in sorted(priors.items(), key=lambda kv: -kv[1][0]):
        print(f"{compound:<14}{slope:>13.5f}{n_cells:>8}{n_obs:>8}")

    # The default for compounds the catalogue never sampled enough of. Chosen as
    # the mid compound's slope rather than the overall mean, because the overall
    # mean is dominated by whichever compound happened to be run most.
    default = priors.get("MEDIUM", (0.0, 0, 0))[0]
    print(f"\ndefault (MEDIUM){default:>11.5f}")
    print("\nPaste into pitwall/parameters/tyre.py:")
    print("CATALOGUE_POOLED_SLOPE_S_PER_LAP = {")
    for compound in ("SOFT", "MEDIUM", "HARD"):
        if compound in priors:
            print(f'    "{compound}": {priors[compound][0]:.5f},')
    for compound in ("INTERMEDIATE", "WET", "UNKNOWN"):
        print(f'    "{compound}": {default:.5f},')
    print("}")
    print(f"CATALOGUE_POOLED_SLOPE_DEFAULT_S_PER_LAP = {default:.5f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
