# VALIDATION.md

> **Overall: ALL RACES PASS the Part 8.3 acceptance thresholds (1 race excluded from the aggregate — see its section below for why; 4 counted).**


Current accuracy numbers from the validation harness (`backend/pitwall/validation/`).
Regenerate with `python backend/scripts/run_validation.py`.

Generated: 2026-08-04T19:08:39.855886+00:00
Ensemble size per race: 10 seeds ([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]) — spec 6.10: a single stochastic run is one sample, not a result.

## Acceptance thresholds (Part 8.3.1, revised 2026-08-04 per 8.3's own "to be revised with justification once the real numbers are known" clause — see PROJECT_SPEC.md 8.3.1 and DECISIONS.md for the justification)

| Metric | Target |
|---|---|
| Green-flag lap-time MAE (open-loop) | < 0.6s/lap for a strict majority (> 50%) of drivers |
| Winner reproduced | modal ensemble winner matches reality |
| Podium | at most 1 position swapped (median) |
| Drivers within one position of reality | >= 55% (median) |
| Rank correlation (Spearman) | > 0.85 (median) |

**How a point threshold is applied to a stochastic ensemble is a project decision, not specified by the spec — see DECISIONS.md for the exact operationalisation of each check above (median across seeds, or modal value for the winner check).**

## 2019_hungarian — PASS

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 90%) — OK
- Podium position swaps (median): 1.00 — OK
- Drivers within one position (median): 65.8% — OK
- Rank correlation (median): 0.944 — OK
- Exact position match rate (median): 36.8%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.537s — drivers under 0.6s (per-driver mean): 80.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.903s — drivers under 0.6s: 30.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.328s
- Gap-to-leader RMSE (median): 35.291s
- Strategy direction match rate (median, pit stops): 91.7%
- Excluded from position metrics (classified but retired): GRO

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - GRO: retired after lap 49 (real retirement, held exogenous)

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.858s (OVER)
  - BOT: 0.674s (OVER)
  - GAS: 0.817s (OVER)
  - GIO: 0.582s (OK)
  - GRO: 0.367s (OK)
  - HAM: 0.465s (OK)
  - HUL: 0.289s (OK)
  - KUB: 0.488s (OK)
  - KVY: 0.507s (OK)
  - LEC: 0.499s (OK)
  - MAG: 1.154s (OVER)
  - NOR: 0.361s (OK)
  - PER: 0.536s (OK)
  - RAI: 0.310s (OK)
  - RIC: 0.463s (OK)
  - RUS: 0.457s (OK)
  - SAI: 0.416s (OK)
  - STR: 0.570s (OK)
  - VER: 0.411s (OK)
  - VET: 0.434s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 1.641s (OVER)
  - BOT: 2.341s (OVER)
  - GAS: 0.840s (OVER)
  - GIO: 0.755s (OVER)
  - GRO: 0.437s (OK)
  - HAM: 0.540s (OK)
  - HUL: 0.495s (OK)
  - KUB: 0.627s (OVER)
  - KVY: 1.044s (OVER)
  - LEC: 0.416s (OK)
  - MAG: 1.565s (OVER)
  - NOR: 0.817s (OVER)
  - PER: 1.106s (OVER)
  - RAI: 0.713s (OVER)
  - RIC: 1.503s (OVER)
  - RUS: 0.791s (OVER)
  - SAI: 0.860s (OVER)
  - STR: 0.827s (OVER)
  - VER: 0.407s (OK)
  - VET: 0.576s (OK)

