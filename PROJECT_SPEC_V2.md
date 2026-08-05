# PROJECT SPEC v2 — Pit Wall Multiverse

### Remaining work: interface, interaction, and finish

**Status:** Extends `PROJECT_SPEC.md`. That document remains authoritative for the backend, the physics models, and the validation regime. This one covers what's left, and it is almost entirely frontend.

**Numbering:** continues the original scheme. The original Phase 6 (frontend core) is complete; this document adds 6.1–6.5, then Phase 7 (the tree) and Phase 8 (finish) as originally specified.

---

## PART 0 — HOW TO USE THIS

Same protocol as v1. One phase at a time. Acceptance criteria met and committed before the next begins. Append to `DECISIONS.md`, keep `CLAUDE.md` current.

### Rules carried forward from v1

Non-negotiable, and every one of them exists because it was violated at least once during v1:

1. **Read, don't derive.** If a value exists in the fixture or the domain objects, display it. Never recompute it in the component. A tyre age displayed as 25 when the model used 28 shipped and passed every test, because it was recomputed from stint length instead of read.
2. **Never hardcode a value that can be fitted.** Applies to interaction constants too. If a threshold governs behaviour, it either comes from data or is declared in `DECISIONS.md` with bounds.
3. **Every generated artifact carries `paramFingerprint`**, and `test_fixture.py` verifies all of them. Numbers derived under one set of parameters and quoted under another was the single most recurrent failure of v1 — six instances.
4. **Name the statistic whenever a pair exists.** Mean or median, drivers or driver-stint-cells. Never quote one half of a pair unqualified.
5. **Open it in a real browser and look at it before claiming it works.** Four separate faults in v1 passed every programmatic check and were only found by looking: the counterfactual rendering off-screen, pit-stop swings owning the y-scale, the real line hidden beneath the alternate, and a correct-but-unreadable distribution column. Programmatic checks verify properties you thought to name. Looking finds the ones you didn't.
6. **Retractions stay in place** in `DECISIONS.md`, not edited out. The record of what was wrong and in what order is the project's most valuable artifact.
7. **Stop and ask** if a phase's acceptance criteria can't be met, or if this spec appears wrong. Do not work around a spec problem silently.

### Design discipline

The visual identity is defined in the v1 design plan and is already implemented: paper stock, monospaced numerals, hairline rules, one accent that means exactly one thing, one caution colour that means exactly one thing.

**Ambition in this phase goes into interaction and information density, never decoration.** No gradients, no glassmorphism, no shadows, no 3D, no dark mode, no additional accent colours. The distinctiveness of this interface is entirely a function of restraint; every decorative addition moves it toward the generic motorsport dashboard it was designed against.

If a change makes the interface denser, more direct, or more honest about uncertainty, it belongs. If it makes it flashier, it doesn't.

---

## PART 1 — CURRENT STATE

**Complete and merged:** Phases 0–3 (ingestion, parameter fitting, simulator, validation harness with the §8.3.1 revision), plus Phase 4's core (fork-and-resimulate, `ChangePitLap`, `AddPitStop`, Monte Carlo ensembles with fitted AR(1) noise) and Phase 6's core components (GapChart in two modes, StrategyTimeline on a shared lap axis, DecisionPanel, Classification with per-driver distributions).

**Deliberately deferred, with reasons on record:** the Phase 5 API (frontend runs on precomputed real simulations through the same functions the API would call), `ChangeCompound` (prior-dominated — 61% of adjacent-compound offset gaps sit at the fitted floor), `RemovePitStop` (extrapolates past the longest observed stint in the catalogue), `ShiftSafetyCar`/`RemoveSafetyCar` (SC periods exist only in the Spanish GP, at a long drift horizon, and Monaco, which is excluded from the gate aggregate), and `counterfactual/diff.py`.

**The known limitation that shapes everything here:** the tool can say whether a decision brings a car into contention — that rests on validated pace and tyre models. It cannot reliably say whether the finishing order changes — that rests on `overtake_difficulty` fitted from one race's sample and a driver-skill prior that was never fitted. The interface must claim the first and not the second.

