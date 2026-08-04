# Pit Wall Multiverse

**A counterfactual Formula 1 race simulator.** Pick a real race that already happened,
change one strategic decision, and watch the race play out differently — lap by lap.

The distinguishing property: **every simulation is anchored to a race whose real outcome
is known**, so the simulator's fidelity is *measurable*. Before the engine is allowed to
change history, it must first reproduce history within stated tolerances (see
[`VALIDATION.md`](VALIDATION.md)). That measurability is the project's core technical claim.

> This is **not** a race-outcome predictor, a telemetry dashboard, or a sim-racing game.
> It answers the counterfactual question fans actually argue about: *what if they'd pitted
> a lap earlier?*

## Status

Under active construction against [`PROJECT_SPEC.md`](PROJECT_SPEC.md), built in gated
phases (spec Part 12). See [`DECISIONS.md`](DECISIONS.md) for the running log.

- [x] **Phase 0 — Scaffold.** Repo structure, tooling, docs, test runners verified.
- [ ] Phase 1 — Data layer (FastF1 ingestion, cleaning, catalogue)
- [ ] Phase 2 — Parameter fitting
- [ ] Phase 3 — Simulator + validation ⚠️ hard gate
- [ ] Phase 4 — Counterfactual engine
- [ ] Phase 5 — API
- [ ] Phase 6 — Frontend core
- [ ] Phase 7 — Multiverse tree
- [ ] Phase 8 — Polish + docs

## Architecture

The **simulation core is a pure library with no I/O** — it takes a race state plus
`Decision` objects and returns a `SimulationResult`, knowing nothing about FastF1, HTTP,
or React. FastF1 is imported in exactly one place (`backend/pitwall/ingestion/`) and is
never called during an HTTP request; data is prefetched offline.

```
FastF1 ─▶ ingestion ─▶ RaceSnapshot ─▶ parameters (fitted) ─▶ simulation (pure)
                                                                    │
                                        ┌───────────────────────────┴───────────┐
                                        ▼                                        ▼
                                   validation (replay reality)         counterfactual (re-sim)
                                        │                                        │
                                        ▼                                        ▼
                                   VALIDATION.md                          api ─▶ frontend
```

## Stack

Python + NumPy simulation core · scikit-learn / scipy for parameter fitting · FastAPI +
Pydantic v2 backend · React 18 + Vite + TypeScript + Tailwind frontend · Recharts +
D3 (multiverse tree) · pytest + vitest. No LLM in the simulation path; no deep learning.

## Quick start

```bash
# Backend
python -m pip install -r backend/requirements.txt
python -m pytest

# Frontend
cd frontend && npm install && npm run dev
```

Full run commands (prefetch, fit, validate, serve) are in [`CLAUDE.md`](CLAUDE.md).

## License

MIT — see [`LICENSE`](LICENSE).
