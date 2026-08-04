# CLAUDE.md — Pit Wall Multiverse conventions & commands

A counterfactual Formula 1 race simulator. Pick a real race, change one strategic
decision, watch the alternate race play out. Every simulation is anchored to a race
whose real outcome is known, so the simulator's fidelity is **measurable** — that is
the core technical claim (see `PROJECT_SPEC.md`).

## The one architectural rule

The **simulation core (`backend/pitwall/simulation/`) is a pure library with no I/O**.
It takes a `RaceState` + `Decision` objects and returns a `SimulationResult`. It never
imports FastF1, HTTP, caching, or anything about the frontend. FastF1 is imported in
**exactly one place**: `backend/pitwall/ingestion/`. FastF1 must never be called during
an HTTP request — data is prefetched offline and served from `data/fitted/`.

## Layout (see PROJECT_SPEC.md Part 3)

```
backend/pitwall/
  domain/         pure frozen data structures, no logic
  ingestion/      the ONLY place FastF1 is imported
  parameters/     fit model params from real data (tyre/pace/fuel/pit/dirty-air)
  simulation/     PURE, deterministic, no I/O
  validation/     replay reality & score  -> VALIDATION.md
  counterfactual/ apply Decision, re-sim from lap N, multiverse tree
  api/            FastAPI
frontend/         React 18 + Vite + TS + Tailwind
data/cache/       FastF1 cache (gitignored)
data/fitted/      persisted fitted params (committed)
```

## Environment (this machine)

- Python **3.14**, pip (no `uv`). FastF1 3.8.3, numpy 2.4, scipy 1.17, sklearn 1.8,
  pandas 2.3 all verified importing and fetching data.
- Node 24 / npm 11.
- Windows. Shell examples below are cross-platform where possible.

## Commands

Install backend deps:

```bash
python -m pip install -r backend/requirements.txt
```

Run backend tests (config in `pyproject.toml`, `pythonpath=backend`):

```bash
python -m pytest
```

Prefetch race data into the FastF1 cache (offline, before serving):

```bash
python backend/scripts/prefetch_races.py
```

Fit parameters for all catalogue races:

```bash
python backend/scripts/fit_parameters.py
```

Regenerate `VALIDATION.md`:

```bash
python backend/scripts/run_validation.py
```

Run the API (after prefetch + fit):

```bash
python -m uvicorn pitwall.api.main:app --app-dir backend --reload
```

Frontend:

```bash
cd frontend && npm install && npm run dev
```

Frontend tests:

```bash
cd frontend && npm run test
```

Everything via Docker:

```bash
docker-compose up
```

## Conventions

- **Determinism is mandatory.** All randomness flows through one seeded
  `numpy.random.Generator` passed explicitly down the call chain. No module-level
  `random`/`np.random`. Same seed + same inputs => byte-identical output.
- **Immutability.** Domain objects are `@dataclass(frozen=True)`. The counterfactual
  engine forks state repeatedly; shared mutable state is forbidden.
- **Never hardcode a fittable value.** Constants come from `RaceParameters` or are
  documented priors-with-bounds in `DECISIONS.md`.
- **Never silently drop data.** Every excluded lap is counted with a recorded reason.
- **Never relax a validation threshold to pass.** Fix the model or drop the race; document it.
- Keep `DECISIONS.md` (append-only) and `VALIDATION.md` current.

## Build phase status

See `DECISIONS.md` for the running log. Phases are gated (Part 12 of the spec);
Phase 3 (validation) is a hard gate — no counterfactuals until replay reproduces reality.

- **Phase 0 (scaffold): done.**
- **Phase 1 (data layer): done.** `ingestion/` (cache, loader, cleaning,
  safety_car, catalogue) implemented; 5-race catalogue curated and each race's
  driver counts, finishing order, and DNFs verified against FastF1's own
  `session.results`. Catalogue: 2018 Australian, 2019 Singapore, 2019 Monaco,
  2019 Hungarian, 2021 Spanish — all strategy/physics-decided, none resolved by
  a stewarding judgement call or a red flag (Abu Dhabi 2021 and British GP 2021
  were both deliberately excluded for this reason; see DECISIONS.md). Abu Dhabi
  2021's SC (L53-57) and VSC (L36-37) periods are still verified against
  `race_control_messages` as an ingestion test fixture. Run `python
  backend/scripts/prefetch_races.py` to (re)warm the cache and print the
  cleaning report for every race.
