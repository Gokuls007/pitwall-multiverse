# VALIDATION.md

Current accuracy numbers from the validation harness (`backend/pitwall/validation/`).
Regenerate with `python backend/scripts/run_validation.py`.

> **Status: not yet populated.** The validation harness (Phase 3) has not run.
> This file is a placeholder created in Phase 0. Per the spec, Phase 3 is a hard gate:
> the simulator must reproduce each catalogued race within the Part 8.3 thresholds
> before any counterfactual work proceeds, and this report must include the cases where
> the model does badly — not only the successes.

## Acceptance thresholds (Part 8.3)

| Metric | Target |
|---|---|
| Green-flag lap-time MAE | < 0.5 s/lap for the majority of drivers |
| Winner reproduced | every catalogued race |
| Podium | at most one position swapped |
| Drivers within one position of reality | ≥ 75% |
| Rank correlation (Spearman/Kendall) | > 0.9 |

Per-race sections (laps used vs excluded with reasons, fit quality, fallbacks,
sensitivity to hand-set parameters) will be filled in by the harness.
