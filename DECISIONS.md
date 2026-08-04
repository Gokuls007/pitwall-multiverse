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
