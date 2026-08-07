# Pit Wall Multiverse

**A counterfactual Formula 1 race simulator.** Take a real race, change one strategic
decision, and simulate the rest of the race forward from that moment.

The distinguishing property is not the simulation — it's that **the simulation is
measurable**. Every counterfactual forks from a race whose real outcome is known, so "how
much should you trust this?" has a numeric answer rather than a vibe. Most of the
engineering here went into establishing those numbers honestly, and into finding the places
where earlier versions of them were quietly wrong.

> Not a race-outcome predictor, a telemetry dashboard, or a sim-racing game. It answers the
> question fans actually argue about: *what if they'd pitted earlier?*

---

## What the tool claims — and what it doesn't

This distinction is load-bearing, and it comes from measurement rather than modesty.

**It claims:** *does this decision bring the car into contention?* That rests on the pace,
tyre, fuel and dirty-air models, which have held-out validation (below).

**It does not claim:** *does this decision change the finishing order?* Once a
counterfactual brings a car up behind another, the gap pins at the fitted minimum following
distance and the outcome is decided by `overtake_difficulty` — a noisy single-race fit — and
by driver skill, which is a uniform prior that was never fitted at all. Win fractions are
reported, but as a footnote to the closing trajectory, not as the headline.

There's an uncomfortable corollary the project reports rather than hides: simulated
overtakes are driven by the tail of the pace-noise distribution, and that noise model
(`AR1_PHI = 0.622`) is unexplained persistence absorbing whatever regressors the pace model
is missing. So **a better pace model would produce fewer simulated overtakes.** The win
fraction partly measures model ignorance.

---

## The core methodological claim: anchoring

A counterfactual does not re-simulate from lap 1. It:

1. copies every lap before the decision **verbatim from reality**,
2. initialises simulation state at the fork from **real** positions, gaps and tyre ages,
3. simulates forward only from there.

So divergence is attributable to the decision rather than to accumulated simulation drift.
This matters because a full from-lap-1 replay accumulates several seconds of positional
error by the finish — an inherent property of any closed loop, not a fixable bug (see
limitations).

---

## Validation

Full numbers: [`VALIDATION.md`](VALIDATION.md). Regenerate with
`python backend/scripts/run_validation.py`.

Thresholds were revised **once**, with justification, under the spec's own clause
permitting revision after real numbers are known ([`PROJECT_SPEC.md`](PROJECT_SPEC.md)
§8.3.1). The revision came *after* fixing four real bugs, not instead of fixing them.
Winner and podium thresholds were met as originally written and are unchanged.

| Metric | Original | Revised | Why |
|---|---|---|---|
| Green-flag lap-time MAE | < 0.5s | **< 0.6s** | Sized to the measured in-sample/held-out gap |
| Drivers within one position | ≥ 75% | **≥ 55%** | Sized to measured full-replay drift — a harsher test than any counterfactual faces |
| Rank correlation | > 0.9 | **> 0.85** | Same |
| Winner reproduced | every race | unchanged | Met |
| Podium | ≤ 1 swap | unchanged | Met |

### Headline: held-out, not in-sample

In-sample accuracy measures fit quality on the laps used to fit the model. Every
counterfactual is *forward prediction*, so the number that matters is held-out. Measured by
truncating the last 4 laps of a stint, fitting on everything else, and predicting the
truncated tail (192 stint-cells):

| | In-sample | **Held-out** |
|---|---|---|
| Mean MAE | 0.640s | **0.796s** |
| Median MAE | 0.453s | **0.540s** |
| Cells under 0.5s | — | **47.4%** (91/192) |

A real but modest degradation. Reproduce: `python backend/scripts/held_out_check.py`.

**Stated without the flattering half:** the held-out median (0.540s) clears the revised
0.6s figure, but only **47.4% of stint-cells fall under the original 0.5s — not a
majority**, so the held-out result does *not* clear §8.3 as originally written. Quoting
"0.54s" alone would be picking the better of a pair; the mean is 0.796s. Note also that
these are different units from the gate's own criterion, which is per *driver* rather than
per driver-stint cell — so the two are directionally comparable, not interchangeable.

