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
- **Phase 2 (parameter fitting): done, after two correction passes.**
  `parameters/` (tyre, fuel, pace, pit_loss, dirty_air, overtaking, fit_all)
  fitted for all five catalogue races; results persisted to `data/fitted/`.
  Catalogue: 2019 Hungarian, 2019 Mexican, 2019 Japanese, 2019 Monaco, 2021
  Spanish (2018 Australian GP and 2019 Singapore GP both dropped — see
  DECISIONS.md for why, and for how they were screened for this time:
  running the actual fitter on candidates, not inspecting secondary stats).
  - **Honest framing (see DECISIONS.md's "fitted vs prior" table): this is
    not a fully data-driven model.** Fitted from real data: `fuel_effect_s_per_lap`
    (pooled cross-driver regression, all 5 races), most of `base_pace_s`,
    70-95% of tyre degradation slopes (rest fall back, tracked per-cell),
    `pit_lane_loss_s`, `overtake_difficulty`. Declared priors, not fitted:
    `dirty_air` (every race), `pit_stop_stationary_s` (every race),
    `overtake_skill`/`defence_skill` (uniform, every driver), SC/VSC
    multipliers on the 3-4/5 races with no safety car period, and — new —
    the *ordering and minimum separation* of tyre compound offsets
    (starting point is fitted, but 58-80% of drivers per race need a
    declared monotonic prior to correct it). Don't let README/Phase 8
    language drift back to "parameters fitted from real race data"
    unqualified.
  - Degradation slopes: positive on every race, verified via per-cell
    provenance tracking (`fit_diagnostics["tyre_cell_provenance"]`) with a
    pre-registered ceiling on fallback-cell fraction and a pre-registered
    (not post-hoc) floor on the raw pre-clip positive rate — see DECISIONS.md
    for why an earlier version of this bar was invalid (tuned after seeing
    Singapore's score).
  - Compound offset ordering is enforced via a declared, weighted-isotonic
    monotonic prior with *both* a minimum (0.15s) and maximum (1.2s)
    adjacent-gap floor/cap — isotonic regression alone only guarantees
    non-decreasing order, not separation, and was verified to collapse
    compounds to indistinguishable offsets before the floor was added.
  - **Dirty air is unfit on every catalogue race** (falls back to the spec
    6.6 prior), after fixing a real conflation with traffic (spec 6.9) that
    was inflating it on street circuits. Not solvable within Phase 2's
    single-race scope; needs multi-race pooling or telemetry.
  - Run `python backend/scripts/fit_parameters.py` to refit and print a
    diagnostics summary per race.
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
  from data in the first place.