---

## PART 2 — EXPLICITLY OUT OF SCOPE

Do not build these, and do not drift into them:

- The Phase 5 API. The deferral is deliberate and documented.
- Any additional `Decision` type. The two implemented are sufficient and the others are either prior-dominated or extrapolate past the evidence.
- Any use of third-party code or data. Everything needed is already in the repository. In particular, external processed lap-data CSVs are not to be introduced: the project's ingestion pipeline is the source of truth and has accumulated bug fixes (compound rank-shift, missing-compound raise, damage detection) that other pipelines will not have.
- Additional races beyond the existing five-race catalogue. Adding a race requires the full disqualifier screen, parameter fitting, and validation loop. Not in this phase.

---

## PHASE 6.1 — CHART CORRECTNESS

**Goal:** two faults visible in the current build, fixed before anything is layered on top.

### Deliverables

**1. Comparison mode plots the delta between timelines, not gap-to-leader.**

Gap-to-leader carries no information when the subject is the leader. In the current build the driver led for the entire displayed window, so both traces sit flat on the axis boundary and the range is dominated by his real pit-stop dip — leaving the actual comparison occupying a small fraction of the plot. This is the third distinct instance of the y-scale swallowing the signal.

In comparison mode, plot `alternate − real` centred on zero, with a zero rule. Positive is time lost, negative is time gained, and the y-extent floor (`MIN_Y_EXTENT_S`) still applies so a small delta can't render as a chasm. Field mode continues to plot gap-to-leader, which is correct there.

**2. Clamp the uncertainty band's lower bound.**

The pace band currently renders above the zero line in places. Whatever the variable, the band must not extend into physically impossible territory — a car cannot be ahead of the leader. Clamp at the variable's valid bound.

### Acceptance

- Comparison mode's y-axis range is set by the delta, not by pit-stop swings; a sub-second difference is legible.
- The band never crosses its variable's valid bound, tested with a synthetic case that would previously have breached it.
- Field mode unchanged.
- Existing GapChart tests still pass; the five named properties from v1 still hold.

**Commit:** `fix: plot timeline delta in comparison mode, clamp band bounds`

---

## PHASE 6.2 — PRECOMPUTE EXPANSION

**Goal:** every driver on every catalogued race, without shipping a large payload.

This is the data layer for all subsequent phases. Nothing after this works without it.

### Deliverables

**Generation script** (`scripts/build_fixtures.py`) producing, for each race in the catalogue and each driver with at least one real pit stop, every candidate pit lap the existing valid-range discovery accepts, at the current seed count.

**Store only what renders.** Per candidate:
- the median gap trace (or delta trace, per 6.1)
- the per-driver classification distribution
- the extrapolation-laps figure from the generalised helper
- the lap indices where the stuck-behind clamp fired

Not full `LapState` arrays. That distinction is the difference between a payload that loads and one that doesn't.

**One file per race per driver**, loaded on demand when a driver is selected. Never ship the whole set.

**`paramFingerprint` in every file**, with `test_fixture.py` extended to verify all of them rather than one.

**Monaco included, labelled.** It's fitted; it's excluded from the gate aggregate. Surface it with a visible note that its parameters are the weakest in the catalogue and why — 30% tyre-cell fallback fraction, highest unclamped signed error. A visible caveat is more interesting than a missing option.

### Sizing — verify, don't assume

At the measured per-simulation cost, the full expansion is on the order of tens of thousands of simulations per race and a few minutes of compute; all five races should be well under half an hour. Per-driver files should land in the low hundreds of kilobytes. **Measure these before committing to the approach.** If per-driver files come out much larger than expected, the stored-fields list is wrong — revisit what's actually being rendered rather than compressing harder.

### Acceptance