An earlier version of this check used leave-one-stint-out and reported a catastrophic 16%.
That result was **confounded and is retracted**: removing a whole stint collides with this
project's own identifiability finding (below), producing near-singular fits for reasons
unrelated to extrapolation quality.

### Per-race (4 gated races)

| Race | Winner | Within 1 pos. | Rank corr. | Open-loop MAE (in-sample) |
|---|---|---|---|---|
| 2019 Hungarian | HAM ✓ (90%) | 65.8% | 0.944 | 0.537s |
| 2019 Mexican | HAM ✓ (100%) | 83.3% | 0.948 | 0.493s |
| 2019 Australian | BOT ✓ (100%) | 58.8% | 0.897 | 0.580s |
| 2021 Spanish | HAM ✓ (80%) | 63.2% | 0.955 | 0.469s |

**2019 Monaco is excluded from the pass/fail aggregate** (still fitted, simulated and fully
reported). It is the outlier on every metric measured and has roughly double the
catalogue's next-worst tyre-cell fallback fraction — 30% of its driver/compound cells fall
back to pooled or flat estimates, consistent with street circuits confounding traffic and
pace. Documented under §8.3's own provision for excluding a race with a stated reason
rather than relaxing a threshold.

---

## Limitations, stated plainly

**Position tracking drifts, and it's structural.** Per-lap pace error accumulates as a
random walk, so simulated-versus-real gap divergence grows with the square root of laps
since the fork — measured at **≈ 0.835 · √(laps elapsed)** seconds (R² = 0.725). Read as a
horizon:

| Laps remaining at the decision | Expected gap drift |
|---|---|
| 5 | ≈ 1.9s |
| 20 | ≈ 3.7s |
| 50 | ≈ 5.9s |

So **late-race counterfactuals are meaningfully more trustworthy than early-race ones**.
This cannot be fixed with better position logic — only with better per-lap accuracy, or by
re-anchoring, which is exactly what forking from real state does.

A related consequence: on a full from-lap-1 replay, the simulated car directly ahead
differs from the real one on 65–85% of green-flag laps. That's why lap-time accuracy is
reported *open-loop* (against real gaps) as the pace-model metric, with the closed-loop
number kept separately as a race-shape diagnostic.

**Every counterfactual leaves the evidence somewhere.** Observed tyre ages are
definitionally what actually happened, so reality is the zero-extrapolation point *by
construction*. Shifting a pit stop lengthens one stint and shortens another, so there is
**no safe direction** — moving Verstappen's 2019 Hungary lap-67 stop to lap 50 takes the
following soft stint to **tyre age 23** against the 6 he actually reached on that compound;
moving it to lap 68 instead takes the hard stint to age 43, past the 42 he ran. (Age, not
stint length: the stint is 20 laps. Writing "23 laps" here would be the same conflation as
finding 5, in the README describing finding 5.)
The UI shows this curve live rather than blocking choices past the data, because the most
interesting question in that race *is* 17 laps beyond the evidence.

**Held-up time is not pace.** When a car is pinned behind one it can't pass, the model adds
real, permanent time. That's tracked in its own field so a confidence band on a gap reports
pace uncertainty only, rather than silently mixing in "how much traffic did this car hit."

**Overtakes are resolved in a single pass, and the field can only shuffle one place per
lap.** `resolve_positions` walks adjacent pairs left to right once per lap; a pair that has
just swapped is not re-checked, so a car cannot gain two places in a lap even when it is
comfortably quicker than both. That is a deliberate simplification matching spec 7.1's "for
each pair in close proximity" as one resolution pass rather than a fixed-point iteration —
but it biases the simulator against fast cars recovering through a midfield, which is
exactly the situation an early-pit counterfactual creates. Read the traffic component of a
result with that in mind.

