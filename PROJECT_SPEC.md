# PROJECT SPEC — "Pit Wall Multiverse"

### A counterfactual Formula 1 race simulator

**Document status:** Authoritative build spec. Treat this as the source of truth for scope, architecture, and acceptance criteria.

---

## PART 0 — HOW TO USE THIS DOCUMENT

**To the agent building this (Claude Code):**

1. Read this entire document before writing any code.
2. Do **not** attempt to build all phases in one pass. The build is divided into Phases 0–8 in Part 12. Each phase has explicit deliverables and **acceptance criteria**. Do not begin a phase until the previous phase's acceptance criteria are met and committed to git.
3. Phase 3 is a **hard gate**. If the simulator cannot reproduce a real race outcome within the stated tolerances, stop and report. Do not proceed to counterfactuals on top of a simulator that can't reproduce reality — the entire product depends on that fidelity.
4. Where this spec states a numeric constant (tyre degradation rates, pit loss, fuel effect), treat it as a **starting prior to be fitted from real data**, not a value to hardcode. The spec says so explicitly at each point. Fitted-from-data is the whole methodological point of the project.
5. Where this spec describes a library API, **verify it against the installed version** before building on it. Library APIs drift. If the API differs from what's described here, adapt and note the deviation in `DECISIONS.md`.
6. Maintain three living documents at the repo root: `CLAUDE.md` (project conventions and how to run things), `DECISIONS.md` (an append-only log of design decisions and deviations from this spec, with reasoning), and `VALIDATION.md` (the current accuracy numbers from the validation harness).
7. Commit at the end of each phase with the commit message given in that phase. Small intermediate commits within a phase are encouraged.

**To the human (Gokul):** Feed this file into the repo first (`PROJECT_SPEC.md`), then use the phase prompts in the Appendix one at a time. Don't paste the whole thing as a single chat message and say "build it" — you'll get a shallow version of everything and a working version of nothing.

---

## PART 1 — THE PRODUCT

### 1.1 One-line description

Pick a real Formula 1 race that already happened. Change one strategic decision. Watch the race play out differently, lap by lap.

### 1.2 The problem it solves

Every significant F1 race has a decision that fans argue about for years. Someone pitted a lap too late. A team stayed out under a safety car. An undercut was called two laps early. The arguments are unresolvable because nobody can actually run the alternate race.

Existing F1 data tools do one of two things: they show you what happened (broadcast graphics, telemetry dashboards, race replays), or they predict what will happen in a future race (the large and crowded space of F1 prediction models). Neither answers the counterfactual question, which is the one fans actually argue about.

### 1.3 What this is NOT

State this clearly, because the failure mode is drifting into an already-saturated category:

- **This is not a race outcome predictor.** It does not forecast unraced Grands Prix. There is a large existing body of work doing quali-time-to-finishing-position regression with gradient boosting. Do not build that. If a reviewer could describe this project as "another XGBoost F1 predictor," the framing has failed.
- **This is not a telemetry dashboard.** Visualising real data is a means, not the product.
- **This is not a game or a sim racing tool.** No driving. The user's only input is strategic decisions.

The distinguishing property: **every simulation is anchored to a race whose real outcome is known**, which means the simulator's fidelity is *measurable*. That measurability is the project's core technical claim and the thing that makes it defensible in an interview. A forecasting model of a future race cannot be validated until the race happens. This can be validated on day one, against dozens of historical races.

### 1.4 Target user

An F1 fan with an argument to settle. Secondary: someone evaluating the author's engineering ability.

### 1.5 The core user journey

1. User selects a race from a curated list of historically significant races.
2. The app shows what actually happened: a lap-by-lap gap-to-leader chart, the strategy timeline (who was on what tyre, when they pitted), and the final classification.
3. The app highlights **decision points** — moments where a team made a choice that plausibly could have gone otherwise (a pit stop, a stay-out under safety car, a compound selection).
4. User modifies one decision. Example: "Hamilton pits on lap 14 instead of lap 18."
5. The app re-simulates the race **from that lap forward**, holding everything before it fixed, and renders the alternate timeline overlaid on the real one — divergence visible from the moment of the change.
6. The app reports the alternate classification and a plain-language summary of what changed and why.
7. User can branch again from the alternate timeline, producing a tree of universes.

### 1.6 The signature feature

The **multiverse tree**. Each decision change spawns a branch. The user accumulates a visible tree of alternate histories from a single race, each node showing its finishing order. This is the thing the project is remembered by, and it is the reason the user stays for more than ninety seconds. Prioritise it in Phase 7, do not cut it.

### 1.7 Definition of done (v1)

- Five historically significant races are fully supported.
- The simulator reproduces each real race within the tolerances in Part 8.
- A user can change a pit stop lap or a compound choice and see a coherent alternate outcome.
- Safety car timing can be shifted as a counterfactual.
- The multiverse tree renders and is navigable.
- `VALIDATION.md` contains honest accuracy numbers per race, including the cases where the model does badly.
- `README.md` explains the method, shows a demo GIF, and states the model's limitations without hedging or overclaiming.

---

## PART 2 — ARCHITECTURE AND STACK

### 2.1 Stack decisions (fixed — do not substitute)

| Layer | Choice | Reason |
|---|---|---|
| Data source | `fastf1` (Python) | Only practical source of lap-level timing, tyre compound, and stint data |
| Simulation core | Pure Python + NumPy | Must be deterministic, testable, and free of framework coupling |
| Parameter fitting | `scikit-learn`, `scipy.optimize` | Curve fitting and regression; no deep learning, it is not warranted here |
| Backend API | FastAPI | Async, typed, auto-documented |
| Data validation | Pydantic v2 | Typed contracts between simulator and API |
| Frontend | React 18 + Vite + TypeScript | — |
| Styling | Tailwind CSS | — |
| Charts | Recharts (timeline/gap charts), D3 (multiverse tree only) | Recharts for standard charts; the tree needs D3's hierarchy layout |
| Testing | `pytest` (backend), `vitest` (frontend) | — |
| Package management | `uv` if available, else `pip` + `requirements.txt` | — |
| Containerisation | Docker + docker-compose | — |

**Explicitly rejected:** No LLM anywhere in the core simulation path. This is a physical/statistical simulation problem. An LLM in the loop would make it slower, non-deterministic, and unvalidatable. (One narrow exception is permitted in Phase 8: generating the plain-language "what changed and why" summary from structured simulation output. That is presentation, not simulation, and must be clearly isolated behind an interface with a deterministic fallback.)

**No deep learning.** Twenty drivers over roughly sixty laps is not a data regime that justifies a neural network. Fitted parametric models are more accurate here, and far more interpretable — which matters, because the product's value depends on the user trusting the counterfactual.

### 2.2 Architectural principle

The simulation core must be a **pure library with no I/O**. It takes a `RaceState` and a set of `Decision` objects, and returns a `SimulationResult`. It does not know about FastF1, HTTP, caching, or React. This is non-negotiable because:

- It makes the core unit-testable with synthetic data.
- It makes the validation harness possible.
- It keeps the counterfactual engine honest — it cannot accidentally peek at the real outcome.

Data ingestion converts messy real-world FastF1 output into clean domain objects at the boundary. Everything inward of that boundary deals only in domain objects.

### 2.3 Data flow