## 2019_mexican — PASS

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 0.00 — OK
- Drivers within one position (median): 83.3% — OK
- Rank correlation (median): 0.948 — OK
- Exact position match rate (median): 61.1%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.493s — drivers under 0.6s (per-driver mean): 80.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.803s — drivers under 0.6s: 35.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.542s
- Gap-to-leader RMSE (median): 34.264s
- Strategy direction match rate (median, pit stops): 96.2%
- Excluded from position metrics (classified but retired): RAI, NOR

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - NOR: retired after lap 48 (real retirement, held exogenous)
  - RAI: retired after lap 58 (real retirement, held exogenous)

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.411s (OK)
  - BOT: 0.297s (OK)
  - GAS: 0.919s (OVER)
  - GIO: 0.287s (OK)
  - GRO: 0.720s (OVER)
  - HAM: 0.477s (OK)
  - HUL: 0.392s (OK)
  - KUB: 0.510s (OK)
  - KVY: 0.574s (OK)
  - LEC: 0.477s (OK)
  - MAG: 0.392s (OK)
  - NOR: 0.512s (OK)
  - PER: 0.326s (OK)
  - RAI: 0.407s (OK)
  - RIC: 0.674s (OVER)
  - RUS: 0.626s (OVER)
  - SAI: 0.558s (OK)
  - STR: 0.533s (OK)
  - VER: 0.375s (OK)
  - VET: 0.384s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.366s (OK)
  - BOT: 0.335s (OK)
  - GAS: 1.235s (OVER)
  - GIO: 0.678s (OVER)
  - GRO: 0.795s (OVER)
  - HAM: 0.470s (OK)
  - HUL: 0.815s (OVER)
  - KUB: 0.486s (OK)
  - KVY: 1.210s (OVER)
  - LEC: 0.408s (OK)
  - MAG: 0.483s (OK)
  - NOR: 3.334s (OVER)
  - PER: 0.685s (OVER)
  - RAI: 1.018s (OVER)
  - RIC: 0.770s (OVER)
  - RUS: 0.616s (OVER)
  - SAI: 1.092s (OVER)
  - STR: 0.847s (OVER)
  - VER: 1.092s (OVER)
  - VET: 0.432s (OK)

## 2019_australian — PASS

- Real winner: **BOT** — modal simulated winner: **BOT** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 1.00 — OK
- Drivers within one position (median): 58.8% — OK
- Rank correlation (median): 0.897 — OK
- Exact position match rate (median): 41.2%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.580s — drivers under 0.6s (per-driver mean): 70.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.878s — drivers under 0.6s: 30.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.341s
- Gap-to-leader RMSE (median): 22.627s
- Strategy direction match rate (median, pit stops): 95.0%
- Excluded from position metrics (classified but retired): GRO, RIC, SAI

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - KUB L1: no fitted TyreModel for HARD (rarely used); substituted MEDIUM model for this lap only
  - RIC L1: no fitted TyreModel for SOFT (rarely used); substituted HARD model for this lap only

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.578s (OK)
  - BOT: 0.447s (OK)
  - GAS: 0.457s (OK)
  - GIO: 0.445s (OK)
  - GRO: 0.495s (OK)
  - HAM: 0.486s (OK)
  - HUL: 0.174s (OK)
  - KUB: 0.985s (OVER)
  - KVY: 1.106s (OVER)
  - LEC: 0.409s (OK)
  - MAG: 0.369s (OK)
  - NOR: 0.969s (OVER)
  - PER: 0.914s (OVER)
  - RAI: 0.379s (OK)
  - RIC: 0.358s (OK)
  - RUS: 0.923s (OVER)
  - SAI: 0.586s (OK)
  - STR: 0.689s (OVER)
  - VER: 0.365s (OK)
  - VET: 0.310s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.991s (OVER)
  - BOT: 0.315s (OK)
  - GAS: 0.748s (OVER)
  - GIO: 1.003s (OVER)
  - GRO: 0.658s (OVER)
  - HAM: 0.515s (OK)
  - HUL: 1.561s (OVER)
  - KUB: 0.986s (OVER)
  - KVY: 1.594s (OVER)
  - LEC: 0.511s (OK)
  - MAG: 1.514s (OVER)
  - NOR: 0.909s (OVER)
  - PER: 1.035s (OVER)
  - RAI: 0.536s (OK)
  - RIC: 0.753s (OVER)
  - RUS: 0.883s (OVER)
  - SAI: 0.329s (OK)
  - STR: 1.431s (OVER)
  - VER: 0.692s (OVER)
  - VET: 0.304s (OK)

## 2019_monaco — EXCLUDED FROM GATE

**Excluded from the Part 8.3 pass/fail aggregate**: worst tyre-cell fallback fraction in the catalogue (30%, ~2x every other race); an outlier on every Phase 3 metric measured (green-flag MAE, unclamped-lap signed error, drivers under threshold, winner correctness) — not informative beyond what the other four races already show. See DECISIONS.md.