- **Phase 2 (parameter fitting): done, after three correction passes.**
  `parameters/` (tyre, fuel, pace, pit_loss, dirty_air, overtaking, fit_all)
  fitted for all five catalogue races; results persisted to `data/fitted/`.
  Catalogue: 2019 Hungarian, 2019 Mexican, 2018 Bahrain, 2019 Monaco, 2021
  Spanish. Three races were dropped after being picked on data quality/
  narrative first and found to be decided by something other than on-track
  racing: 2018 Australian GP, 2019 Singapore GP, 2019 Japanese GP (a
  chequered-flag timing error under Article 43.2 — see DECISIONS.md). **Every
  future candidate must be run through `scripts/screen_race.py` (hard
  disqualifier check: penalties/red flags/DSQs/early front-runner DNFs that
  touch the featured story) *before* checking data quality or writing any
  contested-decision narrative** — the selection process was running in the
  wrong order for three races running before this was made mechanical.
  - **Honest framing (see DECISIONS.md's updated "fitted vs prior" table):
    this is a simulator with a handful of genuinely fitted parameters and
    priors for most of the rest, not a data-driven model.**
    `fuel_effect_s_per_lap` is fitted-and-distinguishable-from-its-0.05-prior
    on only 1 of 5 races (2019 Australian GP, CI 0.051-0.073) — checked with
    a cluster-robust confidence interval, not a condition number, since laps
    from the same driver aren't independent observations; the other 4
    races' CIs contain 0.05, so "consistent with the prior" is the honest
    label there, not "fitted." **This has a knock-on consequence for tyre
    degradation slopes that the accounting must carry, not just fuel
    effect**: pass 2 (`tyre.fit_driver_final`) holds the fuel effect fixed
    while fitting each compound's age slope, specifically to de-confound age
    from fuel burn — so on the 4 races where that fuel effect is itself only
    prior-consistent, the resulting slopes are **fitted conditional on a
    prior**, not independently fitted, even though the regression that
    produces them is real and runs on real lap times. Say "fitted
    conditional on the fuel prior" for those 4 races' 66-95% non-fallback
    tyre cells, not "fitted" unqualified. Compound-offset **separation** is
    prior-dominated outright, not merely "hybrid": 61% of all
    adjacent-compound gaps across the catalogue sit at *exactly* the
    declared 0.15s floor, meaning zero information from that driver's own
    data for the majority of pairs — **this means `ChangeCompound`
    counterfactuals (one of the six Decision types, spec 5.3) will mostly
    return a near-mechanical answer reflecting the 0.15s floor constant, not
    anything specific to that driver or race.** Decide before Phase 4/6
    whether to ship `ChangeCompound` in v1 at all, or ship it visibly
    flagged as prior-driven in the UI — `ChangePitLap` and `ShiftSafetyCar`
    are where this model actually has something fitted to say; don't let a
    demo lead with the weakest lever. Fully prior, every race: `dirty_air`,
    `pit_stop_stationary_s`, `overtake_skill`/`defence_skill` (uniform),
    SC/VSC multipliers on races with no safety car. `base_pace_s` (most
    drivers) and `pit_lane_loss_s` (downstream of the pace model, itself
    unvalidated) are the closest things to unconditionally fitted. Don't let
    README/Phase 8 language drift back to "parameters fitted from real race
    data" unqualified.
  - Degradation slopes: positive on every race, verified via per-cell
    provenance tracking (`fit_diagnostics["tyre_cell_provenance"]`) with a
    pre-registered floor on the raw pre-clip positive rate and a
    just-above-observed (not pre-registered — a deliberately different use
    of "having seen the data," see DECISIONS.md) ceiling on fallback-cell
    fraction.
  - Compound offset ordering is enforced via a declared, weighted-isotonic
    monotonic prior with *both* a minimum (0.15s) and maximum (1.2s)
    adjacent-gap floor/cap — isotonic alone only guarantees non-decreasing
    order, not separation, and was verified to collapse compounds to
    identical offsets before the floor was added.
  - **Dirty air is unfit on every catalogue race** (falls back to the spec
    6.6 prior), after fixing a real conflation with traffic (spec 6.9) that
    was inflating it on street circuits. Not solvable within Phase 2's
    single-race scope; needs multi-race pooling or telemetry.
  - Cleaning (`ingestion/cleaning.py`) gained a sustained-pace-step
    ("suspected damage") detector for a real gap: MAD outlier detection
    can't catch a car running consistently degraded pace for many laps
    (that pace becomes the stint's own norm). Tuned conservatively (4.0s
    sustained over 5+ laps, rolling local baseline) after an initial version
    produced 294 false positives on 2019 Monaco — almost certainly
    deliberate one-stop pace management, not damage. **It currently fires on
    zero laps across the entire catalogue, so it is exercised only by its
    two synthetic unit tests, not by any real race — it has not been
    validated against a confirmed real damage case.** Keep it, but don't
    describe it as validated; it's a defensible, tested safeguard for future
    candidates, not a proven detector.
  - Run `python backend/scripts/fit_parameters.py` to refit and print a
    diagnostics summary per race; `python backend/scripts/screen_race.py
    <year> <event>` to hard-disqualifier-screen a new candidate first.
- Phase 3 (simulator + validation, hard gate): not started. Watch list going
  in, all from Phase 2: (1) dirty air is prior-only everywhere, so expect
  undercut/overtake dynamics weaker than reality until revisited; (2) if
  `pit_lane_loss_s` is biased (it's downstream of the pace model and was not
  independently validated), every counterfactual's "was pitting worth it"
  comparison inherits that bias in one direction — check spec 8.2's
  strategy-accuracy metric specifically for this; (3) a good gap-trace match
  in validation could be validating the declared priors as much as the
  fitted terms, given how much of `RaceParameters` is prior — don't read a
  passing validation as confirming parts of the model that were never fit
  from data in the first place; (4) compound-offset separation is mostly the
  declared 0.15s floor, so a validation pass on lap-time MAE near compound
  transitions may be validating that floor, not real compound physics.