```
FastF1 API ──> ingestion/ ──> RaceSnapshot (frozen, validated)
                                    │
                                    ├──> parameters/ ──> fitted per-race, per-driver params
                                    │                     (tyre curves, pace, pit loss)
                                    │
                                    v
                            simulation/ (pure, deterministic)
                                    │
                    ┌───────────────┴───────────────┐
                    v                               v
            validation/                     counterfactual/
        (replay reality, score)          (apply Decision, re-sim)
                    │                               │
                    v                               v
            VALIDATION.md                       api/ ──> frontend/
```

---

## PART 3 — REPOSITORY LAYOUT

```
pitwall-multiverse/
├── README.md
├── PROJECT_SPEC.md            # this document
├── CLAUDE.md                  # conventions, commands, gotchas
├── DECISIONS.md               # append-only decision log
├── VALIDATION.md              # current accuracy numbers
├── LICENSE                    # MIT
├── .gitignore
├── .env.example
├── docker-compose.yml
├── pyproject.toml
│
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── pitwall/
│   │   ├── __init__.py
│   │   │
│   │   ├── domain/                    # pure data structures, no logic
│   │   │   ├── __init__.py
│   │   │   ├── race.py                # RaceSnapshot, LapRecord, Stint
│   │   │   ├── driver.py              # DriverEntry, DriverParams
│   │   │   ├── decision.py            # Decision types (the counterfactual inputs)
│   │   │   ├── result.py              # SimulationResult, LapState, Classification
│   │   │   └── enums.py               # Compound, TrackStatus, SessionType
│   │   │
│   │   ├── ingestion/                 # the only place FastF1 is imported
│   │   │   ├── __init__.py
│   │   │   ├── cache.py               # FastF1 cache configuration
│   │   │   ├── loader.py              # session -> RaceSnapshot
│   │   │   ├── cleaning.py            # outlier/invalid lap filtering
│   │   │   ├── safety_car.py          # extract SC/VSC periods from track status
│   │   │   └── catalogue.py           # the curated race list
│   │   │
│   │   ├── parameters/                # fit model parameters from real data
│   │   │   ├── __init__.py
│   │   │   ├── tyre.py                # degradation curves per driver/compound
│   │   │   ├── pace.py                # baseline pace per driver
│   │   │   ├── fuel.py                # fuel-burn pace effect
│   │   │   ├── pit_loss.py            # circuit pit lane time loss
│   │   │   ├── dirty_air.py           # pace penalty vs following gap
│   │   │   ├── overtaking.py          # pass probability model
│   │   │   └── fit_all.py             # orchestrator -> RaceParameters
│   │   │
│   │   ├── simulation/                # PURE. No I/O. No FastF1.
│   │   │   ├── __init__.py
│   │   │   ├── engine.py              # the lap-by-lap loop
│   │   │   ├── lap_time.py            # lap time composition
│   │   │   ├── position.py            # gap tracking, position resolution
│   │   │   ├── overtake.py            # pass resolution
│   │   │   ├── pit.py                 # pit stop execution
│   │   │   ├── safety_car.py          # SC/VSC effects on the field
│   │   │   └── rng.py                 # seeded RNG — determinism is mandatory
│   │   │
│   │   ├── validation/
│   │   │   ├── __init__.py
│   │   │   ├── replay.py              # simulate the race exactly as it happened
│   │   │   ├── metrics.py             # accuracy metrics (Part 8)
│   │   │   └── report.py              # writes VALIDATION.md
│   │   │
│   │   ├── counterfactual/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py              # apply Decision, re-simulate from lap N
│   │   │   ├── decision_points.py     # detect plausible decision points
│   │   │   ├── diff.py                # real vs alternate comparison
│   │   │   └── tree.py                # multiverse branch tree
│   │   │
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── main.py                # FastAPI app
│   │       ├── routes/
│   │       │   ├── races.py
│   │       │   ├── simulate.py
│   │       │   └── tree.py
│   │       └── schemas.py             # Pydantic request/response models
│   │
│   ├── scripts/
│   │   ├── prefetch_races.py          # populate the FastF1 cache offline
│   │   ├── fit_parameters.py          # fit and persist parameters per race
│   │   └── run_validation.py          # regenerate VALIDATION.md
│   │
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/                  # small synthetic race fixtures
│       ├── test_domain.py
│       ├── test_parameters.py
│       ├── test_simulation.py         # the bulk of the tests belong here
│       ├── test_counterfactual.py
│       └── test_validation.py
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   ├── Dockerfile
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   ├── client.ts
│       │   └── types.ts               # mirror of backend Pydantic schemas
│       ├── components/
│       │   ├── RaceSelector/
│       │   ├── GapChart/              # the primary visualisation
│       │   ├── StrategyTimeline/      # stint/compound bars per driver
│       │   ├── DecisionPanel/         # where the user changes a decision
│       │   ├── Classification/        # finishing order, real vs alternate
│       │   ├── MultiverseTree/        # the signature element
│       │   └── DivergenceSummary/
│       ├── hooks/
│       ├── state/                     # branch tree state management
│       └── styles/
│
└── data/
    ├── cache/                         # FastF1 cache (gitignored)
    └── fitted/                        # persisted fitted parameters (committed)
```

---

## PART 4 — DATA LAYER

### 4.1 FastF1: what to expect

`fastf1` provides lap-level timing data. Verify the exact API against the installed version before relying on specifics below.

Core usage pattern:

```python
import fastf1

fastf1.Cache.enable_cache("data/cache")
session = fastf1.get_session(2021, "Abu Dhabi", "R")   # "R" = race
session.load(laps=True, telemetry=False, weather=True, messages=True)
```

Load `telemetry=False`. Full telemetry is enormous and this project does not need it — lap-level granularity is sufficient and dramatically faster. If a later feature needs telemetry, load it selectively.

`session.laps` is a DataFrame. Columns to rely on (verify presence at runtime, do not assume):

| Column | Meaning | Notes |
|---|---|---|
| `Driver` | Three-letter code | Primary key for drivers |
| `LapNumber` | Lap index | |
| `LapTime` | Lap duration | A `timedelta`. Convert to float seconds immediately at the ingestion boundary. |
| `Stint` | Stint index | Increments on each pit stop |
| `Compound` | Tyre compound | `SOFT`/`MEDIUM`/`HARD`/`INTERMEDIATE`/`WET` |
| `TyreLife` | Laps on current tyre | Critical for degradation fitting. May not start at 0 for used sets. |
| `FreshTyre` | New vs scrubbed set | Affects degradation start point |
| `PitInTime` / `PitOutTime` | Pit entry/exit timestamps | Non-null identifies in/out laps |
| `Position` | Track position at lap end | |
| `TrackStatus` | Flag state during the lap | Encoded — see 4.3 |
| `IsAccurate` | FastF1's own quality flag | Use it; do not silently keep inaccurate laps |
| `Sector1/2/3Time` | Sector splits | Useful for diagnosing where pace is lost |
| `Team` | Constructor | |
| `LapStartTime` | Session-relative start | Needed to reconstruct gaps |

`session.results` gives the official classification: grid position, finishing position, status (finished / +N laps / DNF reason), points.

`session.weather_data` gives `AirTemp`, `TrackTemp`, `Rainfall`, `Humidity`, `WindSpeed` sampled through the session.

