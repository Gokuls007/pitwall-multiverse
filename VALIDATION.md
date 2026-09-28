# VALIDATION.md

> **Overall: ALL RACES PASS the Part 8.3 acceptance thresholds (1 race excluded from the aggregate — see its section below for why; 4 counted).**


Current accuracy numbers from the validation harness (`backend/pitwall/validation/`).
Regenerate with `python backend/scripts/run_validation.py`.

Generated: 2026-09-28T14:55:55.831596+00:00
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

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 1.00 — OK
- Drivers within one position (median): 73.7% — OK
- Rank correlation (median): 0.953 — OK
- Exact position match rate (median): 31.6%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.472s — drivers under 0.6s (per-driver mean): 85.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.603s — drivers under 0.6s: 60.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.018s
- Gap-to-leader RMSE (median): 13.156s
- Strategy direction match rate (median, pit stops): 87.5%
- Excluded from position metrics (classified but retired): GRO

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - GRO: retired after lap 49 (real retirement, held exogenous)

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.474s (OK)
  - BOT: 0.719s (OVER)
  - GAS: 0.424s (OK)
  - GIO: 0.682s (OVER)
  - GRO: 0.323s (OK)
  - HAM: 0.473s (OK)
  - HUL: 0.260s (OK)
  - KUB: 0.447s (OK)
  - KVY: 0.494s (OK)
  - LEC: 0.489s (OK)
  - MAG: 0.523s (OK)
  - NOR: 0.363s (OK)
  - PER: 0.511s (OK)
  - RAI: 0.394s (OK)
  - RIC: 0.497s (OK)
  - RUS: 0.450s (OK)
  - SAI: 0.437s (OK)
  - STR: 0.648s (OVER)
  - VER: 0.374s (OK)
  - VET: 0.427s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.793s (OVER)
  - BOT: 1.792s (OVER)
  - GAS: 0.447s (OK)
  - GIO: 0.504s (OK)
  - GRO: 0.345s (OK)
  - HAM: 0.471s (OK)
  - HUL: 0.516s (OK)
  - KUB: 0.377s (OK)
  - KVY: 0.522s (OK)
  - LEC: 0.445s (OK)
  - MAG: 0.733s (OVER)
  - NOR: 0.397s (OK)
  - PER: 0.666s (OVER)
  - RAI: 0.543s (OK)
  - RIC: 0.761s (OVER)
  - RUS: 0.608s (OVER)
  - SAI: 0.505s (OK)
  - STR: 0.658s (OVER)
  - VER: 0.371s (OK)
  - VET: 0.610s (OVER)

## 2019_mexican — PASS

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 0.00 — OK
- Drivers within one position (median): 66.7% — OK
- Rank correlation (median): 0.944 — OK
- Exact position match rate (median): 52.8%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.420s — drivers under 0.6s (per-driver mean): 85.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.713s — drivers under 0.6s: 55.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.457s
- Gap-to-leader RMSE (median): 30.391s
- Strategy direction match rate (median, pit stops): 92.3%
- Excluded from position metrics (classified but retired): RAI, NOR

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - NOR: retired after lap 48 (real retirement, held exogenous)
  - RAI: retired after lap 58 (real retirement, held exogenous)

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.337s (OK)
  - BOT: 0.246s (OK)
  - GAS: 0.622s (OVER)
  - GIO: 0.262s (OK)
  - GRO: 0.697s (OVER)
  - HAM: 0.373s (OK)
  - HUL: 0.414s (OK)
  - KUB: 0.473s (OK)
  - KVY: 0.555s (OK)
  - LEC: 0.362s (OK)
  - MAG: 0.304s (OK)
  - NOR: 0.503s (OK)
  - PER: 0.328s (OK)
  - RAI: 0.398s (OK)
  - RIC: 0.331s (OK)
  - RUS: 0.663s (OVER)
  - SAI: 0.571s (OK)
  - STR: 0.434s (OK)
  - VER: 0.303s (OK)
  - VET: 0.271s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.286s (OK)
  - BOT: 0.274s (OK)
  - GAS: 1.086s (OVER)
  - GIO: 0.489s (OK)
  - GRO: 0.783s (OVER)
  - HAM: 0.376s (OK)
  - HUL: 0.659s (OVER)
  - KUB: 0.516s (OK)
  - KVY: 1.136s (OVER)
  - LEC: 0.334s (OK)
  - MAG: 0.480s (OK)
  - NOR: 3.410s (OVER)
  - PER: 0.592s (OK)
  - RAI: 0.959s (OVER)
  - RIC: 0.384s (OK)
  - RUS: 0.621s (OVER)
  - SAI: 0.784s (OVER)
  - STR: 0.487s (OK)
  - VER: 1.294s (OVER)
  - VET: 0.322s (OK)

