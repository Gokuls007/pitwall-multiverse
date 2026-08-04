# DECISIONS.md

Append-only log of design decisions and deviations from `PROJECT_SPEC.md`, with reasoning.
Newest entries at the bottom of each phase section.

---

## Phase 0 — Scaffold

- **2026-08-03 — Project home is `Downloads/f1/`, not `Downloads/guigi/`.** The nominal
  primary working directory (`guigi`) already contains an unrelated portfolio website.
  The empty `f1/` directory was clearly intended for this project. Building there avoids
  polluting an existing project. (Deviation from nothing in the spec; environmental.)

- **2026-08-03 — Runtime is Python 3.14; `uv` is unavailable, using `pip`.** The spec
  allows `pip + requirements.txt` as the fallback. Verified the full stack installs and
  imports on 3.14: FastF1 3.8.3, numpy 2.4.4, scipy 1.17.1, scikit-learn 1.8.0,
  pandas 2.3.3. FastF1 network fetch verified (2021 schedule + Abu Dhabi 2021 session).
  `requires-python` is set to `>=3.11` for portability even though this box runs 3.14.

- **2026-08-03 — FastF1 API spot-check (Part 4).** `fastf1.Cache.enable_cache`,
  `get_event_schedule`, `get_session(year, gp, 'R')`, `session.load(...)`,
  `session.laps`, `session.results`, `session.race_control_messages` all present in
  3.8.3 and behave as Part 4 describes. Any per-column deviations found during Phase 1
  will be logged there.

---

## Phase 1 — Data layer

- **2026-08-03 — TrackStatus codes verified empirically (Part 4.3).** Checked
  Abu Dhabi 2021 lap-by-lap: codes `'16'`/`'671'` at laps 36/37 correspond exactly
  to race control's "VIRTUAL SAFETY CAR DEPLOYED" (L36) / "...ENDING" (L37); codes
  containing `'4'` at laps 53-57 correspond to "SAFETY CAR DEPLOYED" (L53) /
  "SAFETY CAR IN THIS LAP" (L57). Confirms the spec's code table (1 clear, 2
  yellow, 4 SC, 5 red, 6 VSC deployed, 7 VSC ending) exactly. No deviation.

- **2026-08-03 — SC/VSC reconciliation prefers race control on disagreement,
  for both start *and* end lap (Part 4.3).** TrackStatus-derived periods
  consistently start 1-2 laps early and can end late relative to the official
  "DEPLOYED"/"ENDING"/"IN THIS LAP" messages (drivers' per-lap TrackStatus cells
  catch the transition inconsistently depending on where they are on track when
  the flag changes). `ingestion/safety_car.py` derives periods from TrackStatus
  first, then overwrites both boundaries with race control's lap numbers when a
  matching message exists, logging every override. Where reconciling the start
  lap independently of the end lap could invert a single-lap period (observed:
  2018 Australian GP VSC — TrackStatus said lap 25 only, race control said
  "DEPLOYED" at lap 26 with no matching "ENDING" message), the end lap is
  clamped to the (possibly-corrected) start lap and the clamp is logged as a
  discrepancy rather than silently applied.