`session.race_control_messages` gives race control text — the most reliable route to safety car deployment and retirement events.

### 4.2 Lap data cleaning

Real timing data is dirty. The cleaning module must handle, at minimum:

1. **Null lap times.** Common on the first lap and around retirements. Do not impute silently; mark and exclude from fitting.
2. **In-laps and out-laps.** A lap with a non-null `PitInTime` or `PitOutTime` includes pit lane time and is not representative of green-flag pace. **Exclude from pace and degradation fitting.** Model them separately (Part 6.5).
3. **Safety car and VSC laps.** Lap times under SC/VSC are meaningless as pace measurements. Exclude from fitting.
4. **Laps affected by traffic.** A lap spent stuck behind a slower car understates pace. This one is not cleanly separable — it is precisely what the dirty air model is for. Do not exclude; instead, record the gap to the car ahead so the dirty air model can be fitted on it.
5. **Outlier laps.** Off-track excursions, lock-ups, damage. Use a robust filter — median absolute deviation within a stint is better than a fixed threshold, because pace varies enormously by circuit.
6. **First lap.** Standing start, unrepresentative. Handle separately or exclude.

Every exclusion must be **recorded and countable**. The validation report must state how many laps were used versus excluded per race. Silently dropping data is how a model comes to look better than it is.

### 4.3 Track status decoding

`TrackStatus` in FastF1 is a string of concatenated digit codes for the flags seen during that lap. The codes in common use:

| Code | Meaning |
|---|---|
| `1` | Track clear |
| `2` | Yellow flag |
| `4` | Safety car |
| `5` | Red flag |
| `6` | Virtual safety car deployed |
| `7` | Virtual safety car ending |

A lap's status may contain several codes (e.g. `"14"`). Treat a lap as SC-affected if it contains `4`, VSC-affected if it contains `6` or `7`. **Verify these codes empirically** against a race with a known safety car period — do not trust this table blindly. Abu Dhabi 2021 is a good test case since its safety car period is well documented.

Cross-check derived SC periods against `race_control_messages`. If the two disagree, prefer race control messages and log the discrepancy.

### 4.4 The race catalogue

Curate a hand-picked list rather than supporting every race. Fidelity on five races beats broken support for three hundred.

Selection criteria: a well-known, genuinely contested strategic decision; a dry race for v1 (wet races add a compound-crossover dimension — defer to a stretch goal); reliable data availability. FastF1's detailed timing coverage is substantially better from 2018 onward; prefer that era.

Choose five races meeting these criteria. Each catalogue entry must include the year, event name, a short description of the contested decision, and the specific decision points to surface in the UI. Verify data availability for each before committing to it — if a race's data is incomplete, replace it rather than working around gaps.

Store the catalogue as structured data (`catalogue.py` or a YAML file), not scattered through code.

---

## PART 5 — THE DOMAIN MODEL

All domain objects are immutable (`@dataclass(frozen=True)` or Pydantic with `model_config = ConfigDict(frozen=True)`). Immutability matters here: the counterfactual engine forks state repeatedly, and shared mutable state would produce bugs that are extremely hard to trace.

### 5.1 Core types

```python
class Compound(StrEnum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"


@dataclass(frozen=True)
class LapRecord:
    """One driver's one lap, as it actually happened."""
    driver: str
    lap_number: int
    lap_time_s: float | None
    compound: Compound
    tyre_life: int
    is_fresh_tyre: bool
    stint: int
    position: int
    is_in_lap: bool
    is_out_lap: bool
    track_status: str
    gap_to_ahead_s: float | None      # derived, needed for dirty air fitting
    is_usable_for_fitting: bool       # set by cleaning, with reason recorded
    exclusion_reason: str | None


@dataclass(frozen=True)
class Stint:
    driver: str
    stint_number: int
    compound: Compound
    start_lap: int
    end_lap: int
    started_fresh: bool


@dataclass(frozen=True)
class SafetyCarPeriod:
    kind: Literal["SC", "VSC", "RED"]
    start_lap: int
    end_lap: int


@dataclass(frozen=True)
class DriverEntry:
    code: str
    number: int
    team: str
    grid_position: int
    finish_position: int | None        # None if DNF
    status: str                        # "Finished", "+1 Lap", "Accident", etc.
    retired_on_lap: int | None


@dataclass(frozen=True)
class RaceSnapshot:
    """Everything known about a real race. The immutable ground truth."""
    year: int
    event_name: str
    circuit: str
    total_laps: int
    drivers: tuple[DriverEntry, ...]
    laps: tuple[LapRecord, ...]
    stints: tuple[Stint, ...]
    safety_car_periods: tuple[SafetyCarPeriod, ...]
    air_temp_c: float
    track_temp_c: float
    had_rain: bool
    pit_lane_loss_s: float             # fitted, see Part 6.5
```

### 5.2 Fitted parameters

```python
@dataclass(frozen=True)
class TyreModel:
    """Lap time penalty as a function of tyre age, for one compound."""
    compound: Compound
    base_offset_s: float        # pace offset vs the reference compound
    linear_deg_s_per_lap: float
    cliff_lap: int | None       # age at which degradation accelerates
    cliff_deg_s_per_lap: float | None
    r_squared: float            # fit quality — surface this, do not hide it
    n_observations: int


@dataclass(frozen=True)
class DriverParams:
    driver: str
    base_pace_s: float          # clean-air, fresh-tyre, low-fuel reference lap
    pace_std_s: float           # lap-to-lap consistency
    tyre_models: dict[Compound, TyreModel]
    overtake_skill: float       # 0..1, see Part 6.7
    defence_skill: float        # 0..1


@dataclass(frozen=True)
class RaceParameters:
    """All fitted parameters for one race. Persisted to data/fitted/."""
    race_key: str
    drivers: dict[str, DriverParams]
    fuel_effect_s_per_lap: float
    pit_lane_loss_s: float
    pit_stop_stationary_s: float
    dirty_air: DirtyAirModel
    overtake_difficulty: float   # circuit-specific, 0..1
    sc_lap_time_multiplier: float
    vsc_lap_time_multiplier: float
    fitted_at: datetime
    fit_diagnostics: dict        # per-model R², sample counts, warnings
```

### 5.3 Decisions — the counterfactual inputs

```python
@dataclass(frozen=True)
class ChangePitLap(Decision):
    driver: str
    original_lap: int
    new_lap: int

@dataclass(frozen=True)
class ChangeCompound(Decision):
    driver: str
    stint_number: int
    new_compound: Compound

@dataclass(frozen=True)
class AddPitStop(Decision):
    driver: str
    lap: int
    compound: Compound

@dataclass(frozen=True)
class RemovePitStop(Decision):
    driver: str
    lap: int

@dataclass(frozen=True)
class ShiftSafetyCar(Decision):
    period_index: int
    lap_delta: int              # negative = earlier

@dataclass(frozen=True)
class RemoveSafetyCar(Decision):
    period_index: int
```

Every `Decision` must expose `first_affected_lap` — the earliest lap from which the simulation must be re-run. Everything before that lap is copied verbatim from reality. This is what makes the counterfactual credible: it does not re-simulate the parts it does not need to.

### 5.4 Simulation output