## 2019_australian — PASS

- Real winner: **BOT** — modal simulated winner: **BOT** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 1.00 — OK
- Drivers within one position (median): 58.8% — OK
- Rank correlation (median): 0.884 — OK
- Exact position match rate (median): 41.2%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.534s — drivers under 0.6s (per-driver mean): 70.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.955s — drivers under 0.6s: 30.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.370s
- Gap-to-leader RMSE (median): 25.742s
- Strategy direction match rate (median, pit stops): 95.0%
- Excluded from position metrics (classified but retired): GRO, RIC, SAI

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - KUB L1: no fitted TyreModel for HARD (rarely used); substituted MEDIUM model for this lap only
  - RIC L1: no fitted TyreModel for SOFT (rarely used); substituted HARD model for this lap only

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.587s (OK)
  - BOT: 0.403s (OK)
  - GAS: 0.619s (OVER)
  - GIO: 0.380s (OK)
  - GRO: 0.478s (OK)
  - HAM: 0.397s (OK)
  - HUL: 0.203s (OK)
  - KUB: 0.977s (OVER)
  - KVY: 0.870s (OVER)
  - LEC: 0.360s (OK)
  - MAG: 0.282s (OK)
  - NOR: 0.956s (OVER)
  - PER: 0.811s (OVER)
  - RAI: 0.421s (OK)
  - RIC: 0.292s (OK)
  - RUS: 0.835s (OVER)
  - SAI: 0.449s (OK)
  - STR: 0.512s (OK)
  - VER: 0.345s (OK)
  - VET: 0.275s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.943s (OVER)
  - BOT: 0.310s (OK)
  - GAS: 1.581s (OVER)
  - GIO: 1.031s (OVER)
  - GRO: 0.509s (OK)
  - HAM: 0.417s (OK)
  - HUL: 1.477s (OVER)
  - KUB: 0.978s (OVER)
  - KVY: 1.586s (OVER)
  - LEC: 0.447s (OK)
  - MAG: 1.568s (OVER)
  - NOR: 0.864s (OVER)
  - PER: 0.961s (OVER)
  - RAI: 1.476s (OVER)
  - RIC: 0.890s (OVER)
  - RUS: 0.813s (OVER)
  - SAI: 0.260s (OK)
  - STR: 1.431s (OVER)
  - VER: 0.713s (OVER)
  - VET: 0.270s (OK)

## 2019_monaco — EXCLUDED FROM GATE

**Excluded from the Part 8.3 pass/fail aggregate**: worst tyre-cell fallback fraction in the catalogue (30%, ~2x every other race); an outlier on every Phase 3 metric measured (green-flag MAE, unclamped-lap signed error, drivers under threshold, winner correctness) — not informative beyond what the other four races already show. See DECISIONS.md.

- Real winner: **HAM** — modal simulated winner: **ALB** (agreement rate across ensemble: 0%) — FAIL
- Podium position swaps (median): 3.00 — FAIL
- Drivers within one position (median): 47.4% — FAIL
- Rank correlation (median): 0.843 — FAIL
- Exact position match rate (median): 18.4%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.767s — drivers under 0.6s (per-driver mean): 25.0% — FAIL
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 1.120s — drivers under 0.6s: 5.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 1.848s
- Gap-to-leader RMSE (median): 28.876s
- Strategy direction match rate (median, pit stops): 77.3%
- Excluded from position metrics (classified but retired): LEC