**A concrete miss, since a general caveat is cheaper than an example.** In the Hungary
counterfactual, Bottas really finished P8 — the model puts him at P10 in 83% of its 60
runs. It is not uncertain about him; it is *confidently wrong*. The Classification panel
shows the full spread per driver rather than one alternate order specifically so that
distinction is visible: a tight distribution in the wrong place looks different from a
wide one, and only the first tells you the model has a systematic problem with that car.
If every panel showed a single order this would have rendered as a flat "P10" and read as
an answer.

---

## Fitted vs. declared prior

The project's claim is "parameters fitted from real race data." The honest version of that
claim is narrower than it sounds, so here it is in full.

| Component | Status |
|---|---|
| `fuel_effect_s_per_lap` | **Fitted** (pooled cross-driver) — distinguishable from the prior by cluster-robust CI on only 1 of 5 races |
| `base_pace_s` | **Fitted** for most drivers; teammate/field-median fallback for a few per race |
| `linear_deg_s_per_lap` (tyre wear) | **Fitted** for 66–95% of driver/compound cells; pooled or flat fallback for the rest, all tracked in `tyre_cell_provenance` |
| `base_offset_s` separation | **Prior-dominated** — ~61% of adjacent-compound gaps sit at exactly the declared 0.15s floor (66/109 when first measured; 57/92 on a re-check after the degradation refit — the two passes enumerate pairs slightly differently, the conclusion does not move) |
| `pit_lane_loss_s` | **Fitted** from real in/out-lap timing (downstream of the pace model, so it inherits its bias) |
| `dirty_air` | **Fitted** from pooled cross-race residuals: max penalty 1.290s [0.846, 1.850], decay 0.864s [0.564, 1.494] (clustered bootstrap) |
| `overtake_difficulty` | **Fitted**, acknowledged noisy single-race estimate |
| `AR1_PHI` (noise autocorrelation) | **Fitted** 0.622 from 5,373 consecutive-lap residual pairs — but autocorrelation absorbs missing regressors, so treat as an upper bound |
| `MIN_FOLLOWING_GAP_S` | **Fitted** 0.580s (5th percentile of 5,435 observed real gaps) |
| `sc` / `vsc` multipliers | **Fitted** only on races that had such a period; prior otherwise |
| `pit_stop_stationary_s` | **Prior** (2.4s) — not separable from transit loss without telemetry |
| `overtake_skill` / `defence_skill` | **Prior** (uniform 0.5), every driver — spec permits this |
| `MAX_GAP_CLOSURE_PER_LAP_S` | **Prior** (15s/lap), calibrated against one race's telemetry, unverified against a second |
| `BLUE_FLAG_YIELD_PROBABILITY` | **Prior** (0.9) — grounded in the rule existing, not in measured compliance timing |

---

## Findings

The parts worth reading. Each was found by measuring something rather than assuming it, and
several corrected an earlier conclusion in this same repo.

**1. Fuel effect and tyre degradation are unidentifiable without a compound revisit.**
Within a single stint, tyre age and lap number advance together — perfectly collinear. The
two effects separate only when a driver returns to the same compound at a *different* race
offset, and only one or two drivers per race actually do. This is a property of the sport's
structure, not of data quality, and it constrains everything downstream. It's also why the
leave-one-stint-out validation was confounded: removing a stint destroys the very variation
that makes the fit identifiable.

**2. A rank check misses the near-singular matrices real data produces.** Checking
`matrix_rank` passes on designs that are numerically hopeless. Switching to condition number
caught fits that were technically full-rank and practically meaningless — and later made the
decision to *reject* putting dirty air inside the per-driver regression (condition numbers
71–145, worsening up to 115% with the extra term) an evidenced call rather than a guess.