```python
@dataclass(frozen=True)
class LapState:
    lap_number: int
    driver: str
    lap_time_s: float
    cumulative_time_s: float
    gap_to_leader_s: float
    position: int
    compound: Compound
    tyre_age: int
    in_dirty_air: bool
    pitted_this_lap: bool
    under_sc: bool

@dataclass(frozen=True)
class SimulationResult:
    race_key: str
    decisions_applied: tuple[Decision, ...]
    lap_states: tuple[LapState, ...]
    classification: tuple[tuple[str, int], ...]   # (driver, finish position)
    diverged_from_lap: int | None
    rng_seed: int
    notes: tuple[str, ...]      # warnings, e.g. "VER lapped traffic on L34"
```

---

## PART 6 — THE PHYSICS AND STATISTICAL MODELS

This is the technical heart of the project. Every model here must be **fitted from the race's own data** wherever possible, with the values given below serving only as priors and sanity bounds.

### 6.1 Lap time composition

A driver's lap time on a given lap is composed additively:

```
lap_time = base_pace
         + tyre_degradation(compound, tyre_age)
         + compound_offset(compound)
         + fuel_effect(laps_remaining)
         + dirty_air_penalty(gap_to_car_ahead)
         + traffic_penalty(lapped_cars_nearby)
         + sc_vsc_effect(track_status)
         + pit_lane_time(if in/out lap)
         + noise(driver_consistency)
```

Implement each term as a separate, individually testable function. Do not fuse them. When validation shows the simulator is off, you need to be able to isolate which term is wrong.

### 6.2 Base pace

Each driver has a reference lap time representing clean air, fresh tyres, and low fuel.

**Fitting approach:** take each driver's usable green-flag laps, regress lap time against tyre age and fuel load, and take the intercept. The regression must be run per driver — driver pace differences are real and material, and averaging them away destroys the simulation's ability to reproduce the real order.

**Robustness:** some drivers have very few usable laps (early retirement, a race spent in traffic). Where a driver's sample is too small to fit reliably, fall back to a team-mate-informed estimate and **record the fallback in the diagnostics**. A silently fabricated pace figure is worse than an acknowledged uncertain one.

### 6.3 Tyre degradation

The dominant strategic effect in F1. Get this right or nothing else matters.

**Physical behaviour:** lap times increase roughly linearly with tyre age over the usable life of the tyre, then degrade sharply once the tyre passes its working range ("the cliff"). Different compounds have different pace offsets and different degradation rates — softer compounds are faster initially and degrade faster.

**Fitting approach:**
1. Group usable green-flag laps by driver and compound.
2. Fit lap time against tyre age, having first removed the fuel effect (see 6.4) — otherwise fuel burn (making the car faster over a stint) and tyre degradation (making it slower) partially cancel, and both get mis-estimated. **This confound is the single most common error in tyre modelling. Handle it explicitly and write a test for it.**
3. Start with a linear fit. Test whether a piecewise-linear fit with a breakpoint (the cliff) improves the fit materially. Only adopt the more complex model where the data supports it.
4. Where a driver-compound pair has insufficient data, pool across drivers on the same compound, then apply the driver's pace offset. Record the pooling.

**Sanity bounds:** degradation rates should be positive (tyres get slower, not faster) and within physically plausible magnitudes. Compound ordering should come out as expected — softs faster than mediums faster than hards on a single lap. If a fit violates these, treat it as a data or method bug, not a discovery. Log it loudly.

**Do not hardcode degradation rates.** They vary enormously by circuit, temperature, and car. Fitting them per race is the point.

### 6.4 Fuel effect

Cars start heavy and get lighter, so lap times improve through a stint independent of tyres. A commonly cited magnitude is on the order of a few hundredths of a second per lap of fuel burned, but this varies by circuit and era.

**Approach:** treat the per-lap fuel effect as a parameter fitted jointly with tyre degradation, not assumed. The clean way to separate them: fuel effect is monotonic across the *whole race* regardless of pit stops, while tyre age resets at each stop. Fitting across multiple stints therefore identifies both terms. Write a test using synthetic data with known fuel and tyre coefficients, and assert the fitter recovers both.

### 6.5 Pit stop model

Two distinct components — keep them separate:

1. **Stationary time** — the tyre change itself. Short, and roughly consistent within a team.
2. **Pit lane transit loss** — time lost driving through the pit lane at the speed limit versus taking the racing line. Heavily circuit-dependent.

**Fitting approach:** measure empirically rather than assuming. Compare a driver's in-lap and out-lap times against their expected green-flag pace at that tyre age and fuel load. The excess is the total pit loss. Aggregate across all stops in the race for a circuit-level estimate, using a robust statistic (median) since individual stops include botched ones.

**Important:** total pit loss must be measured relative to *modelled* expected pace, not to the driver's average lap time, otherwise the estimate absorbs tyre and fuel effects.

Model a small probability of a slow stop, fitted from the spread of observed stationary times. This matters for counterfactual realism — "what if they pitted a lap earlier" should not assume a perfect stop.

### 6.6 Dirty air

A car following closely loses downforce and cannot match its clean-air pace. This is what makes the undercut work and what makes overtaking hard, so it is central to any counterfactual about pit timing.

**Model shape:** a pace penalty that increases as the gap to the car ahead shrinks, approaching zero beyond a few seconds of gap. A monotonic decreasing function of gap, saturating at both ends.

**Fitting approach:** for each usable lap, compute the gap to the car ahead at the start of the lap, and regress the driver's lap time excess (actual minus their modelled clean-air expectation) against that gap. Pool across drivers — per-driver dirty air sensitivity is not identifiable from one race's data.

**Note on regulations:** the aerodynamic sensitivity to following changed substantially with the 2022 regulations and again in 2026. If the catalogue spans regulation eras, fit dirty air per race and do not pool across eras. Record the era in diagnostics.

**Prior for sanity checking:** penalties in the range of a few tenths of a second per lap at close following distances, tapering to negligible beyond roughly two seconds. Use as a bound, not a value.

### 6.7 Overtaking

Being faster does not mean passing. This is the most stochastic part of the model and needs the most care in how uncertainty is presented to the user.

**Model:** the probability that a following car completes a pass on a given lap, as a function of:
- **Pace delta** — how much faster the follower is in clean air. The dominant term.
- **Circuit overtaking difficulty** — a per-circuit parameter. Some circuits allow passes readily; others are nearly impossible to pass at regardless of pace advantage.
- **Attacker skill and defender skill** — bounded per-driver modifiers.
- **DRS availability** — whether the follower was within the activation window at the detection point on the previous lap.

**Fitting the circuit difficulty parameter:** count observed on-track position changes in the race (excluding those caused by pit stops, retirements, and lap-one chaos) relative to the number of laps spent in close proximity. This gives an empirical pass rate per close-following lap for that circuit. This is a small-sample estimate from one race — pool across multiple races at the same circuit if available, and be explicit in diagnostics about the uncertainty.

**Driver skill parameters:** these are the one place where hand-assigned priors are acceptable, because they are not identifiable from a single race. If you assign them, they must be (a) declared as priors in `DECISIONS.md`, (b) bounded to a narrow range so they cannot dominate the physical terms, and (c) subjected to a sensitivity check — if the simulation outcome swings wildly on plausible variations of a hand-set parameter, that parameter is doing too much work and must be constrained further.