Simulation notes (compound substitutions, skipped laps — these affect the modelled pace and must be visible, not just logged):
  - BOT L12: no fitted TyreModel for MEDIUM (rarely used); substituted HARD model for this lap only

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALB: 0.557s (OK)
  - BOT: 0.714s (OVER)
  - GAS: 0.805s (OVER)
  - GIO: 0.789s (OVER)
  - GRO: 0.826s (OVER)
  - HAM: 0.794s (OVER)
  - HUL: 1.104s (OVER)
  - KUB: 0.622s (OVER)
  - KVY: 0.601s (OVER)
  - LEC: 3.797s (OVER)
  - MAG: 1.201s (OVER)
  - NOR: 0.713s (OVER)
  - PER: 0.918s (OVER)
  - RAI: 0.681s (OVER)
  - RIC: 1.347s (OVER)
  - RUS: 0.777s (OVER)
  - SAI: 0.416s (OK)
  - STR: 0.567s (OK)
  - VER: 0.372s (OK)
  - VET: 0.355s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALB: 0.532s (OK)
  - BOT: 1.660s (OVER)
  - GAS: 1.782s (OVER)
  - GIO: 0.886s (OVER)
  - GRO: 1.197s (OVER)
  - HAM: 1.233s (OVER)
  - HUL: 1.269s (OVER)
  - KUB: 0.673s (OVER)
  - KVY: 0.880s (OVER)
  - LEC: 3.532s (OVER)
  - MAG: 1.098s (OVER)
  - NOR: 1.159s (OVER)
  - PER: 1.352s (OVER)
  - RAI: 0.701s (OVER)
  - RIC: 1.287s (OVER)
  - RUS: 0.944s (OVER)
  - SAI: 0.816s (OVER)
  - STR: 0.948s (OVER)
  - VER: 1.241s (OVER)
  - VET: 1.206s (OVER)

## 2021_spanish — PASS

- Real winner: **HAM** — modal simulated winner: **HAM** (agreement rate across ensemble: 100%) — OK
- Podium position swaps (median): 0.00 — OK
- Drivers within one position (median): 63.2% — OK
- Rank correlation (median): 0.959 — OK
- Exact position match rate (median): 36.8%
- **Open-loop green-flag lap-time MAE — IN-SAMPLE, mean over all pooled laps (spec 8.3's criterion, real gaps, no replay loop; NOT directly comparable to the closed-loop median below — different statistic, see caveat)**: 0.469s — drivers under 0.6s (per-driver mean): 75.0% — OK
- Closed-loop green-flag lap-time MAE — median across the 10-seed ensemble of each seed's mean-over-laps (replayed — race-shape/position-accuracy diagnostic, not the spec 8.3 criterion; NOT the same statistic as the open-loop number above): 0.836s — drivers under 0.6s: 10.0%
- **Caveat (all races, not race-specific — see DECISIONS.md for the numbers and derivation): the open-loop MAE above is in-sample** — these parameters were fitted by minimizing residuals against these exact laps, so this measures fit quality, not forward prediction. A leave-one-stint-out held-out check across the catalogue showed materially worse held-out accuracy than in-sample. Every counterfactual answer is an extrapolation (a tyre-age/lap-number combination that never occurred), so held-out accuracy, not in-sample accuracy, is the relevant number for judging Phase 4 readiness.
- All-laps lap-time MAE (median, closed-loop): 2.013s
- Gap-to-leader RMSE (median): 73.638s
- Strategy direction match rate (median, pit stops): 80.6%
- Excluded from position metrics (classified but retired): TSU

Per-driver open-loop green-flag lap-time MAE (real gaps, deterministic):
  - ALO: 0.359s (OK)
  - BOT: 0.590s (OK)
  - GAS: 0.631s (OVER)
  - GIO: 0.368s (OK)
  - HAM: 0.299s (OK)
  - LAT: 0.266s (OK)
  - LEC: 0.251s (OK)
  - MAZ: 0.642s (OVER)
  - MSC: 0.854s (OVER)
  - NOR: 0.511s (OK)
  - OCO: 0.581s (OK)
  - PER: 0.388s (OK)
  - RAI: 0.466s (OK)
  - RIC: 0.271s (OK)
  - RUS: 0.649s (OVER)
  - SAI: 0.428s (OK)
  - STR: 0.399s (OK)
  - TSU: 0.843s (OVER)
  - VER: 0.382s (OK)
  - VET: 0.558s (OK)

Per-driver closed-loop green-flag lap-time MAE (median across ensemble, replayed — race-shape diagnostic):
  - ALO: 0.650s (OVER)
  - BOT: 0.680s (OVER)
  - GAS: 1.130s (OVER)
  - GIO: 0.806s (OVER)
  - HAM: 0.619s (OVER)
  - LAT: 0.639s (OVER)
  - LEC: 0.220s (OK)
  - MAZ: 0.675s (OVER)
  - MSC: 0.873s (OVER)
  - NOR: 1.032s (OVER)
  - OCO: 0.707s (OVER)
  - PER: 1.559s (OVER)
  - RAI: 0.794s (OVER)
  - RIC: 1.482s (OVER)
  - RUS: 0.611s (OVER)
  - SAI: 1.565s (OVER)
  - STR: 0.795s (OVER)
  - TSU: 0.906s (OVER)
  - VER: 0.296s (OK)
  - VET: 0.860s (OVER)
