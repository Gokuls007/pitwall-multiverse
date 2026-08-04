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

- **Phase 3 (simulator + validation, hard gate): BUILT, NOT PASSED, NOT
  COMMITTED.** `simulation/` (rng, lap_time, overtake, safety_car, pit,
  position, engine — replay mode only) and `validation/` (replay, metrics,
  report) exist in the working tree and pass their own test suite (32 tests:
  per-component, property, determinism, SC-compression). Run `python
  backend/scripts/run_validation.py` to regenerate `VALIDATION.md` and
  `data/validation_plots/*.png`.

  **The first validation pass was itself measured wrong** — an earlier
  version of this note attributed the failure to dirty air plus a "noise
  floor." Both explanations were retracted after external review:
  `compose_lap_time_s` was sampling noise into the value scored against
  reality (mean-zero noise only inflates MAE, never reflects model
  accuracy), and that same noise, accumulated over a full race, produced a
  random-walk field spread independent of model quality. A worse-than-
  random-chance `strategy_direction_match_rate` (9-15% vs. ~33% chance) was
  also filed as noise when it was actually a sign bug: pit stops were going
  through the proximity-gated probabilistic overtake model, which almost
  never lets a car that just lost 20+ seconds fall behind anyone. Fixed with
  `position.reorder_pitting_drivers` (mechanical reinsertion by cumulative
  time, bypassing the probabilistic model for pit stops specifically). Two
  more bugs surfaced while re-measuring cleanly: `compress_field_under_sc`
  could produce inverted (decreasing) cumulative time when track position
  legitimately disagreed with raw time order, and separately snapped the
  *entire* field to the following distance on the first lap of SC instead of
  closing large gaps gradually over the SC period, as real telemetry shows.
  Both fixed (floor at zero; a declared `MAX_GAP_CLOSURE_PER_LAP_S` rate
  cap). Full diagnosis and retraction: DECISIONS.md's Phase 3 section,
  "Retraction" entry.

  **Corrected results, all four fixes applied: still zero of five races
  pass.** Winner correctness improved from 2/5 to 4/5 (only 2019 Monaco
  still wrong) and strategy-direction match rate from 9-15% to 80-94%
  (confirming that was the pit-reorder bug, not noise) — but green-flag
  lap-time MAE now fails *every* race even measured honestly with noise
  off, and dirty air, re-ablated on now-uncorrupted gaps, accounts for a
  genuine ~0.3-0.4s/lap but **even entirely zeroed doesn't get any race
  under threshold** (best case, 2019 Mexican: 40% of drivers under 0.5s,
  vs. the 50% spec 8.3 requires). 2019 Monaco additionally has an
  unresolved, distinct issue (a real small fitted-pace gap that Monaco's
  near-zero overtaking difficulty never lets resolve under green flag, then
  gets revealed all at once by a mass pit stop under SC) — flagged, not
  fixed at the time.

  **Root-cause decomposition, then a rejected fix.** A signed-error test
  (mean `sim - real` per driver/compound cell, grouped by whether
  `_enforce_monotonic_compound_offsets` had altered that cell) refuted the
  leading hypothesis for the systematic error (an unrecentered offset
  correction) — altered and unaltered cells showed statistically
  indistinguishable bias once a single-lap outlier cell was excluded. But
  isolating each race's most-often-in-clean-air driver (minimal dirty-air
  exposure) showed signed error of just 0.13-0.33s in 4/5 races, against a
  0.7-1.0s field-wide average — strong evidence the pace model itself
  (base pace, tyre degradation, fuel, compound offsets) is close to
  correct, and the dirty-air prior specifically is the dominant remaining
  bias. A "stuck-behind" constraint was implemented (a car close behind
  another that doesn't complete a pass can't record a faster lap time than
  the car blocking it — spec 6.9's never-built "cost for laps unable to
  pass"), plus a blue-flag rule (a lapped car yields near-deterministically
  rather than contesting position, `position.py`), and dirty air's penalty
  was removed from the simulation entirely (superseded, not just ablated —
  `DirtyAirModel` fitting still runs and is stored for diagnostics, but
  `compose_lap_time_s` no longer applies it).

  **That combination does not pass, and was initially worse than doing
  nothing** — traced to conflating two different physical questions under
  one constant: `CLOSE_PROXIMITY_GAP_S` (is a pass plausible) was also
  being used to decide "is this car physically unable to close further,"
  forcing lap-time *equality* across the whole 1.5s range instead of only
  at genuine wheel-to-wheel range. Reformulated as `MIN_FOLLOWING_GAP_S`
  (currently 0.3s, a placeholder): a failed pass floors the resulting gap
  rather than equalising lap times, so a car closes at its own pace above
  the floor and the clamp no longer propagates a whole train down to its
  slowest link. Real, modest improvement; still well above the dirty-air-
  off-no-clamp baseline.

  **Dirty air successfully refit from pooled cross-race residuals — the
  earlier "confound" was arithmetic, not a population effect.**
  `expected_clean_pace_s`'s `base_pace_s` is an OLS intercept fit on laps
  mostly *with* a car ahead, so it represents average-traffic pace, not
  zero-traffic pace; every per-race `fit_dirty_air` attempt was fitting an
  exponential decaying to *zero* onto residuals whose true large-gap
  asymptote is -0.47s, which no parameter choice can do — that's the
  Phase 2 mystery, resolved. Verified the mean-residual-near-zero check
  first (-0.253s across the full 5,752-lap fitting sample — real, not
  ~0, but about half the -0.474s asymptote, consistent with a genuine
  proximity effect on top of a real post-hoc-correction-driven shift).
  Checked whether dirty air could instead go inside the joint per-driver
  regression: condition numbers were already elevated (71-145, vs. this
  project's own ~10 precedent from the fuel fit) and got up to 115% worse
  with a gap term added — rejected per the pre-agreed fallback rule.
  Implemented the simpler option instead: `dirty_air.
  fit_pooled_dirty_air_across_races` (asymptote-corrected pooled curve fit,
  R²=0.088, real signal) plus `fit_all.fit_catalogue_with_pooled_dirty_air`
  (two-pass: fit every race independently, pool, refit every race with the
  correction). `MIN_FOLLOWING_GAP_S` stays a 0.3s placeholder — the
  apparent floor signature in the tightest bucket (n=9) doesn't survive a
  sample-size check. Pit loss shifted larger (~+0.95s per race) as a
  direct, checked consequence of the base-pace correction — moving further
  from, not toward, the separate, still-open "biased-high pit loss" concern.

  **Signed error was reported without MAE last pass — same mistake, mirror
  image, caught and corrected.** Also: the reported clamp-firing rate
  (13-46%) rested on a stale exact-tie heuristic built for the *previous*
  (equality) clamp — the floor clamp rarely produces one. Fixed the
  instrumentation first: `resolve_positions` now takes a `clamped_this_lap`
  set (mutated in place, same pattern as the other per-lap state) and
  `LapState.stuck_behind_clamped` records it directly. True clamp rates:
  17-34% (Hungarian/Mexican/Australian/Spanish), 50.2% (Monaco).

  **The direct answer to "would this pass if the clamp were fixed"**:
  per-driver MAE on *unclamped* laps only, drivers under 0.5s — 50.0%,
  55.0%, 50.0%, 47.4% for the four non-Monaco races (Monaco: 20.0%). Close
  to the "majority" line the gate requires, not clearly over it and not far
  under either — a real, undecided result, not evidence either way on its
  own.

  **Second finding: 87-96% of clamped laps have a simulated car-ahead that
  isn't the real car-ahead.** The clamp is very likely doing exactly what
  it should given the (already-wrong) car the simulation has adjacent —
  the clamped-lap error (1.4-2.2s MAE) is substantially a symptom of the
  simulation's track order having already diverged from reality by that
  point in the race, not primarily evidence the clamp's trigger condition
  itself is broken. Materially changes what "fixing the clamp" would even
  mean; not resolved this session.

  **Pit loss corrected further**: `expected_clean_pace_s` gained optional
  dirty-air parameters (default off, so `dirty_air.py`'s own fitting is
  unaffected); `fit_pit_loss`'s second pass now folds the pooled dirty-air
  penalty into each in/out-lap's expected pace using its real gap, so
  traffic during a stop no longer gets counted as pit loss. Came back down
  partway toward the pre-correction values, as expected (e.g. Hungarian
  21.44s -> 20.96s).

  **Re-checked the offset-recentring hypothesis a third time (CellProvenance
  split of the -0.253s mean residual) — still doesn't hold**: altered
  cells -0.262s, unaltered -0.229s, statistically indistinguishable. The
  "average-traffic intercept" mechanism fully accounts for the gap on its
  own.

  **Dirty-air curve now has clustered CIs** (98 race x driver clusters, 500
  bootstrap resamples): `max_penalty_s` 1.290 [0.846, 1.850],
  `decay_scale_s` 0.864 [0.564, 1.494] — real, identified signal, though
  `max_penalty_s` is the value at gap=0, which `MIN_FOLLOWING_GAP_S=0.3`
  means the simulator never actually exercises.

  **2019 Monaco dropped from the Part 8.3 pass/fail aggregate** (still
  fitted, simulated, and fully reported — `validation.report.
  EXCLUDED_FROM_GATE_AGGREGATE`, reason stated inline): worst on every
  metric measured (MAE, unclamped signed error, drivers under threshold,
  winner) and the catalogue's worst tyre-cell fallback fraction (30%, ~2x
  every other race).

  **Two claims from this same status section retracted on external
  review**: "the clamp's trigger condition is the whole remaining gap" —
  false, unclamped MAE (0.53-0.57s) stays over threshold even with a
  perfect clamp; and two races' 50.0%-drivers-under-threshold were being
  read as borderline passes when a tie isn't a majority (`green_flag_mae_ok`
  is now `>`, not `>=`).

  **The real finding: the gate itself was measuring the wrong thing.**
  Extended the car-ahead mismatch check from clamped-only laps to *every*
  green-flag lap: the closed-loop replay's simulated car-ahead differs
  from the real car-ahead on **65-85% of all green-flag laps**, not just
  the ~90% of clamped ones. Since dirty air applies using the simulated
  gap, every closed-loop MAE number so far was scored against a largely
  fictional gap sequence — a self-reinforcing loop (divergence -> wrong
  neighbour -> wrong penalty/clamp -> more divergence), and a measurement
  problem in the gate, not only a modelling problem in the simulator.

  **Fix: `validation.metrics.open_loop_green_flag_lap_time_accuracy`** —
  predicts each real lap's time from the fitted model using its *real*
  gap-to-car-ahead, no replay loop, no position tracking, deterministic.
  This is what spec 8.3's threshold is actually about (8.2 calls exactly
  this the fairest test of the pace model in isolation); the closed-loop
  number is kept as a race-shape diagnostic under its own label.

  **Result, in-sample: the pace model passes.** Open-loop green-flag MAE
  clears 0.5s for the majority of drivers in all four non-Monaco races
  (0.47-0.58s, 55-60% of drivers under threshold, vs. 0.80-0.90s/15-35%
  closed-loop). 2019 Mexican passes every threshold — at 55.0% (11/20), a
  narrow margin, not a comfortable one. Hungarian and Spanish fail on
  exactly one criterion each (within-one-position); Australian fails on
  within-one-position and rank correlation.

  **But that number is in-sample, and held-out is substantially worse —
  checked directly, not assumed.** Leave-one-stint-out cross-validation
  (refit each driver's pace/tyre model excluding one stint, predict that
  stint with the same pooled dirty-air model, same open-loop methodology):
  held-out MAE 0.992s mean / 0.658s median vs. 0.596s in-sample on the same
  population — and only **16.0% (4/25)** of driver-race cells under 0.5s
  held-out, against 55-60% in-sample. Every counterfactual answer is
  extrapolation (a tyre-age/lap-number combination that never occurred),
  so held-out accuracy, not in-sample accuracy, is the number that matters
  for Phase 4 readiness. This materially revises the "pace model passes"
  conclusion: it fits its training laps well; whether it generalizes to
  what a counterfactual would ask about is a different, currently
  unfavourable, question.

  Also corrected: the previous entry's side-by-side open-loop/closed-loop
  comparison mixed a mean (open-loop, single deterministic pass) with a
  median (closed-loop, across the 10-seed ensemble) as if they were the
  same statistic — `VALIDATION.md` now labels each explicitly. And the
  neighbour-identity mismatch (65-85%) was checked against gap
  *magnitude*, not just identity: median `|sim gap - real gap|` is
  2.1-3.6s, only 10-19% of laps within 0.5s of the real gap — confirms the
  position-tracking problem is large in magnitude too, not softened by
  "maybe the gaps are roughly right and only the labels swapped."

  Dirty-air CIs re-reported at the gaps the simulator actually exercises
  (not the gap=0 extrapolation past the 0.3s floor): 0.912s [0.669, 1.186]
  at 0.3s, down to 0.127s [0.049, 0.268] at 2.0s — real signal throughout
  the operating range, unaffected by the in-sample/held-out question above
  (this is about the curve's own confidence interval, not forward
  prediction of lap times). The -0.253 mean residual is fully explained by
  the asymptote plus the sample's mean dirty-air exposure; the offset-
  recentring hypothesis is retired after a third failed test.

  **The held-out result above was itself retracted after review found it
  confounded — corrected version is materially better news.** Leave-one-
  stint-out removes a whole stint; Phase 2 already proved tyre age and lap
  number are perfectly collinear *within* a stint, so most drivers'
  reduced fits were rank-deficient or near-singular for a reason that has
  nothing to do with extrapolation quality. Corrected experiment
  (`scripts/held_out_check.py`): truncate the last 4 laps of a stint —
  every stint stays present, matching how "pitted a few laps later"
  actually stresses the fit — and predict the truncated tail. Result: 0.640s
  in-sample vs. 0.796s held-out mean (0.453s vs. 0.540s median), 47.4%
  (91/192) of truncated-stint cells under 0.5s. A real but modest
  degradation, not the collapse the confounded version showed — and
  confirmed not to be the same confound (held-out MAE doesn't improve with
  more remaining stints; condition numbers are all in a moderate,
  non-degenerate 56-111 range).

  **Gap-drift-vs-laps-elapsed, quantified rather than assumed**: median
  `|sim gap - real gap|` fits `0.835 * sqrt(laps elapsed)` reasonably well
  (R²=0.725). Since a counterfactual forks from real state at the decision
  lap and only diverges forward, this reads directly as a horizon: ~1.9s
  drift at 5 laps remaining, ~3.7s at 20, ~5.9s at 50 — well short of the
  6-9s+ a full 60-70-lap from-lap-1 replay accumulates. Late-race decisions
  face materially less drift than the full-replay gate measures.

  **Revised position on proceeding**: both corrections point the same
  direction — real, held-out-validated (not just in-sample) pace accuracy
  with a modest, quantified degradation, and a position-drift problem
  that's bounded and horizon-quantifiable rather than an open-ended
  full-race failure. Still the human running the project's call, not this
  session's, but it now supports a scoped v1 (e.g. late-race decisions
  where drift is small, reporting Monte Carlo ensemble outcomes as
  distributions per spec 6.10 rather than single points) as a legitimate
  place to build from, more than the immediately preceding entry did.

  All 141 tests pass. Full numbers, every rejected alternative and why,
  and the bucketed residual/CI/held-out tables: DECISIONS.md's Phase 3 section, most
  recent entries. Per the spec's explicit instruction, this is **not
  committed and Phase 4 has not started.**