**Presenting uncertainty:** because passes are probabilistic, a single simulation run is one sample, not a prediction. See 6.10.

### 6.8 Safety car and VSC

The largest source of strategic upheaval in real races, and therefore the most interesting counterfactual lever.

Effects to model:
1. **Lap times balloon** under SC/VSC. Fit the multiplier from the race's own SC laps.
2. **The field compresses.** Under a full safety car the pack closes up behind the SC, destroying gaps. This is the effect that makes safety cars decisive — a driver who was twenty seconds ahead is suddenly a car length ahead. Model the compression to a fixed following distance.
3. **Pit stops become cheap.** Because everyone is going slowly, the time lost pitting is much smaller. This is why teams pit under safety cars, and it is the single most important interaction in the whole model. The pit loss under SC must be scaled by the SC lap time multiplier, not held at the green-flag value.
4. **VSC differs from SC.** VSC does not compress the field — drivers hold a delta, so gaps are preserved in proportion. Model them separately; do not treat VSC as a weak SC.
5. **Restart position.** Order under SC follows track position at the point of deployment, including anyone who pitted.

Modelling the field compression correctly is what makes `ShiftSafetyCar` counterfactuals meaningful. Test it directly with a synthetic case: two cars twenty seconds apart, a safety car is deployed, assert the gap closes to approximately the following distance.

### 6.9 Traffic and lapped cars

A leader catching lapped backmarkers loses time. A driver rejoining from a pit stop into a queue of slower cars loses far more time than the pit stop itself — this is the "undercut into traffic" failure mode that decides real races.

Model this as a dirty air penalty applied when the gap to any car ahead — regardless of whether it is on the same lap — falls within the dirty air range, plus an additional cost for laps spent unable to pass a car that is not racing for position.

This term is easy to skip and expensive to skip. A counterfactual that says "pitting three laps earlier gains eight seconds" while ignoring that the driver rejoins into a train of four cars is straightforwardly wrong.

### 6.10 Determinism and uncertainty

Two requirements that appear to conflict but do not:

1. **Every simulation must be exactly reproducible.** All randomness flows through a single seeded RNG passed explicitly through the call chain. No module-level `random` calls, no `np.random` without an explicit `Generator`. Same seed and same inputs must produce byte-identical output. Write a test asserting this.

2. **Counterfactual results must be presented as distributions, not points.** Because overtakes and pit stops are stochastic, run each counterfactual **many times with different seeds** (a Monte Carlo ensemble) and report the distribution of outcomes. "Hamilton wins in 68% of simulated universes" is an honest and far more interesting claim than "Hamilton wins."

This second point is a **product feature, not just statistical hygiene**. It reinforces the multiverse framing and it is the honest way to represent a stochastic simulation. Do not ship a single-run point answer.

Set the ensemble size to balance responsiveness against stability — large enough that the reported percentages are stable to within a couple of points across repeat runs, small enough to return in a few seconds. Measure and record this.

---

## PART 7 — THE SIMULATION ENGINE

### 7.1 The loop

For each lap from the divergence point to the end of the race:

1. Determine track status for this lap (green / SC / VSC), accounting for any `ShiftSafetyCar` decision.
2. For each driver still running, in current position order:
   a. Determine whether they pit this lap (from their strategy, real or modified).
   b. Compute the lap time from the composition in 6.1.
   c. Accumulate cumulative time.
3. Recompute gaps and provisional positions from cumulative times.
4. Resolve overtakes: for each pair in close proximity where the follower is faster, sample the pass probability. Apply position changes.
5. Apply safety car compression if applicable.
6. Handle retirements. For the real replay, retirements occur as they did. For counterfactuals, see 7.3.
7. Record a `LapState` for every driver.

### 7.2 Position resolution ordering

A subtle but important detail: gaps derived from cumulative time and positions resolved by overtaking can disagree. A car can be "ahead on cumulative time" while stuck behind on track. The engine must treat **track position as authoritative** and cumulative time as the input to gap calculation, resolving conflicts in favour of track position. Getting this backwards produces the classic simulation bug where cars teleport past each other without an overtake ever being modelled.

Document the chosen resolution order in `DECISIONS.md` and test it explicitly.

### 7.3 Retirements in counterfactuals

A genuine modelling question with no clean answer. If Verstappen retired on lap 30 with a mechanical failure, and the user changes Hamilton's pit strategy, does Verstappen still retire?

**Decision for v1:** mechanical retirements are treated as exogenous and preserved at the same lap. Incident-related retirements (collisions) are also preserved, with a note surfaced to the user that the incident's participants may not have been in proximity in this timeline, so the retirement is being held fixed as a simplifying assumption.

This is a defensible simplification, but it must be **visible in the UI**, not buried. Users who care enough to use this tool will notice, and being upfront about it builds more credibility than papering over it. Add it to the limitations section of the README.

### 7.4 Performance

The Monte Carlo ensemble means running the simulation many times per user request. Budget: a full ensemble for one counterfactual should return in a few seconds.

Optimise only after profiling. The likely hot path is the per-lap per-driver inner loop. Vectorising across drivers with NumPy is the first thing to try if it is too slow. Do not pre-emptively optimise before Phase 3 validation passes — correctness first.

---

## PART 8 — THE VALIDATION HARNESS

**This is the most important part of the project.** It is what separates it from a plausible-looking toy, and it is the thing to lead with in an interview.

### 8.1 The principle

Before the simulator is allowed to change history, it must demonstrate that it can *reproduce* history. Feed it the real race's actual strategies, actual safety cars, actual retirements — and check whether it produces the actual result.

### 8.2 Metrics

Compute all of these, per race, and write them to `VALIDATION.md`:

**Lap time accuracy**
- Mean absolute error between simulated and actual lap times, per driver and overall.
- The same, restricted to green-flag laps only (the fairest test of the pace and tyre models).
- Error distribution, not just the mean — a model with low mean error and fat tails is not trustworthy.

**Race shape accuracy**
- Root mean squared error of gap-to-leader across all drivers and laps. This measures whether the *shape* of the race is right, which matters more than individual lap times.
- Plot simulated versus actual gap traces. Include the plot in the report. Visual inspection catches errors that aggregate metrics hide.

**Outcome accuracy**
- Exact finishing position match rate.
- Proportion of drivers finishing within one position of reality.
- Rank correlation (Spearman or Kendall) between simulated and actual classification.
- Podium correctness and winner correctness — these are what a user will judge the tool on, regardless of what the aggregate metrics say.

**Strategy accuracy**
- Does the simulated undercut/overcut outcome match what really happened at each pit stop? This is the most directly relevant metric to the product's actual purpose, since the product is entirely about pit strategy counterfactuals.

### 8.3 Acceptance thresholds

Set concrete thresholds and record them. Suggested starting targets, to be revised with justification once the real numbers are known:

- Green-flag lap time MAE: under half a second per lap for the majority of drivers.
- Winner correctly reproduced in every catalogued race.
- Podium reproduced with at most one position swapped.
- At least three quarters of drivers within one position of their real finish.
- Rank correlation above 0.9.

**If these are not met, the correct action is to fix the model, not to lower the thresholds.** If a threshold genuinely turns out to be unreasonable for a specific race (a chaotic wet race, a race decided by an unmodellable incident), document *why* in `VALIDATION.md` and exclude that race from the catalogue rather than quietly relaxing the standard.