- Every race and every eligible driver generates without error.
- Total generation time and per-file sizes recorded in `DECISIONS.md`.
- `test_fixture.py` verifies the fingerprint on every generated file and fails if any is stale.
- Loading a driver fetches exactly one file.
- No file contains full per-lap state for every seed.

**Commit:** `feat: precompute all drivers across catalogue with lazy per-driver loading`

---

## PHASE 6.3 — DRAG THE DECISION

**Goal:** retire the slider. The pit stop itself becomes the control.

This is the highest-value change in this document. It converts "configure a parameter" into "move the decision," which is what the product is about — and because the chart and timeline share a lap axis, dragging left is literally moving the stop earlier in time.

### Deliverables

Pointer-based drag on the pit-stop tick in the stint bar:

- `pointerdown` on the tick → `setPointerCapture`, so the drag survives the pointer leaving the element
- `pointermove` → map `clientX` through the **existing shared lap axis scale**, snap to integer lap, clamp to the discovered valid range
- On each lap change, update in one pass: stint bar reflow, caution hatch extent, chart paths, preview sentence, classification distribution
- `pointerup` → commit

**Key candidates in a `Map` by lap number.** `pointermove` fires at pointer frequency and every event is a lookup plus a redraw; a linear search over the candidate list will feel sticky.

**No animation during drag.** Instant redraw only. Path-drawing transitions on every move read as broken. Reserve transitions for commit, and disable them entirely under `prefers-reduced-motion`.

**Keyboard, on the tick:** `tabindex="0"`, `role="slider"`, `aria-valuemin`/`max`/`now`, and `aria-valuetext` carrying the preview sentence so a screen reader gets the teaching line, not just a number. Arrows step ±1 lap, Shift+arrow ±5, Home/End to range bounds.

**Remove the slider** once the tick is fully operable by both pointer and keyboard. Keep RESET TO REAL.

**Two details that carry the epistemic frame:**

- A persistent faint marker at the **real** lap, visible throughout the drag. That's the zero-extrapolation point, and always being able to see where you departed from the evidence is the frame made physical. A notch, not a snap — magnetic snapping will feel like the control resisting.
- `cursor: ew-resize` on hover, over the existing 44px invisible hit area, so the tick is discoverable as draggable.

### Acceptance

- Drag works with mouse, touch, and pen; capture survives leaving the element and releasing outside the window.
- Fully operable by keyboard, with `aria-valuetext` reading as the preview sentence.
- Redraw keeps up during continuous drag — no visible lag on a full-range sweep.
- Real-lap marker visible at all times during drag.
- Slider removed; RESET TO REAL retained.
- **Verified by dragging it in a real browser**, not only by synthetic pointer events.

**Commit:** `feat: direct-manipulation pit stop drag, replacing the slider`

---

## PHASE 6.4 — LAP SCRUBBING

**Goal:** a playhead across the lap axis, with the classification reordering live.

The pit wall is a timing screen where the order shifts under you. This makes the interface that, and it needs no new data — per-lap positions for every seed already exist.

### Deliverables

- A playhead draggable along the shared lap axis, with a play/pause control
- Both timelines draw in progressively as it advances
- The Classification panel reorders in real time, showing the order at that lap rather than the finish
- Playhead position is keyboard-operable on the same conventions as 6.3
- Under `prefers-reduced-motion`, playback is disabled and the playhead is drag-only

**Position at a lap is read from stored state, never interpolated.** Interpolating positions between laps would invent an ordering the model never produced — the same failure class as the derived tyre age.

### Acceptance

- Scrubbing the full race redraws smoothly; playback runs at a readable rate
- Classification order at any lap matches the stored state for that lap exactly
- Reduced-motion path works
- **Looked at in a browser during playback**, not only asserted

**Commit:** `feat: lap playhead with live classification reordering`

---

## PHASE 6.5 — SMALL MULTIPLES OF THE DECISION SPACE

**Goal:** the whole space of alternate histories at a glance.

### Deliverables