- Real winner: **HAM** — modal simulated winner: **KVY** (agreement rate across ensemble: 0%) — FAIL
- Podium position swaps (median): 3.00 — FAIL
- Drivers within one position (median): 42.1% — FAIL
- Rank correlation (median): 0.848 — FAIL
- Exact position match rate (median): 26.3%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.861s — drivers under 0.6s (per-driver mean): 25.0% — FAIL
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 1.575s — drivers under 0.6s: 15.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 2.273s
- Gap-to-leader RMSE (median): 36.117s
- Strategy direction match rate (median, pit stops): 81.8%
- Excluded from position metrics (classified but retired): LEC

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - BOT L12: no fitted TyreModel for MEDIUM (rarely used); substituted HARD model for this lap only

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.639s (OVER)
  - BOT: 0.519s (OK)
  - GAS: 0.840s (OVER)
  - GIO: 0.745s (OVER)
  - GRO: 0.754s (OVER)
  - HAM: 0.913s (OVER)
  - HUL: 1.052s (OVER)
  - KUB: 0.642s (OVER)
  - KVY: 0.704s (OVER)
  - LEC: 3.554s (OVER)
  - MAG: 1.610s (OVER)
  - NOR: 1.236s (OVER)
  - PER: 0.956s (OVER)
  - RAI: 0.643s (OVER)
  - RIC: 1.893s (OVER)
  - RUS: 0.807s (OVER)
  - SAI: 0.484s (OK)
  - STR: 0.585s (OK)
  - VER: 0.578s (OK)
  - VET: 0.343s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.586s (OK)
  - BOT: 1.810s (OVER)
  - GAS: 1.050s (OVER)
  - GIO: 1.675s (OVER)
  - GRO: 2.236s (OVER)
  - HAM: 1.672s (OVER)
  - HUL: 1.455s (OVER)
  - KUB: 1.570s (OVER)
  - KVY: 0.542s (OK)
  - LEC: 3.843s (OVER)
  - MAG: 1.913s (OVER)
  - NOR: 2.071s (OVER)
  - PER: 2.173s (OVER)
  - RAI: 1.513s (OVER)
  - RIC: 2.193s (OVER)
  - RUS: 1.339s (OVER)
  - SAI: 0.489s (OK)
  - STR: 1.728s (OVER)
  - VER: 1.635s (OVER)
  - VET: 1.800s (OVER)

## 2021_spanish — PASS

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 80%) — OK
- Podium position swaps (median): 0.00 — OK
- Drivers within one position (median): 63.2% — OK
- Rank correlation (median): 0.955 — OK
- Exact position match rate (median): 36.8%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.469s — drivers under 0.6s (per-driver mean): 70.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.838s — drivers under 0.6s: 25.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 2.049s
- Gap-to-leader RMSE (median): 74.409s
- Strategy direction match rate (median, pit stops): 84.7%
- Excluded from position metrics (classified but retired): TSU

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALO: 0.335s (OK)
  - BOT: 0.615s (OVER)
  - GAS: 0.538s (OK)
  - GIO: 0.381s (OK)
  - HAM: 0.307s (OK)
  - LAT: 0.276s (OK)
  - LEC: 0.354s (OK)
  - MAZ: 0.666s (OVER)
  - MSC: 0.883s (OVER)
  - NOR: 0.507s (OK)
  - OCO: 0.606s (OVER)
  - PER: 0.398s (OK)
  - RAI: 0.450s (OK)
  - RIC: 0.314s (OK)
  - RUS: 0.619s (OVER)
  - SAI: 0.318s (OK)
  - STR: 0.400s (OK)
  - TSU: 0.915s (OVER)
  - VER: 0.450s (OK)
  - VET: 0.466s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALO: 0.558s (OK)
  - BOT: 0.702s (OVER)
  - GAS: 1.041s (OVER)
  - GIO: 0.728s (OVER)
  - HAM: 0.527s (OK)
  - LAT: 0.529s (OK)
  - LEC: 0.326s (OK)
  - MAZ: 0.669s (OVER)
  - MSC: 0.873s (OVER)
  - NOR: 0.976s (OVER)
  - OCO: 0.760s (OVER)
  - PER: 1.487s (OVER)
  - RAI: 0.812s (OVER)
  - RIC: 1.446s (OVER)
  - RUS: 0.603s (OVER)
  - SAI: 1.579s (OVER)
  - STR: 0.872s (OVER)
  - TSU: 0.887s (OVER)
  - VER: 0.405s (OK)
  - VET: 0.948s (OVER)