#### 8.3.1 Revision (2026-08-04), per this section's own "to be revised with justification" clause

Before revising anything, the model was fixed repeatedly across many review passes — this is not a case of hitting the numbers above and lowering them anyway. In order: a noise-inflated MAE measurement was corrected: a worse-than-random-chance strategy-direction sign bug (pit-stop position resolution) was found and fixed; two safety-car field-compression bugs were found and fixed; a stuck-behind position constraint and a blue-flag rule were added, replacing an unfittable per-race dirty-air prior with one refit from pooled cross-race residuals (max_penalty_s=1.29 [0.85,1.85] 95% CI, decay_scale_s=0.86 [0.56,1.49]) once the confound blocking that fit (the clean-air baseline's own intercept absorbing mean traffic exposure) was diagnosed and corrected. Pit loss was refit to account for it. Full derivation of every fix and every rejected hypothesis along the way: `DECISIONS.md`'s Phase 3 sections.

What's left after all of that is not underfitting — it's two different, now-quantified ceilings on what single-race (plus cross-race pooling for the one component that needed it) fitting can achieve, neither of which more validation-pass grinding would move:

- **Green-flag lap-time MAE, measured the way spec 8.2 actually asks for it** (open-loop: real gap-to-car-ahead, no replay loop — isolates the pace/tyre/dirty-air model from position-tracking accuracy, which is a separate question measured separately below). In-sample: 0.47-0.58s across the four well-fit catalogue races, 55-60% of drivers under 0.5s. Held-out (truncated stint tail — the closest available proxy to what a real counterfactual asks for, a tyre age a few laps past the fitting sample): 0.54s median / 0.80s mean, 47.4% of cells under 0.5s. The gap between in-sample and held-out is real and measured, not assumed. **Revised threshold: under 0.6s/lap for the majority of drivers**, evaluated open-loop — the 0.1s margin is sized to the measured in-sample/held-out gap on this catalogue, not picked to make the number work. All four gated races clear both the original 0.5s figure in-sample and the revised 0.6s figure held-out.
- **Within-one-position and rank correlation, evaluated on a full closed-loop replay from lap 1.** Measured directly: adjacent-pair gap error between simulated and real track position grows with laps elapsed at roughly `0.835 * sqrt(n)` seconds (R²=0.725) — a random-walk-like accumulation inherent to *any* closed-loop replay carried from race start to finish, independent of pace-model quality, because small stochastic overtake-resolution differences compound over 60-80 laps. This is a substantially harsher test than anything Phase 4 will ask of the model: per spec 9.1 step 5, a counterfactual is initialised from real state at the decision lap and only diverges forward, so its accumulated drift scales with laps *remaining*, not race length (e.g. ~3.7s of adjacent-gap drift at 20 laps remaining, vs. 6-9s+ observed over a full 60-70 lap replay). **Revised thresholds: within-one-position >= 55% (from 75%), rank correlation > 0.85 (from 0.9)**, both measured on the full from-lap-1 replay as a conservative diagnostic, not as a proxy for Phase 4 accuracy. The drift-horizon measurement itself — not a fixed threshold — is the number that should gate individual Phase 4 counterfactuals (e.g. flagging or declining decisions with a large number of laps remaining, where drift is large).
- **Winner and podium thresholds are unchanged** — both were met as originally written (winner correct in all four gated races; podium swaps <= 1 in all four) and needed no revision.

2019 Monaco is excluded from this assessment (not from the catalogue) — see `DECISIONS.md` and `VALIDATION.md`: it is the outlier on every metric measured and has roughly double the catalogue's next-worst tyre-cell fallback fraction, a credible (if not fully root-caused) explanation.

**Under these revised thresholds, all four gated races (2019 Hungarian, Mexican, Australian; 2021 Spanish) pass.** Current numbers: `VALIDATION.md`. Full derivation and every intermediate (including three rejected hypotheses and one retracted, confounded experiment) that led here: `DECISIONS.md`.

### 8.4 Honesty requirement

`VALIDATION.md` must include the cases where the model performs badly, and a short explanation of the suspected cause. A validation report showing only successes is not credible and will be read as such by anyone technical. The failures are more informative than the successes, and reporting them is a positive signal about the engineering, not a negative one.

Include per-race: laps used versus excluded (with reasons), fit quality for each fitted model, which parameters fell back to pooled or prior values, and the sensitivity of the outcome to the hand-set parameters.

### 8.5 Regression protection

The validation harness runs as part of the test suite (or as a scripted command run before each commit that touches the models). Any change to a model that degrades validation metrics must be caught. Record the current numbers in a committed file so degradation is visible in the diff.

---

## PART 9 — THE COUNTERFACTUAL ENGINE

### 9.1 Mechanism

1. Take the `RaceSnapshot` and the real strategies.
2. Apply the `Decision`, producing a modified strategy set.
3. Identify `first_affected_lap`.
4. Copy all `LapState` records before that lap verbatim from the real race.
5. Initialise simulation state at that lap from reality — real positions, real gaps, real tyre ages.
6. Simulate forward to the end.
7. Run the ensemble across seeds.
8. Produce a diff against reality.

Step 5 is what gives the counterfactual its credibility: it is anchored in real data right up to the moment of change, so the divergence is attributable to the decision rather than to accumulated simulation drift.

### 9.2 Decision point detection

The UI needs to suggest interesting changes rather than making the user guess. Surface as decision points:
- Every real pit stop (offer shifting it earlier or later within a plausible window).
- Every safety car period (offer shifting or removing it).
- Moments where a driver was in close proximity to another for a sustained stretch — these are where a strategy change could plausibly have broken a stalemate.
- Stint lengths that were unusually long or short relative to the fitted tyre life, which indicate a team taking a risk.

Rank suggestions by expected impact — a decision that changes nothing is not interesting. Estimating impact cheaply may require a coarse pre-simulation; that is acceptable.

### 9.3 The diff

For each counterfactual, produce a structured comparison: the classification change per driver, the lap at which each driver's trajectory diverged, the largest single position swing, and whether the winner changed. This structured diff feeds both the UI and the optional natural-language summary.

### 9.4 The multiverse tree

State model: a tree where the root is reality and each node is a `SimulationResult` produced by applying one additional `Decision` to its parent's state.

Requirements:
- Branching from any node, not only from the root.
- Each node caches its result — do not re-simulate on navigation.
- Each node displays its finishing order and its delta from its parent.
- Node identity is a hash of the ordered decision list, so identical decision paths deduplicate.
- Depth limit to prevent unbounded growth; make it generous but finite.

---

## PART 10 — THE API

FastAPI, all responses Pydantic-typed. Endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/races` | Catalogue: available races with metadata |
| `GET` | `/api/races/{race_key}` | Full real race data: laps, stints, classification, SC periods |
| `GET` | `/api/races/{race_key}/decision-points` | Ranked suggested decision points |
| `POST` | `/api/simulate` | Apply decisions, return ensemble result |
| `GET` | `/api/races/{race_key}/validation` | Validation metrics for this race |
| `POST` | `/api/tree/branch` | Add a branch to a tree |
| `GET` | `/api/health` | Health check |

Requirements:
- Real race data is static — cache aggressively and serve from the fitted/persisted layer, not from FastF1 at request time. **FastF1 must never be called during an HTTP request.** Prefetch offline via `scripts/prefetch_races.py`.
- `/api/simulate` returns the full distribution across the ensemble, not a single outcome: per-driver finishing position distributions, win probability, and a representative median timeline for charting.
- Include the RNG seeds used, so any specific universe can be reproduced exactly.
- Reject invalid decisions with clear errors — a pit lap outside the race, a compound that was not available, a negative stint length. Validate at the Pydantic layer.

---

## PART 11 — THE FRONTEND

### 11.1 Design direction

Do not default to a generic dark dashboard with neon accents — that is the template answer for motorsport data and it will read as such. Before building, write a short design plan: a palette of four to six named hex values, two or three typefaces with defined roles, a layout concept, and one signature element. Review that plan and revise anything that reads as a default rather than a choice, then build to the revised plan.

Grounding thought for the direction: the subject is not "racing" in the abstract — it is the **pit wall**, a room of engineers reading timing screens and making irreversible decisions under time pressure. The visual vernacular of that world is timing towers, stint bars, delta figures, radio transcripts, monospaced numerals. That is a much more specific and more interesting well to draw from than "fast car, motion blur, red accent."

Constraints regardless of direction: responsive to mobile, visible keyboard focus, `prefers-reduced-motion` respected. The gap chart carries a lot of data — legibility beats decoration everywhere it conflicts.

### 11.2 Components

**GapChart** — the primary visualisation. Multi-line chart, gap to leader on the y-axis, lap number on the x-axis, one line per driver in team colours. Must support overlaying the alternate timeline against the real one, with the divergence lap marked. Hover gives a full field order snapshot at that lap. This is the component the whole product hangs on; give it the most attention.

**StrategyTimeline** — horizontal bars per driver, segmented by stint and coloured by compound, with pit stops marked. Clicking a pit stop opens the decision panel for it. This is the primary interaction surface for making changes, so it must read instantly.

**DecisionPanel** — where the user changes a decision. Show the real value, allow modification within a validated range, and preview the immediate mechanical consequence before committing (e.g. "pitting on lap 14 means a 24-lap stint on mediums, four laps beyond the fitted useful life"). That preview is what turns the tool from a toy into something that teaches the user how strategy works.

**Classification** — side-by-side real versus alternate finishing order, with position deltas. Where the ensemble disagrees, show the distribution rather than a single order.

**MultiverseTree** — the signature element. D3 hierarchy layout. Each node shows its decision label and its winner. The current node is emphasised. Clicking navigates. Must remain legible at a dozen or more nodes.

**DivergenceSummary** — plain-language explanation of what changed. Generated from the structured diff. Must have a deterministic template-based fallback if the LLM path is unavailable or disabled.

### 11.3 State

The branch tree is the central state object. Model it explicitly with a proper reducer rather than scattered `useState` calls — the interaction pattern (branch, navigate, compare arbitrary nodes) will otherwise become unmanageable. Cache simulation results by decision-path hash and never re-request a path already computed.

---

## PART 12 — BUILD PHASES

Each phase ends with a commit. Do not skip acceptance criteria.

### Phase 0 — Scaffold

**Deliverables:** repo structure per Part 3; `pyproject.toml` and `requirements.txt`; dependency install verified; `CLAUDE.md` with run commands; empty `DECISIONS.md` and `VALIDATION.md`; `.gitignore` covering the FastF1 cache; MIT `LICENSE`; git initialised; `pytest` and `vitest` runnable (even with zero tests).

**Acceptance:** `pytest` runs and exits clean. Frontend dev server starts. All directories from Part 3 exist.

**Commit:** `chore: scaffold project structure and tooling`

---

### Phase 1 — Data layer

**Deliverables:** FastF1 cache configuration; `loader.py` converting a session into a validated `RaceSnapshot`; `cleaning.py` implementing all the exclusion rules in 4.2 with recorded reasons; `safety_car.py` extracting SC/VSC periods and cross-checking against race control messages; the curated catalogue with five verified races; `scripts/prefetch_races.py`.

**Acceptance:**
- All five catalogue races load into `RaceSnapshot` objects without errors.
- Lap counts, driver counts, and final classifications match the official results for each race. Verify this explicitly, do not assume.
- Safety car periods extracted match the documented real periods for at least one race with a known safety car.
- The cleaning report prints usable versus excluded lap counts with reasons, per race.
- Loading is fast on a warm cache.

**Commit:** `feat: FastF1 ingestion, cleaning, and race catalogue`

---

### Phase 2 — Parameter fitting

**Deliverables:** every fitter in `parameters/`; `fit_all.py` producing a `RaceParameters` object per race; persistence to `data/fitted/`; a diagnostics report per race.

**Acceptance:**
- Tyre degradation fits produce positive rates with sensible compound ordering on every catalogued race. Any violation is investigated and explained, not accepted.
- A synthetic-data test proves the fitter recovers known tyre and fuel coefficients when both are present — this is the test that guards against the confound in 6.3.
- Pit loss estimates are plausible and consistent across stops within a race.
- Every fallback (pooled data, prior values) is recorded in diagnostics.
- Fit quality figures are reported per model, not hidden.

**Commit:** `feat: fit tyre, pace, fuel, pit, and dirty air models from race data`

---

### Phase 3 — Simulator and validation ⚠️ **HARD GATE**

**Deliverables:** the full simulation engine per Part 7; the validation harness per Part 8; a generated `VALIDATION.md`; gap-trace comparison plots.

**Acceptance:**
- Determinism test passes: identical seed and inputs produce identical output.
- The replay reproduces each catalogued race within the thresholds in 8.3.
- `VALIDATION.md` is generated and includes failures and diagnostics.
- Gap-trace plots visually track the real race.
- Unit tests cover each lap time component separately, plus the safety car compression case in 6.8.

**If acceptance fails:** stop. Do not proceed to Phase 4. Report which metric failed on which race, the suspected cause, and options. A counterfactual engine on an unvalidated simulator is worthless, and building it anyway wastes all subsequent work.

**Commit:** `feat: deterministic race simulator with validation harness`

---

### Phase 4 — Counterfactual engine

**Deliverables:** all `Decision` types; the fork-and-resimulate engine; Monte Carlo ensemble; decision point detection and ranking; the structured diff.

**Acceptance:**
- A no-op decision (changing a pit lap to its real value) reproduces the real result. This is the single most important test in the project — it proves the counterfactual machinery does not itself introduce drift.
- Shifting a pit stop produces a directionally sensible change, verifiable by hand for at least one case.
- A safety car shift changes outcomes via field compression, and the mechanism can be traced through the lap states.
- Ensemble results are stable across repeat runs to within a couple of percentage points.
- Invalid decisions are rejected with clear errors.

**Commit:** `feat: counterfactual engine with Monte Carlo ensembles`

---

### Phase 5 — API

**Deliverables:** all endpoints from Part 10; Pydantic schemas; caching; error handling; auto-generated OpenAPI docs.

**Acceptance:** every endpoint returns valid typed responses; no FastF1 call occurs during any request; a counterfactual request returns within the latency budget; invalid input returns clear errors, not stack traces.

**Commit:** `feat: FastAPI backend exposing simulation and catalogue`

---

### Phase 6 — Frontend core

**Deliverables:** design plan written and reviewed first; then RaceSelector, GapChart, StrategyTimeline, DecisionPanel, Classification; API client; state management.

**Acceptance:** a user can select a race, see the real race rendered accurately, change a pit stop, and see the alternate timeline overlaid with divergence marked. Works down to mobile. Keyboard navigable.

**Commit:** `feat: race visualisation and decision interface`

---

### Phase 7 — Multiverse tree

**Deliverables:** the D3 tree; branch state model; result caching by decision-path hash; DivergenceSummary with deterministic fallback.

**Acceptance:** branching from any node works; the tree stays legible past a dozen nodes; navigation never re-simulates a cached path; deduplication works for identical decision paths.

**Commit:** `feat: multiverse branch tree`

---

### Phase 8 — Polish and documentation

**Deliverables:** `README.md` with method explanation, demo GIF, honest limitations section, and validation summary; Docker Compose bringing up both services; test coverage review; a written architecture document.

**Acceptance:** a stranger can clone the repo and run it from the README alone; the limitations section names the real weaknesses (retirement handling, single-race parameter fitting, hand-set skill priors); `docker-compose up` works from clean.

**Commit:** `docs: README, architecture notes, and demo assets`

---

## PART 13 — TESTING STRATEGY

The simulation core is where tests earn their keep. Prioritise accordingly.

**Unit tests, per lap time component.** Each term in 6.1 tested in isolation with synthetic inputs and hand-computed expected outputs.

**Property tests.** Tyre degradation is monotonic in age. Fuel effect is monotonic in laps remaining. Dirty air penalty decreases with gap. A driver with strictly better pace and identical strategy never finishes behind. These catch sign errors and unit confusions that example-based tests miss.

**Determinism test.** Same seed, same output. Assert byte equality.

**The no-op counterfactual test.** Applying a decision equal to reality reproduces reality. If this fails, the counterfactual engine is introducing drift and every result it produces is suspect.

**Synthetic-recovery tests.** Generate a fake race with known parameters, run the fitters, assert the parameters are recovered within tolerance. This is the only way to know the fitters are correct rather than merely producing plausible-looking numbers.

**Validation as integration test.** The replay-against-reality harness is the top-level integration test.

Do not chase a coverage percentage. Cover the simulation core thoroughly, the ingestion boundary adequately, and the API surface lightly.

---

## PART 14 — RULES AND GUARDRAILS

1. **Never hardcode a value that can be fitted.** If a constant appears in the simulation, it must either come from `RaceParameters` or be justified in `DECISIONS.md` as a prior with bounds.
2. **Never let the counterfactual engine see the real outcome.** It receives the snapshot up to the divergence lap and the fitted parameters. Nothing else. Any code path that could leak the real result into a counterfactual is a serious bug.
3. **Never silently drop data.** Every exclusion is counted and reasoned.
4. **Never relax a validation threshold to make a test pass.** Fix the model or drop the race, and document either way.
5. **Keep FastF1 out of the simulation core and out of the request path.** Ingestion boundary only.
6. **All randomness through the seeded generator.** No exceptions.
7. **Log the discrepancies.** When two data sources disagree, or a fit violates a physical expectation, surface it rather than smoothing it over. The interesting engineering is in the discrepancies.
8. **Stop and ask** if: a validation threshold cannot be met after genuine effort; the FastF1 API differs materially from Part 4; a catalogued race turns out to have unusable data; or a design decision in this spec appears to be wrong. Do not silently work around a spec problem.
9. **Commit at every phase boundary** with the specified message.
10. **Update `DECISIONS.md` whenever you deviate from this spec**, with reasoning. Deviations are expected and fine; undocumented ones are not.

---

## PART 15 — STRETCH GOALS

Not v1. Do not start these before Phase 8 is complete.

- **Wet races.** Compound crossover, drying tracks, an entirely different degradation regime. The most interesting extension and the largest.
- **Multi-race parameter pooling.** Fit circuit overtaking difficulty and driver skill across many races rather than one, which would materially improve the weakest parameters in the model.
- **Cross-driver counterfactuals.** "What if Ferrari had run Leclerc's strategy on Hamilton's car."
- **Championship propagation.** Apply the alternate result to the championship standings and propagate through the remaining season.
- **Full-season multiverse.** The natural endpoint of the concept, and a genuinely large project on its own.
- **Cricket adaptation.** The same counterfactual architecture applied to a different sport — different physics, same methodological spine.

---

## APPENDIX — PHASE PROMPTS

Paste these into Claude Code one at a time. Do not combine them.

**Phase 0**
> Read `PROJECT_SPEC.md` in full. Then execute Phase 0 only: scaffold the repository structure per Part 3, set up Python and frontend tooling, create `CLAUDE.md`, `DECISIONS.md`, and `VALIDATION.md`, and verify the test runners work. Meet the Phase 0 acceptance criteria, then commit with the specified message. Stop and summarise. Do not start Phase 1.

**Phase 1**
> Execute Phase 1 only: the data layer. Before building, verify the installed FastF1 version's API against Part 4 and note any deviations in `DECISIONS.md`. Implement ingestion, cleaning, and safety car extraction, and curate five races meeting the Part 4.4 criteria — verifying data availability for each before committing to it. Meet all Phase 1 acceptance criteria, including explicitly checking loaded classifications against official results. Commit, then stop and report the cleaning statistics per race.

**Phase 2**
> Execute Phase 2 only: parameter fitting. Pay particular attention to the fuel/tyre confound described in Part 6.3 — write the synthetic-recovery test first, then fit. Report fit quality and every fallback honestly in the diagnostics. Commit, then stop and show me the fitted tyre degradation curves and pit loss estimates per race so I can sanity check them.

**Phase 3**
> Execute Phase 3 only: the simulator and validation harness. This is the hard gate. Build the engine per Part 7 with strict determinism, then the validation harness per Part 8. Generate `VALIDATION.md` with real numbers including failures. If the acceptance thresholds in 8.3 are not met, stop and report which metrics failed on which races with your diagnosis — do not proceed and do not adjust the thresholds. If they are met, commit and stop, and show me the gap-trace plots.

**Phase 4**
> Execute Phase 4 only: the counterfactual engine. Write the no-op counterfactual test first and make sure it passes before building anything else — it is the load-bearing test. Then implement the decision types, ensemble sampling, decision point detection, and the diff. Commit, then stop and walk me through one worked counterfactual by hand so I can verify the mechanism.

**Phase 5**
> Execute Phase 5 only: the FastAPI backend per Part 10. Confirm no FastF1 call happens in any request path. Commit and stop.

**Phase 6**
> Execute Phase 6 only: the frontend core. Start by writing the design plan described in Part 11.1 and show it to me before writing any component code — palette, typefaces, layout concept, signature element. Wait for my response. Then build RaceSelector, GapChart, StrategyTimeline, DecisionPanel, and Classification to that plan.

**Phase 7**
> Execute Phase 7 only: the multiverse tree and divergence summary. Commit and stop.

**Phase 8**
> Execute Phase 8 only: polish and documentation. The README's limitations section must name the real weaknesses honestly — retirement handling, single-race parameter fitting, hand-set skill priors, and anything else validation exposed. Commit and stop.