**3. A validation metric was measuring noise the simulator injected itself.** Green-flag MAE
was computed on a *sampled* lap time — the model's prediction plus a random draw from its own
residual distribution. Mean-zero noise cannot improve MAE, only inflate it. The reported
figure was scoring a random realisation of the prediction rather than the prediction, and
`pace_std_s` was being cited as an irreducible noise floor when it is the model's own
unexplained error.

**4. A sign error was hiding as a weak model.** The strategy-direction metric scored 9–15%
across every race. Random guessing scores ~33%. Consistently *below chance* isn't weakness,
it's inversion — pit stops were resolved through the proximity-gated overtake model, which
almost never lets a car that just lost 20 seconds in the pit lane fall behind anyone, because
the resulting gap is far outside the range where a pass is even attempted. Fixed by
reinserting pitting drivers mechanically by cumulative time. The metric went to 80–94% — and
then became nearly tautological, which is itself worth knowing.

**5. A displayed tyre age was fabricated by derivation.** The frontend computed stint tyre age
as `endLap - startLap + 1`. Plausible, wrong: a stint can begin on used tyres, so
Verstappen's opening stint (laps 1–25, ages 4–28) displayed as 25. Every test passed — both
quantities were integers of similar magnitude. It was caught by knowing the car started on
used rubber. The fix wasn't the arithmetic, it was **reading the value the pipeline already
had instead of re-deriving it**, plus a guard asserting at least one stint's real age
disagrees with its lap count, so the derivation cannot return silently.

That last pattern — a value quietly re-derived instead of read — recurred three times here.
The response was structural: fixtures carry a **parameter fingerprint**, and a test fails if
it drifts from live code. A win fraction of "25%" was once quoted in prose after the
parameter it depended on had already been refitted; that class of error is now impossible
rather than merely discouraged.

**6. Most pit calls were roughly right — and that is the tool's actual answer.** Across
2019 Hungary's 1,580 candidate decisions, exactly **two of twenty drivers** had an
alternative worth more than a couple of seconds that the model can also defend (Bottas,
−16.8s from stopping on lap 8 rather than 5; Russell, −9.8s from lap 15 rather than 16).
Eighteen sit between −1.1s and +3.0s. The arguments fans have about pit timing are, on this
evidence, mostly arguments about noise. That is a more interesting result than any single
counterfactual, and it is the kind of claim only a tool that enumerates the whole decision
space can make.

**7. Only 3% of the decision space is inside the model's own evidence.** 53 of those 1,580
candidates keep every stint within a tyre age the driver actually reached. The rest
extrapolate, and the interface says so per candidate rather than in a footnote. The *width*
of the defensible region is itself a per-driver property: Hamilton has 14 defensible
candidates at his lap-48 stop, Verstappen has **none at either of his** — because Hamilton
ran a compound in more than one stint and Verstappen ran each exactly once, so every one of
his stints ended at its own observed maximum by construction. Any shift in any direction
leaves the evidence immediately.

That is the same compound-revisit property as finding 1. **The drivers whose tyre models are
best identified are exactly the drivers whose counterfactuals are defensible** — one
structural fact of the sport, showing up at both ends of the pipeline.

**8. A degradation rate of exactly zero was reachable, and it drove the demo.** The
per-driver fallback chain ended in a `flat_zero` tier. Verstappen's SOFT cell at Hungary hit
it: 2 observations, slope 0.0000 s/lap, r² = nan. The model believed his softs never wore,
so they stayed ~1.5 s/lap faster than his hards at any age, and moving his lap-67 stop to
lap 40 "gained" 52 seconds.

Two faults, not one. The pool that should have caught it was gated on a driver-level
identifiability flag that only 2 of 20 drivers pass, so SOFT never entered it. And the pool
was built from *fuel-confounded* pass-1 slopes — five drivers' SOFT estimates came out
between −0.63 and −1.90 s/lap and were discarded by the positivity filter as noisy when they
were merely confounded. Refit with the race-level fuel effect held fixed, **34 of 34 cells at
Hungary are physically plausible**. Fixing it removed **36 seconds of pure artifact** from
that headline number.

