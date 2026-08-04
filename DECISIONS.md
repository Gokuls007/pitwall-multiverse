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