A dense row of thumbnail delta charts, one per candidate pit lap, each narrow enough that the full candidate set fits without scrolling on desktop. Each shaded by extrapolation depth in the caution colour. The real lap marked. Click to load as the main comparison; the currently-selected candidate emphasised.

This makes a finding from v1 self-evident rather than captioned: the extrapolation curve is **V-shaped with its minimum at reality**, because shifting a stop lengthens one stint while shortening its neighbour, so every counterfactual departs from the evidence somewhere. Seen as a row of shaded thumbnails, the V is a shape rather than a claim.

### Acceptance

- All candidates for a driver render legibly at thumbnail scale
- Extrapolation shading is read from stored values, not recomputed
- Click-to-load works; selection state is visible
- Row degrades to horizontal scroll on mobile with a visible affordance
- The V-shape is visually apparent without a caption explaining it

**Commit:** `feat: small-multiples view of the candidate decision space`

---

## PHASE 7 — THE MULTIVERSE TREE

**Goal:** the signature element. Branch from any node; accumulate a visible tree of alternate histories from one race.

Rendered as a critical apparatus — received text plus variant readings — not as an org chart.

### Deliverables

- Branch tree state modelled with an explicit reducer, not scattered component state. The interaction pattern (branch, navigate, compare arbitrary nodes) becomes unmanageable otherwise.
- Node identity is a hash of the ordered decision list, so identical decision paths deduplicate.
- Each node caches its result; navigation never re-fetches a path already loaded.
- Hairline connectors, no boxes. Nodes are small text blocks: decision label in the label face, winner in the numeral face, delta from parent.
- Current node lifted off the wash with a heavier rule.
- A generous but finite depth limit.

**Test node legibility with dummy data at depth 3 or more before committing to the layout.** Horizontal spread is the failure mode, and the requirement is legibility past a dozen nodes.

**Branching depth is bounded by what's precomputed.** A second decision on top of a first requires a simulation that may not exist in the fixture. Either precompute a bounded set of depth-2 paths for one or two illustrative cases, or restrict branching to the precomputed set and say so in the UI. Do not silently offer branches that produce nothing.

### Acceptance

- Branching from any node works within the precomputed set
- Legible past a dozen nodes; depth-3 dummy layout verified visually
- Navigation never re-fetches a cached path
- Identical decision paths deduplicate
- Unavailable branches are visibly unavailable, not silently inert

**Commit:** `feat: multiverse branch tree`

---

## PHASE 8 — FINISH

**Goal:** presentable, reproducible, published.

### Deliverables

**Demo capture at the top of the README, above the prose.** The drag is the demo: from the real lap to a substantially earlier one, showing the caution hatch growing from nothing and the extrapolation count rising. Starting at the real lap matters — shading appearing *from zero* is what shows it measuring distance from evidence rather than decorating.

**README updates:** the interaction model, the expanded coverage, and the branching limitation if Phase 7 restricts it. The claim/non-claim distinction, the validation numbers with statistics named, the fitted-vs-prior table, and the V-shape limitation are already in place — verify they still match the build.

**Docker Compose** bringing the frontend up from clean.

**Push.** No remote is currently configured. Verify the default branch contains everything before pushing — during v1 the default branch sat stale with a placeholder README while sixteen commits of work were stranded on a working branch, which would have made every documented number unverifiable to anyone who looked.

### Acceptance

- A stranger can clone and run it from the README alone
- GIF is the first thing in the README
- `docker-compose up` works from clean
- Default branch contains all work; README claims match the branch
- Test suites green

**Commit:** `docs: demo capture, README updates, and deployment`

---

## APPENDIX — PHASE PROMPTS

One at a time.

**6.1**
> Read `PROJECT_SPEC_V2.md`. Execute Phase 6.1 only: plot the timeline delta in comparison mode instead of gap-to-leader, and clamp the uncertainty band's lower bound. Meet the acceptance criteria, commit, stop. Then open it in a browser and tell me whether the comparison is actually legible now.