- **2026-08-03 — `RaceSnapshot.had_rain` is derived from compound usage, not
  FastF1's `Rainfall` weather sensor.** The `Rainfall` boolean in
  `session.weather_data` is noisy: 2019 Monaco shows `Rainfall=True` on 63%
  (87/139) of weather samples despite the entire race being run on slick
  compounds only (verified via `laps['Compound'].value_counts()`) — i.e. it was
  a dry race by every measure that matters to this project (spec 4.4's "dry
  race" catalogue criterion). `had_rain` is instead `True` iff any lap in the
  race used `INTERMEDIATE` or `WET` compound, which is the signal that actually
  affects whether the race enters the wet-race compound-crossover regime the
  spec explicitly defers to a stretch goal (15).

- **2026-08-03 — Legacy (pre-2019) compound naming remapped to the relative
  SOFT/MEDIUM/HARD scheme (deviation from spec 4.1's column table).** 2018
  Australian GP reports compounds as `ULTRASOFT`/`SUPERSOFT`/`SOFT` (FastF1's
  raw passthrough of that era's absolute Pirelli naming), not the post-2019
  relative scheme the domain `Compound` enum models. `ingestion/loader.py`
  (`_remap_legacy_compounds`) detects any non-relative name and remaps the
  compounds actually nominated for that race weekend, ranked softest-to-hardest,
  onto SOFT/MEDIUM/HARD. Logged at INFO with the mapping used. This only
  affects 2018-era races; 2019 onward FastF1 already reports the relative
  names directly.

- **2026-08-03 — The five-race catalogue (`ingestion/catalogue.py`).** Chosen
  for a genuinely contested, well-known strategic decision, dry conditions
  (slicks-only, per the `had_rain` note above), and confirmed 20/20 driver
  coverage in both `laps` and `results`:
  1. **2018 Australian GP** — Ferrari's near-instant pit call for Vettel during
     Alonso's VSC-triggering stoppage, an almost-free stop that won him the race.
  2. **2019 Singapore GP** — Vettel's undercut of his own polesitter teammate
     Leclerc via an earlier pit stop.
  3. **2019 Monaco GP** — Mercedes' tyre-set mix-up forcing Hamilton to defend
     the entire remaining distance on one set of hards.
  4. **2021 British GP** — the lap-1 Verstappen/Hamilton collision, red flag,
     and standing restart.
  5. **2019 Hungarian GP** — Verstappen led on a long final stint; Mercedes
     gambled a second stop for Hamilton on lap 48 for fresher rubber, and
     Hamilton hunted him down to win. Zero SC/VSC periods in this race at
     all — a clean pit-timing-only decision.
  Each entry's ingestion was verified individually: driver counts (20/20),
  finishing order for the top 5 (matches official classification), and DNF
  status/lap for any retirements — see `tests/test_ingestion.py::EXPECTED` and
  the corresponding parametrized tests.

- **2026-08-03 — Abu Dhabi 2021 removed from the catalogue; kept only as a
  hardcoded SC/VSC-extraction test fixture.** Originally catalogued for its
  well-documented late safety car, but on review its actual race outcome
  turned on a *race-control judgement call* (which lapped cars were waved
  through before the one-lap restart) rather than a physics/strategy decision
  the simulator can represent. Validating the simulator against it would be
  uninformative at best (a stewarding call has no tyre/fuel/pace model) and
  misleading at worst (if the pass-probability model happens to reproduce
  Verstappen's move, there's no way to tell whether that's a correct model or
  a lucky sample — spec 6.10's whole point about not trusting a single
  stochastic run). It remains valuable as ingestion validation — the SC (L53-57)
  and VSC (L36-37) extraction is still tested directly against it
  (`test_safety_car_periods_match_documented_abu_dhabi_2021`) — just not as one
  of the five races the counterfactual product is built and scored on.
  Replaced with 2019 Hungarian GP (above), a genuinely strategy-decided race
  with no confounding SC/VSC/red-flag periods at all.

- **2026-08-03 — 2021 British GP also removed from the catalogue; replaced
  with 2021 Spanish GP.** Same defect as Abu Dhabi 2021, caught on review
  before Phase 2: Silverstone 2021 was decided by a lap-1 collision, a red
  flag, and a 10-second stewards' penalty — not a pit-strategy decision. It is
  also *worse* than Abu Dhabi in one respect: a red flag forces a standing
  restart with a free tyre change, and the spec's `TrackStatus`/`SafetyCarPeriod`
  enum lists `RED` (Part 5.1) but Part 6.8 never describes what a red flag does
  to the simulation (no restart/free-tyre-change model exists). Modelling it
  properly is out of scope for this project's Decision types (Part 5.3 has
  nothing for "restart from a red flag"). 2021 Spanish GP replaces it: Verstappen
  led from the front after passing Hamilton at the start, Mercedes reacted with
  an early second stop for Hamilton (lap 42) while Red Bull left Verstappen out
  on ageing tyres until lap 60, and Hamilton used the ~24-lap tyre-life
  advantage to pass Verstappen for the win. Verified: dry (MEDIUM/SOFT only),
  20/20 drivers, a brief unrelated SC (laps 8-10, ~50 laps before the decision
  that actually won the race) that doesn't confound the outcome. Also verified
  Verstappen's stint in **2019 Hungarian GP** directly against raw FastF1 rows
  while investigating this: the 42-lap stint from lap 26-67 is HARD, not
  MEDIUM (the medium stint was laps 1-25, ending at that pit-in) — `_build_stints`'
  per-Stint-column majority vote was correct; no mislabeling, no fix needed.

- **2026-08-03 — `DriverEntry.finish_position` comment corrected; validation
  treatment of classified-but-retired drivers decided now, ahead of Phase 3.**
  The old "None if DNF" comment on `finish_position` (`domain/race.py`) was
  wrong: F1 classifies a retiree who completed >=90% of race distance at the
  position they stopped (e.g. Grosjean, P20, "Water pressure", 2019 Hungary;
  Pérez/Latifi/Giovinazzi/Russell/Räikkönen, Abu Dhabi 2021) — `finish_position`
  is an int alongside a non-"Finished" status in exactly this case, and that's
  correct, not a bug. `None` only means never classified at all (withdrew before
  the race started, e.g. Mazepin's "Illness" at Abu Dhabi 2021).
  **Consequence flagged for Part 8's outcome metrics, decided now rather than
  discovered as an unexplained validation failure at the Phase 3 gate:** a
  classified-but-retired driver's *real* position reflects where they were on
  track when they stopped racing, lap 20 or lap 60, but the simulator (per Part
  7.6/Part 9) will keep simulating them to the chequered flag under whatever
  decisions are in force. Comparing the simulator's lap-70 position for a
  driver who actually stopped at lap 60 against their classified real position
  is not a fair test of the simulator and would silently drag down rank
  correlation / position-match metrics for reasons that have nothing to do with
  model quality. **Decision:** `validation/metrics.py` (Phase 3) must exclude
  classified-but-retired drivers (`DriverEntry.status not in {"Finished"} and
  not status.startswith("+")`, with `finish_position is not None`) from the
  exact-position and within-one-position outcome metrics, reporting them
  separately with their retirement lap and cause — consistent with Part 7.3's
  existing treatment of retirements as exogenous and preserved at the same lap.
  They remain fully modelled in the simulation itself (position, gap, etc. up
  to their retirement lap); they're excluded only from the final-classification
  comparison metrics.

- **2026-08-03 — `DriverEntry` lives in `domain/race.py`, not a separate
  `domain/driver.py` as Part 3's layout diagram shows.** This was already the
  case from Phase 0 scaffolding (not re-decided here); noting it now because
  Phase 1's ingestion code imports it from `race.py`. `DriverParams` (the
  *fitted* per-driver parameters, distinct from `DriverEntry`'s raw
  session data) will still go in `domain/driver.py` when Phase 2 needs it.

- **2026-08-03 — Ingestion diagnostics live in a plain `IngestionReport`
  dataclass in `ingestion/loader.py`, not on `RaceSnapshot` itself.** Keeps
  `RaceSnapshot` a pure ground-truth record (spec 5.1) while still satisfying
  Phase 1's "cleaning report prints usable vs excluded lap counts with reasons"
  acceptance criterion — `load_race()` returns `(RaceSnapshot, IngestionReport)`
  and `scripts/prefetch_races.py` prints the report for every catalogue race.

---

## Phase 2 — Parameter fitting

- **2026-08-03 — Domain placement: `TyreModel`/`DriverParams` in
  `domain/driver.py`; `RaceParameters`/`DirtyAirModel` in `domain/race.py`.**
  Part 3's layout diagram doesn't assign the Part 5.2 dataclasses to specific
  files. `DriverParams` (fitted) joins `driver.py` alongside the file's own
  name; `RaceParameters` joins `race.py` next to `RaceSnapshot` since both are
  keyed by `race_key` and persisted/consumed together. `DirtyAirModel` has no
  shape given in the spec's own code block (5.2 lists it by name only) — see
  the dirty-air entry below for the shape chosen.

- **2026-08-03 — The fuel/tyre confound is separable within a single driver
  only if a compound is *revisited* at a different lap-number offset — not
  merely "more than one stint."** Writing the synthetic recovery test first
  (as the Phase 2 prompt requires) surfaced this before any real data was
  touched: within one contiguous stint, tyre age is an exact affine function
  of lap number (`age = lap_number - stint_start_offset`). A design with one
  age column and one offset dummy per compound has a nontrivial null space —
  a shared shift in the fuel coefficient is exactly cancelled by the same
  shift in every compound's degradation slope plus compensating offsets —
  *regardless of how many stints exist*, as long as no compound repeats. It
  only becomes identifiable when a compound is used in two non-adjacent
  stints at different lap-number offsets (e.g. SOFT-MEDIUM-SOFT), which
  breaks the shared-column algebra. `tests/test_parameters.py`'s positive
  recovery test uses exactly this shape; a same-length "two distinct
  compounds, no repeat" scenario is kept as an explicit negative control.

- **2026-08-03 — Exact-rank checks miss real data's actual failure mode;
  switched to a column-normalized condition number.** `np.linalg.matrix_rank`
  only catches *exact* singularity, but real cleaning (excluded laps, SC/VSC,
  MAD outliers) perturbs the design just enough that it's rarely exactly
  singular even when it's practically unidentifiable — the symptom is a
  regression that "succeeds" but returns wild, unphysical coefficients.
  Verified empirically on 2019 Hungary: 17/20 drivers had condition numbers of
  1e15-1e16 (fuel estimates from -2.7 to +0.18 s/lap) while the 2 drivers who
  genuinely repeated a compound had condition numbers of ~7-10. Columns are
  L2-normalized before taking the condition number (so a 0/1 dummy column
  doesn't get an unfair condition-number penalty against a `lap_number`
  column spanning 1-70) and a driver's fit is trusted only below
  `CONDITION_NUMBER_THRESHOLD = 1e5` — chosen empirically (there's a 12-orders-
  of-magnitude gap between the "genuinely identified" and "not" populations,
  so the exact cutoff isn't sensitive). See `tyre.fit_driver_joint`.

- **2026-08-03 — A driver-level plausibility bound catches what the condition
  number alone doesn't.** Even after the condition-number fix, 2018 Australian
  GP's Leclerc (3-stint MEDIUM-HARD-SOFT, no repeated compound, but HARD had
  only 3 post-cleaning laps) passed the condition-number check yet still
  produced `fuel_coef_s_per_lap=2.13` s/lap — ~40x the plausible range. A
  compound with too few laps to earn its own age term (so it contributes only
  a dummy) can numerically "unstick" the condition number from astronomical
  without giving the regression enough real information to pin the fuel
  effect down. Added a direct sanity bound on the *output*
  (`PLAUSIBLE_FUEL_EFFECT_RANGE_S_PER_LAP = (-0.3, 0.5)` in `fuel.py`;
  `MAX_PLAUSIBLE_SLOPE_S_PER_LAP = 0.5` s/lap in `tyre.py`) — deliberately wide
  so ordinary noise around a true small value still counts, but rejects
  order-of-magnitude confound-leakage artifacts regardless of *why* the
  regression produced them. Same treatment applied to negative degradation
  slopes (spec 6.3's explicit positivity prior): an implausible own-fit slope
  (negative or absurdly large) now falls back to the cross-driver pooled
  slope for that compound, or flat 0.0 if no pooled estimate is sensible
  either — extending the existing sparse-data pooling mechanism (6.3 point 4)
  to also cover "enough samples but a physically-impossible sign/magnitude."
  Result: zero negative or implausible-magnitude degradation slopes across
  all five catalogue races (was up to 21/43 negative before this fix).

- **2026-08-03 — Compound offset must be fit *jointly* with tyre age, not as
  a separate group-mean step.** The first working version of `fit_driver_final`
  computed each compound's offset as a plain group mean of fuel-adjusted lap
  time (a const+dummy-only regression), then fit the age slope afterward on
  the residuals. This silently conflates pace with however much tyre wear a
  compound's *sampled* laps happened to average. Found concretely on 2019
  Hungary's Hamilton: his HARD laps averaged tyre age 9 against MEDIUM's 15,
  making HARD's raw mean pace look faster than MEDIUM's even though HARD is
  the physically slower compound — the group mean was baking in "how worn were
  the tyres on average," not "how fast is this compound at age zero." Fixed by
  including per-compound age columns in the *same* regression that estimates
  the offset dummies (mirroring pass 1's design), so offsets are correctly
  adjusted for whatever age distribution each compound happened to sample.

- **2026-08-03 — Pooled the fuel-effect fit across every driver simultaneously
  (per-driver intercepts, shared compound/age terms, one shared lap-number
  coefficient) as the primary method, keeping the per-driver-median approach
  as a documented fallback.** Motivated by a genuine finding, not a synthetic
  concern: even after the fixes above, real catalogue races showed the
  expected soft-faster-than-medium-faster-than-hard offset ordering violated
  on roughly half of all driver/compound pairs — and on 2021 Spanish GP,
  *all 20/20 drivers* showed SOFT slower than MEDIUM, which is far too
  consistent to be per-driver noise. Traced to: whichever compound a driver
  used *latest* in the race consistently looked fastest, regardless of which
  compound it physically was (confirmed by checking each compound's mean
  lap-of-use per race). Pooling every driver into one regression gives the
  lap-number coefficient far more identifying variation (different drivers
  pit at different laps, so the field mixes tyre ages and compounds at any
  given lap number in a way no single driver's own race offers) — implemented
  in `fuel.fit_pooled_fuel_effect`. This measurably improved the fuel-effect
  estimate's robustness but did **not** fully resolve the ordering violation
  (see next entry) — the pooling fix and the remaining limitation are
  separate findings.

- **2026-08-03 — KNOWN LIMITATION, disclosed loudly rather than silently
  shipped: compound offset ordering is still frequently wrong, root cause
  understood and is a limitation of spec 6.1's own linear fuel-effect term,
  not a bug in this implementation.** After the pooled-fuel-effect fix above,
  the violation rate barely changed — meaning the fuel-effect *magnitude*
  was never the real bottleneck. The actual mechanism: real on-track grip
  ("track evolution," rubber laid down as a race progresses) is front-loaded
  — fast improvement early, then a plateau — not linear in lap number. Spec
  6.1's lap-time composition has no separate term for it; the single linear
  `fuel_effect(laps_remaining)` term is the only lever available, and a linear
  term structurally cannot represent a front-loaded, decaying trend. Since
  compound choice correlates with stint order (a driver's first stint is
  usually SOFT or MEDIUM; whichever compound is used *last* is on average
  raced during the flattest, most-evolved part of the track), the compound
  used latest is systematically under-corrected for the (large, early) grip
  gain it never experienced and so looks artificially fast relative to
  compounds used earlier. This was verified directly: per-race mean
  lap-of-use per compound lines up exactly with which pairwise offset
  comparisons come out backwards (e.g. 2018 Australia: SOFT mean lap 22,
  MEDIUM 27, HARD 42 — and HARD is the one that looks anomalously fast).
  **This is not corrected in Phase 2** — doing so would mean adding a
  nonlinear track-evolution term to the model, which isn't representable in
  `RaceParameters.fuel_effect_s_per_lap`'s spec-defined single-float schema
  (Part 5.2) without a schema change beyond this phase's scope. Instead:
  `fit_all._check_compound_ordering` computes the reference-independent,
  per-driver offset difference for every compound pair, averages it across
  the field, and logs a loud `COMPOUND ORDERING VIOLATION` warning (recorded
  in `fit_diagnostics["compound_ordering_check"]`) whenever the aggregate
  comes out backwards — every catalogue race currently triggers at least one.
  Per spec Part 14 rule 8 ("stop and ask if... a design decision in this spec
  appears to be wrong"): flagging this now rather than papering over it in
  Phase 2, and it should be watched closely in Phase 3 — if green-flag lap
  time MAE or the gap-trace shape comes out wrong specifically around
  compound transitions, this is the first place to look.

- **2026-08-03 — `pit_stop_stationary_s` is a declared prior, not fitted.**
  Spec 6.5 asks for stationary (box) time and pit-lane transit loss reported
  separately, but splitting them requires telemetry (car speed through the
  pit lane) — and ingestion deliberately loads `telemetry=False` for
  performance (spec 4.1). Only their sum ("total pit loss") is identifiable
  from lap-level timing data: measured as (actual in-lap + out-lap time) minus
  (modelled expected pace for those laps), aggregated via median across all
  stops in the race, per circuit-specific `pit_lane_loss_s`. Stationary time
  is set to a fixed, documented prior (2.4s, typical modern F1 box time),
  justified as a prior-with-bounds per Part 14 rule 1 exactly as spec 6.7
  permits for driver skill. Verified plausible and consistent across all five
  races (pit_lane_loss_s ranged ~18-34s, all within the sane per-circuit range).

- **2026-08-03 — Driver `overtake_skill`/`defence_skill` set uniformly to 0.5
  (neutral), not fitted.** Spec 6.7 explicitly permits hand-set priors here
  since they aren't identifiable from a single race, provided they're (a)
  declared, (b) narrowly bounded, (c) sensitivity-checked. A uniform constant
  trivially satisfies all three: it's declared in `pace.py`, it has zero
  variance (as narrow a bound as exists), and a simulation cannot be sensitive
  to a parameter that never varies across drivers. Differentiating real skill
  would need multi-race pooling (Part 15 stretch goal).

- **2026-08-03 — `DirtyAirModel` shape: single-exponential decay.** Spec 5.2
  lists `DirtyAirModel` by name only, without a functional form. Chosen as
  `penalty(gap) = max_penalty_s * exp(-gap / decay_scale_s)` — the simplest
  function satisfying 6.6's required shape (maximal at gap=0, saturating to
  ~0 by a few seconds). Fit via `scipy.optimize.curve_fit`. Fit quality was
  poor-to-negative R² on several races (single-race dirty-air fitting is
  inherently noisy per spec 6.6's own acknowledgement that per-driver
  sensitivity isn't identifiable from one race) — disclosed via
  `fit_diagnostics["dirty_air"]`, with degenerate fits (hit a fitting bound)
  falling back to the spec 6.6 sanity-prior midpoint rather than reporting a
  meaningless negative-R² curve as if it were trustworthy.

- **2026-08-03 — SC/VSC lap-time multipliers fall back to declared priors
  (SC 1.50, VSC 1.35) when a race has no SC or no VSC laps to fit from.**
  Most of this project's catalogue races have few or no safety-car periods
  (2019 Hungary and 2021 Spain have none at all) — computed directly in
  `fit_all._sc_vsc_multipliers` from the ratio of actual lap time to modelled
  expected pace on SC/VSC-flagged laps (excluding in/out laps, whose extra
  time is pit loss, not the SC/VSC effect), median-aggregated; falls back to
  the declared prior with the fallback explicitly flagged in diagnostics when
  no such laps exist.

---

## Phase 2 correction pass — external review caught four real problems

A review of the first Phase 2 pass (above) found that several of the
"fixes" had made the acceptance criteria untestable rather than actually
satisfied, and that one disclosed limitation was mis-diagnosed. Addressed in
this order (each is a distinct problem, not one fix cascading into the next):

- **2026-08-04 — The slope sanity-bound clipping made "positive degradation
  rates" true by construction, not by fitting, and the tests were checking
  the guard instead of the model.** `tyre.fit_driver_final`'s implausible-slope
  handling (negative or >0.5 s/lap → pooled fallback → flat 0.0) is correct
  as a *safety net*, but the Phase 2 integration tests asserted positivity
  only on the *post-clip* value, which can never fail once that fallback
  chain exists — 2018 Australian GP's tyre models had landed at exactly
  0.000 s/lap for both shown compounds (the flat-zero fallback tier), which
  means *zero degradation was ever actually fitted for that race*, and the
  test still passed. A tyre model with zero degradation has no undercut and
  no reason to ever pit, which makes every counterfactual on that race
  meaningless — this is not "the weakest fit in the catalogue," it's an
  unfitted one. Fixed in two parts:
  1. `tyre.fit_driver_final` now returns a `CellProvenance` per driver/compound
     recording which tier the final value came from (`own_fit`,
     `pooled_implausible`, `pooled_insufficient_samples`, `flat_zero`) *and*
     the driver's raw own-fit slope even when it was later overridden.
     `fit_all.py` aggregates this into `fit_diagnostics["tyre_cell_provenance"]`.
  2. `tests/test_parameters.py` replaced the post-clip-only positivity check
     with two tests that use this provenance data:
     `test_fallback_fraction_is_bounded` (no more than 60% of driver/compound
     cells may need any fallback tier) and
     `test_raw_own_fit_slopes_are_usually_positive` (of cells where a driver's
     own regression actually ran, the *raw, pre-clip* slope must be
     non-negative at least half the time — see the Singapore entry below for
     why the bar is 50%, not higher). Both would have caught Australia's zero
     model immediately (100% of its shown cells were `flat_zero`).

- **2026-08-04 — Dirty air was unfit on every catalogued race, and the report
  had disclosed the finding it had a good explanation for while going quiet
  on the one it didn't.** Negative R² on multiple races (worse than
  predicting the mean) and `max_penalty_s` pinned at a curve-fit bound on
  others were both symptoms of the same conflation the first pass didn't
  name: spec 6.6 (dirty air — aero wake from a car close ahead, whether or
  not it's racing you) and spec 6.9 (traffic — losing time stuck behind a car
  "not racing for position," e.g. a lapped backmarker) are explicitly
  separate mechanisms in the spec's own lap-time composition (6.1), but
  `dirty_air.fit_dirty_air` was regressing lap-time excess against
  `gap_to_ahead_s` using *every* usable close-following lap, regardless of
  whether the car ahead was a genuine on-pace rival or a backmarker about to
  be lapped. On a street circuit (Monaco, Singapore) where the whole field is
  bunched together for most of the race, most "close gap" observations are
  the backmarker case — one regressor, two effects, and the fitted
  "penalty" ends up representing whichever effect dominates the sample, not
  a clean dirty-air estimate. Fixed with a heuristic that doesn't require a
  full traffic model: a lap only counts as a dirty-air observation if the
  car ahead ran *similar* pace that lap
  (`TRAFFIC_DISPARITY_THRESHOLD_S = 1.5`s) — a backmarker about to be lapped
  is, almost definitionally, running much slower than the car catching it.
  Also added the same rigor already applied to tyre slopes: a converged fit
  with R² below `MIN_ACCEPTABLE_R_SQUARED = 0.05`, or with either curve_fit
  parameter pinned within 1% of its bound (checked at *both* bounds — the
  first version of this check only tested the lower bound and missed 2021
  Spain's `max_penalty_s` pinned at its upper bound of 5.0), is now treated
  as degenerate and replaced with the declared spec 6.6 prior rather than
  reported as a real fit. **Result, disclosed rather than hidden: dirty air
  fell back to the prior on all five catalogue races** — it is not
  identifiable from any single race in this catalogue with lap-level
  (non-telemetry) timing data using this method. This is consistent with
  spec 6.6's own acknowledgement that per-driver dirty-air sensitivity isn't
  identifiable from one race, extended here to the race-level penalty curve
  itself. A full fix would need either pooling across multiple races (Part
  15 territory) or telemetry-derived following-distance data, both out of
  scope for Phase 2.

- **2026-08-04 — Compound ordering fix corrected: the binding constraint is
  collinearity across the whole field, not an under-fit time trend, so no
  time-trend term (linear, log, or otherwise) can fix it — replaced the
  "fit freely and log the violation" approach with a declared monotonic
  prior.** The first pass's diagnosis (linear `fuel_effect` failing to
  capture front-loaded track evolution) was directionally right but pointed
  at a fix that cannot work: nearly every driver in the field runs softs (or
  the softest available compound) early and hards (or the hardest) late, so
  compound identity and race phase are collinear *across the entire field*,
  not just within one driver's stints. No monotonic-in-lap-number term, no
  matter how it's shaped, can separate "this compound is inherently faster"
  from "this compound was used earlier in the race" when the two are the same
  partition of the data. This is confirmed by the pooled cross-driver
  fuel-effect fit (previous entry, `fuel.fit_pooled_fuel_effect`): it gave
  every driver's trend term far more identifying variation and barely moved
  the fuel-effect number at all, which is exactly what you'd expect from a
  collinearity rather than an underestimated trend. Per Part 14 rule 1: some
  things aren't identifiable from one race's data and the honest move is a
  declared, bounded prior — the same class of problem as the fuel/tyre
  confound, and as driver skill in spec 6.7. Adjacent-compound single-lap
  pace deltas are one of the few quantities reasonably well known independent
  of any single race (consecutive dry compounds are a few tenths of a second
  apart in general Pirelli/historical experience). Implemented as **weighted
  isotonic regression** (`fit_all._enforce_monotonic_compound_offsets`,
  `sklearn.isotonic.IsotonicRegression`, weights = each compound's own
  `n_observations`) over each driver's fitted offsets, ranked by
  `enums.SLICK_ORDER` — the least-squares-optimal monotonic sequence given
  that driver's own (possibly backwards) fitted offsets, so it moves the
  numbers as little as possible while guaranteeing the correct order, rather
  than substituting an external value. `MAX_ADJACENT_COMPOUND_GAP_S = 1.2`s is
  a generous backstop cap on top (rarely triggered). `_check_compound_ordering`
  is now a post-correction verification (should always report zero
  violations; if it doesn't, that's a bug in the projection, not the
  underlying fit) rather than the loud-but-uncorrected warning it was before.
  Result: 12-15 of ~20 drivers needed correction per race (recorded in
  `fit_diagnostics["compound_ordering_prior"]`), and post-correction ordering
  is now correct on every catalogue race.

- **2026-08-04 — Don't chase the pit-loss numbers directly; they're a symptom
  of pace-model bias, not an independent bug.** Pit loss is defined (spec
  6.5) relative to *modelled expected pace* — any bias in the tyre/offset
  model mechanically inflates or deflates it, since the "excess" the pit-loss
  fitter measures is excess over whatever the (possibly biased) model
  expects. No separate pit-loss fix was made; the numbers moved on their own
  once the compound-offset bias above was corrected (e.g. Australia's
  pit_lane_loss_s dropped from a suspiciously high 34.6s pre-correction —
  though Australia was dropped from the catalogue anyway, see next entry).

- **2026-08-04 — 2018 Australian GP dropped from the catalogue; replaced with
  2019 Mexican GP.** Essentially nothing about Australia's fitted parameters
  actually came from Australia: its fuel effect fell back to the documented
  prior, its tyre degradation slopes landed on the flat-zero fallback tier
  for the cells shown in the original report, its dirty air was unfit (as it
  now is for every race, but Australia had no other signal to fall back on
  either), and its pit loss inherited the resulting pace-model bias. Root
  cause, found by screening candidates before picking a replacement (a check
  skipped the first time): Australia 2018 has two drivers with fewer than 6
  usable laps (ERI, SIR — struggling backmarker teams that race) requiring
  teammate fallback, plus heavy SC/VSC/inaccurate-lap exclusion (67+15+62
  laps out of 940), leaving too little clean data for most cells to fit
  independently. Per spec 8.3, which explicitly permits excluding a race with
  documentation rather than degrading the standard: replaced with 2019
  Mexican GP, screened *before* committing this time — minimum 39 usable laps
  per driver (zero teammate-fallback cases needed), only a 3-lap VSC, dry.
  Genuinely strategy-decided: Leclerc took pole but slid to P4 while Vettel
  (front row alongside him) finished P2, the two Ferraris having run
  different strategies (Vettel one-stopped, Leclerc pitted twice) — a live
  question of whether Leclerc's second stop cost more track position than
  the tyre offset was worth.
