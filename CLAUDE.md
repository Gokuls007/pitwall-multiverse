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
- Phase 2 (parameter fitting): not started.