Every existing guard passed while this was true, because they were all aggregates: the
fallback-fraction ceiling sat at 40% while Hungary passed at 19% with one catastrophic cell.
**An aggregate cannot catch a local catastrophe.** The guard is now per cell, and zero is
unreachable as a value *and* as a provenance.

**9. The uncertainty band was mostly measuring its own draw order.** A counterfactual and its
baseline were paired by seed, but once a decision changes a lap time the two runs consume the
generator out of step, so every subsequent draw differs. Keying every random quantity on
`(seed, driver, lap, channel)` instead — common random numbers — made the p10–p90 band on the
demo candidate **17.9s wide → 1.29s**, on an effect of 0.3s. It had been reporting noise about
noise. A stronger invariant came free: the no-op equivalence is now asserted byte-for-byte
*with noise on*.

**10. Position 0 is not a position.** FastF1 writes `0` for a car's retirement lap, where it
stops part-way round with no classified place. Plotted as a position it sorts to the *front*,
so the lap-scrubber would have shown a retired car leading the race. Three cases across the
catalogue, caught by a range assertion on generated files rather than by anything visual.

### Design notes worth stealing

**Never let an integer be a y coordinate.** Finishing position looks like the obvious y axis
for a tree of alternate outcomes. It is an integer over ~20 values, so branches that finish
in the same place land on exactly the same line — 13 nodes collapsed onto 4 rows, paths and
labels overlapping. Net effect in seconds is continuous, so exact collisions are rare and
*near*-collisions are meaningful: two branches drawn close together really did cost the same.

**The y-scale swallowed the signal four separate times**, in four different ways: an
auto-scaled floor-pinned comparison, a pit-lane transient setting the range, gap-to-leader
being floored at zero for a race leader, and finally a tree axis set by its own outlier.
Each was found by opening the page, never by a test. The fixes are all in
[`DECISIONS.md`](DECISIONS.md) — robust MAD range with overflow markers, a delta on
cumulative time rather than gap, and a symmetric-log tree axis.

**Two bugs produced plausible output with an inverted conclusion**, which is the class worth
fearing. A candidate count of `14` clipped by an SVG's right edge rendered as `1`, making
every driver look equally hopeless — the precise opposite of what that panel exists to show.
And a tree that branched on the candidate *nearest* reality, rather than the best defensible
one, drew nineteen sub-second branches piled on the zero rule and said nothing at all. Neither
would fail a test; both were caught by comparing what was drawn against what was in the file.

---

## Architecture

The one architectural rule: **FastF1 is imported in exactly one place**
(`backend/pitwall/ingestion/`), and never during an HTTP request. Everything downstream
operates on plain immutable domain objects, so the simulator is pure, deterministic and
testable without network or cache.

```
FastF1 ─▶ ingestion ─▶ RaceSnapshot ─▶ parameters (fitted) ─▶ simulation (pure)
                                                                    │
                                        ┌───────────────────────────┴───────────┐
                                        ▼                                       ▼
                              validation (replay reality)        counterfactual (fork + re-sim)
                                        │                                       │
                                        ▼                                       ▼
                                  VALIDATION.md                          api ─▶ frontend
```

Determinism is enforced: every stochastic path threads an explicit seeded
`numpy.random.Generator`. No global random state anywhere.

**GapChart and StrategyTimeline share one lap axis by construction** — a single scroll
container and one x-scale, not two synchronised scrollers — because the layout's analytical
payoff is dropping your eye from "the gap did this at lap 50" to "he was on 23-lap-old softs
at lap 50."

## Stack

Python + NumPy simulation core · scikit-learn / scipy for parameter fitting · FastAPI +
Pydantic v2 backend · React 18 + Vite + TypeScript + Tailwind frontend · D3 · pytest +
vitest. No LLM in the simulation path; no deep learning.

---

## Running it