**6.2**
> Execute Phase 6.2 only: the precompute expansion. Measure generation time and per-file sizes before committing to the storage format — if per-driver files are much larger than the estimate, revisit the stored-fields list rather than compressing. Extend `test_fixture.py` to fingerprint every file. Commit, then report the sizes and timings.

**6.3**
> Execute Phase 6.3 only: replace the slider with a direct drag on the pit-stop tick. Key candidates in a Map, no animation during drag, full keyboard operability with `aria-valuetext` carrying the preview sentence, persistent real-lap marker. Then drag it yourself in a real browser and tell me how it feels — not whether the events fire.

**6.4**
> Execute Phase 6.4 only: the lap playhead with live classification reordering. Positions are read from stored state, never interpolated. Watch it play in a browser before reporting.

**6.5**
> Execute Phase 6.5 only: small multiples of the candidate decision space. Check whether the V-shape is apparent without a caption — if it isn't, the encoding is wrong.

**7**
> Execute Phase 7 only: the multiverse tree. Test legibility with dummy data at depth 3+ before committing to a layout. Be explicit about what branching depth the precomputed fixture actually supports, and make unavailable branches visibly unavailable.

**8**
> Execute Phase 8 only: finish. Verify the default branch contains everything and that the README's claims match what's on it before anything is pushed.

---
---

# PROJECT SPEC v2.1 — INTEGRATING StratSim

**Status:** amends this document. v1 remains authoritative for the backend, physics and
validation regime; everything in v2 above stands. This part adds a second track drawn from
the `StratSim-main` codebase, and states precisely what is taken, what is rejected, and why.

## PART 3 — WHAT StratSim IS, AND WHAT IT IS FOR HERE

`StratSim-main` is an independent F1 strategy simulator: Streamlit UI, gradient-boosted
lap-time models (XGBoost / LightGBM / CatBoost) tracked with MLflow, a multi-agent
architecture (tyre manager, tyre temperature, weather, grip, gap effects, vehicle
dynamics), its own FastF1 collector and preprocessor, and ~208 MB of processed 2023–2024
lap data (68,847 rows x 98 columns).

Architecturally it is the opposite of this project: ML-inferred where this is
parameter-fitted, agent-orchestrated where this is a pure function, Streamlit where this is
hand-built SVG. It is therefore **not** a codebase to merge. It is a source of **scope and
capability** that this project lacks, and the integration takes those while keeping this
project's ingestion, fitting and validation as the sole source of truth.

### 3.1 Hard constraints on the integration

These are not preferences.

1. **No StratSim code is copied into this repository.** The zip contains no LICENSE file,
   which under default copyright means all rights reserved. This repository is MIT and
   public. Concepts and approaches are not copyrightable; specific source is. Everything
   below is therefore a **reimplementation against this project's own domain objects**, not
   a port. If ownership of StratSim is confirmed, direct porting becomes permissible and
   this constraint can be revisited — until then it holds.
2. **No StratSim CSVs are introduced.** Part 2 of v2 already forbids this and the reason
   stands: `data/processed/seasons_2023_2024_data*.csv` come from a different preprocessor
   that will not carry this pipeline's accumulated fixes (compound rank-shift, the
   missing-compound raise, damaged-car pace-step detection). Any race added is ingested
   through `pitwall.ingestion` or not at all.
3. **Rule 3 of v2 extends to every new model.** Anything added here carries a
   `paramFingerprint` and appears in the fitted-vs-prior table. A model that is a declared
   prior says so in the table, in `DECISIONS.md`, and in the README.
4. **No new model may silently change existing published numbers.** Every addition below is
   introduced behind an explicit switch, defaulting off, with a measured before/after
   recorded. `VALIDATION.md`'s figures are cited in the README; they do not move without an
   entry saying by how much and why.

### 3.2 Rejected from StratSim, with reasons

Recorded so the decisions are not silently revisited.

- **`gap_effects_agent`'s dirty-air model — rejected.** It hardcodes banded zones
  (0–1.0 s → 1.5% time loss, 1.0–2.0 s → 1.0%, and so on). This project *fitted* that curve
  from 4,508 pooled cross-race laps with clustered bootstrap confidence intervals
  (`max_penalty_s` 1.290 [0.846, 1.850], `decay_scale_s` 0.864 [0.564, 1.494]) after
  diagnosing why per-race fits failed. Adopting hardcoded bands would be a regression
  against v2 Rule 2 and would discard the most involved result of v1.
- **The ML lap-time models — rejected.** The project's position is no ML in the simulation
  path, for a reason central to it: a fitted parameter can be reported as fitted-or-prior
  with a confidence interval; a gradient-boosted ensemble cannot. The honest
  fitted-vs-prior table is this project's most distinguishing artifact and a black-box
  predictor would end it.
- **The agent/orchestrator architecture — rejected.** `simulation/` is a pure function of
  `(RaceSnapshot, RaceParameters, seed)`. Determinism and the exact no-op guarantee depend
  on that; stateful message-passing agents would break both.
- **Streamlit — rejected.** The frontend exists, is designed, and is the subject of v2.

### 3.3 Taken from StratSim

Three capabilities, in ascending order of risk.

**A. Catalogue expansion to 2023–2024 (lowest risk, highest value).** StratSim's real
contribution is *scope*: this project validates against five races from 2019/2021, StratSim
covers two full modern seasons. Take the **race selection**, ingest via
`pitwall.ingestion`, run the existing disqualifier screen, fit, validate. This is the mix
that costs nothing epistemically — StratSim's ambition with this project's rigour.

**B. Weather and tyre-temperature models (medium risk).** This project models neither.
Note the ordering problem: the current catalogue is entirely dry by construction (the
screen excludes wet races), so a weather model has nothing to act on until (A) admits a
wet race. Sequence accordingly.

**C. Per-driver characteristics (highest risk).**
`data/categories/driver_characteristics.json` rates 22 drivers 0.0–1.5 on aggression,
consistency, risk tolerance, tyre management, wet-weather skill, qualifying pace, race
pace, overtaking and defending.

**These are hand-authored judgments, not fitted values.** The accompanying `.md` documents
the scale but no methodology, and `VER aggression 1.15` is an opinion. This matters more
than it appears:

- This project's headline limitation is that it cannot claim finishing-order changes,
  *because* `overtake_skill`/`defence_skill` are unfitted uniform 0.5 priors.
- Substituting per-driver hand-authored numbers would move outputs — including the win
  fraction the README discusses — on the basis of someone's opinion.
- It would therefore be **dishonest to present this as resolving that limitation.** It
  replaces an uninformative prior with an informative but unvalidated one. That may produce
  better-looking results; better-looking is not the standard.

Adopt only as a **declared prior, defaulting off**, with a measured ablation showing how
much the win fraction moves when enabled. The comparison is the deliverable, not the
feature.

---

## PHASE 9 — CATALOGUE EXPANSION VIA OWN INGESTION

**Goal:** more races, same rigour. Take StratSim's coverage, not its data.

### Deliverables

- Candidate 2023–2024 races selected using StratSim's coverage as the shortlist, screened
  with `scripts/screen_race.py` **disqualifier-first** (penalties, red flags, DSQ, early
  front-runner retirements) exactly as the current five were.
- Ingested through `pitwall.ingestion.loader` only. `data/processed/*.csv` is never read.
- Fitted with `fit_catalogue_with_pooled_dirty_air`. Note the pooled dirty-air fit is
  cross-race: **adding races changes it**, so the existing five races' parameters move.
  Legitimate (more data), but per 3.1.4 the before/after is measured and recorded, and
  `VALIDATION.md` regenerated.
- 2023–2024 use a different compound-allocation era; verify `_parse_compound` handles them
  and **raises** rather than defaulting on anything unrecognised, as v1 established.

### Acceptance