**With Docker — the interface, one command:**

```bash
docker compose up web                  # http://localhost:8080
```

**From source:**

```bash
# Backend
python -m pip install -r backend/requirements.txt
cd backend
python -m pytest                       # 186 tests
python scripts/run_validation.py       # regenerates VALIDATION.md
python scripts/held_out_check.py       # held-out extrapolation check
python scripts/build_fixtures.py       # regenerates all 138 fixtures (~12 min)

# Frontend
cd frontend && npm install
npm run dev                            # http://localhost:5173
npm test                               # 50 tests
```

`docker compose run --rm backend <command>` runs any of the backend scripts in a
container, with the FastF1 cache and the fixture directory mounted from the host.

`?treelab` on the dev server opens the tree layout harness — fabricated numbers,
used to test legibility at depths the app does not ship. It is not reachable from
any control in the interface.

Parameter fits are reproducible and drift-guarded: `scripts/fit_noise_autocorrelation.py`
and `scripts/fit_min_following_gap.py` both re-fit from data and fail loudly if the
committed constant has drifted. Full run commands in [`CLAUDE.md`](CLAUDE.md).

---

## Status

Built in gated phases against [`PROJECT_SPEC.md`](PROJECT_SPEC.md). Running decision log,
with every retraction preserved in place rather than edited away:
[`DECISIONS.md`](DECISIONS.md).

- [x] Phase 0 — Scaffold
- [x] Phase 1 — Data layer
- [x] Phase 2 — Parameter fitting
- [x] Phase 3 — Simulator + validation ⚠️ hard gate (passes under §8.3.1)
- [x] Phase 4 — Counterfactual engine (`ChangePitLap`, `AddPitStop`)
- [~] Phase 5 — API *(deferred, see below)*
- [x] Phase 6 — Frontend core (GapChart, StrategyTimeline, DecisionPanel, Classification)
  - [x] 6.1 — Delta plotting with a robust scale
  - [x] 6.2 — Whole catalogue precomputed, lazily loaded
  - [x] 6.3 — Drag the pit stop; the slider is gone
  - [x] 6.4 — Lap scrubbing, order read per lap
  - [x] 6.5 — The decision space as small multiples
- [x] Phase 7 — Multiverse tree
- [~] Phase 8 — Finish *(this section, Docker Compose; demo GIF outstanding — see below)*

**The API was deferred deliberately, and the interaction loop is complete without it.**
`backend/scripts/build_fixtures.py` precomputes the *entire* decision space through the same
pipeline functions the API would call: **8,085 candidate decisions across 5 races and 133
driver-stops, 485,100 simulations, in 12 minutes on 10 workers**, written as 138 files
totalling 33.8MB. Selecting a race fetches one base file (45–64KB); selecting a driver-stop
fetches exactly one candidate file (median 249KB, max 466KB). Moving the pit stop costs no
network at all — every candidate's ensemble is already open.

So the API would add exactly one thing: an ensemble for a decision type that isn't
precomputed. It does not add correctness, and swapping fixtures for an endpoint is a
data-source change rather than a rewrite. Given the choice between an API serving an
unvalidated simulator and a validated simulator behind precomputed fixtures, the second is
the more honest artifact.

**The demo GIF is not yet recorded.** The interaction it should show is the pit-stop drag:
grab the tick on the alternate stint bar, pull it away from the real lap, and watch the
ochre beyond-evidence hatch grow from nothing as the decision leaves the data. Everything
needed is in the repo — `npm run dev` and drag — but a recorded capture is a manual step
that has not been done, and this section will keep saying so until it has been.

Deliberately **not** implemented, with reasons: `RemovePitStop` (lengthens a stint past
anything observed — the catalogue's longest sample is 42 laps, a one-stop needs 60+),
`ChangeCompound` (~61% prior-dominated, so it would answer from the prior rather than from
the driver's data).

## License

MIT — see [`LICENSE`](LICENSE).