- Every added race passes the disqualifier screen, with the output recorded.
- No file under `data/processed/` from the zip is read by any code path.
- The pooled refit's effect on the original five races is measured and recorded in
  `DECISIONS.md`; `VALIDATION.md` regenerated.
- The full gate is re-run and reported honestly, including any race that now fails that
  previously passed.
- `paramFingerprint` regenerated for every fixture; `test_fixture.py` green.

**Commit:** `feat: expand catalogue to 2023-24 races via own ingestion pipeline`

---

## PHASE 10 — WEATHER AND THERMAL MODELS

**Goal:** two capabilities this project lacks, reimplemented and honestly labelled.
Depends on Phase 9 admitting at least one non-dry race, or it has nothing to act on.

### Deliverables

- `parameters/weather.py` and a thermal term in the tyre model, reimplemented from
  concepts, no StratSim source.
- Each fitted where the data supports it, declared as a bounded prior where it does not,
  with the same degenerate-fit rejection already applied to dirty air (minimum R²,
  bound-pinning detection).
- Both in the fitted-vs-prior table and behind a default-off switch per 3.1.4.

### Acceptance

- Every new constant is either fitted with a recorded diagnostic or declared with bounds.
- Enabling them changes no existing published number until the ablation is recorded.
- Green-flag MAE measured with and without, both statistics named.

**Commit:** `feat: weather and tyre-thermal models with fitted-vs-prior accounting`

---

## PHASE 11 — DRIVER CHARACTERISTICS AS A DECLARED PRIOR

**Goal:** make the effect of an opinionated prior measurable rather than invisible.

### Deliverables

- `overtake_skill`/`defence_skill` optionally sourced from a reimplemented characteristics
  table, mapped onto the existing 0–1 skill scale with the mapping documented.
- **Default off.** Uniform 0.5 remains shipped until an ablation justifies otherwise.
- An ablation: win fraction and within-one-position rate for the demo counterfactual and
  for the full gate, characteristics on versus off, both statistics named.
- README and fitted-vs-prior table state plainly that these are hand-authored ratings, not
  fitted values, and that enabling them does **not** lift the stated inability to claim
  finishing-order changes.

### Acceptance

- Ablation numbers in `DECISIONS.md` and reflected in the README.
- Default remains uniform 0.5 unless the ablation gives a documented reason to change it.
- No claim anywhere that driver skill is now fitted.

**Commit:** `feat: optional driver-characteristics prior with measured ablation`

---

## SEQUENCING

The frontend track (6.1 → 6.5 → 7 → 8) and this backend track are independent, but the
frontend is nearly finished and produces the demo; the backend track is open-ended and
changes published numbers.

**Recommended order:** 6.1 → 6.2 → 6.3 → 9 → 6.4 → 6.5 → 10 → 11 → 7 → 8.

Rationale: 6.1–6.3 complete the interaction model and the drag demo. Phase 9 lands before
6.4/6.5 because those render whatever the catalogue contains, and doing it after means
regenerating fixtures twice. Phases 10–11 are additive and default-off, so they cannot
block the finish. Phase 8 stays last so the README describes what actually shipped.

If time runs short, **Phase 9 alone is the valuable half of this integration** — it
multiplies coverage without touching a single epistemic claim. 10 and 11 are interesting;
9 is the one that makes the project bigger without making it weaker.

### Appendix — added phase prompts

**9**
> Execute Phase 9 only: expand the catalogue to 2023–24 races using StratSim's coverage as
> the shortlist but this project's own ingestion. Disqualifier-screen first. Measure and
> record what the pooled dirty-air refit does to the original five races, regenerate
> VALIDATION.md, and report the gate outcome honestly including any regression.

**10**
> Execute Phase 10 only: weather and tyre-thermal models, reimplemented. Every constant
> fitted with a diagnostic or declared with bounds. Default off, ablation recorded.

**11**
> Execute Phase 11 only: driver characteristics as a declared prior, default off, with the
> ablation as the deliverable. Do not claim driver skill is now fitted.
