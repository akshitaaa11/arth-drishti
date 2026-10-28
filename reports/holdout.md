# Hold-out evaluation (FY2024-25 and FY2025-26): the one-time run

Produced by exactly one run of `python -m bsp.evaluation.holdout --mode holdout` at the tagged commit below. Nothing was re-tuned after seeing it. This is descriptive: two budgets cannot support a significance test.

- Evaluation budgets: FY2024-25, FY2025-26. Plan: `config/holdout_plan.json` (frozen before the run). Procedure: The Phase 5 walk-forward is run unchanged (same code, seeds, tuning trials, alpha grid, costs) with the hold-out budgets added as two more test folds; every model is trained only on budgets before the test budget whose 12m label was resolved on its day 0, so FY2025-26 is trained on all earlier budgets including FY2024-25. The first 12 folds must reproduce the saved Phase 5 predictions (drift check). All models and baselines are reported; none is selected or promoted because of its hold-out result.
- Two budgets cannot support a significance test; hold-out results are descriptive. FY2024-25's window runs from 2024-07-24 to the next budget on 2025-02-01 (about six months), FY2025-26's from 2025-02-03 to 2026-02-02 (twelve months).
- Not included: speech features (no speeches exist; Phase 6 re-run blocked); company fundamentals and order wins (not built); the live year FY2026-27 (sealed, unresolved).
- Run: commit `d8a269010b355c63774c278819e82b5764cf5f43`, tag `holdout-run-v1`, freeze tag `holdout-freeze-v1`.
- Drift check (largest absolute difference between the recomputed and the saved Phase 5 scores on every fold that was already saved): equal_weight 0.0e+00, last_years_winners 5.0e-09, biggest_allocation_increase 0.0e+00, ridge 5.0e-09, lgbm_ranker 5.0e-09, bayes_hier 5.0e-09, tier1_blend 3.3e-09, tier1_stack 3.3e-09.

## Pre-registered decision rules, applied mechanically

| Rule | Statement | Values (per budget) | Result |
| --- | --- | --- | --- |
| P1 | IC of the 14 budget-sensitive sectors is at least the bar in BOTH hold-out budgets | IC -0.247, 0.225 | not met |
| S1 | tier1_blend top-3 net return exceeds the equal_weight (all 14) net return in BOTH hold-out budgets | net return minus equal weight: -7.7%, -5.0% | not met |
| S2 | tier1_blend 80% interval coverage over the 28 hold-out forecasts (14 sectors x 2 budgets) lies in 75%-85% | coverage 64.3% | not met |
| S3 | tier2_ranker pooled IC is positive in BOTH hold-out budgets and its top-15 net return exceeds the stock equal_weight net return in BOTH | IC -0.084, 0.189; net return minus equal weight: 4.5%, 2.0% | not met |
| S4 | IT Services (control) is not ranked in the predicted top 3 by tier1_blend in BOTH hold-out budgets | IT in predicted top 3: no, no | **MET** |

P1 is the primary rule; S1-S4 are secondary; values are listed per budget in the order of the evaluation budgets above. No model is selected or promoted because of these results.

## Sector models (14 budget-sensitive sectors)

| Model | Budget | IC | Top-3 hit | Top-k net return | Nifty 500 | Excess |
| --- | --- | --- | --- | --- | --- | --- |
| equal_weight | FY2024-25 | n/a | n/a | -11.6% | -6.3% | -5.3% |
| equal_weight | FY2025-26 | n/a | n/a | -0.5% | 6.6% | -7.1% |
| last_years_winners | FY2024-25 | -0.908 | 0.0% | -22.0% | -6.3% | -15.7% |
| last_years_winners | FY2025-26 | 0.393 | 33.3% | 8.7% | 6.6% | 2.0% |
| biggest_allocation_increase | FY2024-25 | -0.275 | 33.3% | -9.5% | -6.3% | -3.2% |
| biggest_allocation_increase | FY2025-26 | -0.371 | 0.0% | -6.9% | 6.6% | -13.5% |
| ridge | FY2024-25 | -0.820 | 0.0% | -22.9% | -6.3% | -16.7% |
| ridge | FY2025-26 | -0.297 | 0.0% | -4.5% | 6.6% | -11.1% |
| lgbm_ranker | FY2024-25 | -0.086 | 0.0% | -8.9% | -6.3% | -2.7% |
| lgbm_ranker | FY2025-26 | 0.174 | 33.3% | 12.2% | 6.6% | 5.6% |
| bayes_hier | FY2024-25 | -0.235 | 33.3% | -13.7% | -6.3% | -7.4% |
| bayes_hier | FY2025-26 | 0.266 | 33.3% | 5.3% | 6.6% | -1.3% |
| tier1_blend | FY2024-25 | -0.247 | 0.0% | -19.2% | -6.3% | -12.9% |
| tier1_blend | FY2025-26 | 0.225 | 0.0% | -5.5% | 6.6% | -12.1% |
| tier1_stack | FY2024-25 | -0.247 | 0.0% | -19.2% | -6.3% | -12.9% |
| tier1_stack | FY2025-26 | 0.246 | 33.3% | 12.2% | 6.6% | 5.6% |

Mean over the two budgets:

| Model | Mean IC | Mean net return | Mean excess vs Nifty 500 |
| --- | --- | --- | --- |
| bayes_hier | 0.015 | -4.2% | -4.3% |
| biggest_allocation_increase | -0.323 | -8.2% | -8.3% |
| equal_weight | n/a | -6.0% | -6.2% |
| last_years_winners | -0.257 | -6.7% | -6.8% |
| lgbm_ranker | 0.044 | 1.6% | 1.5% |
| ridge | -0.558 | -13.7% | -13.9% |
| tier1_blend | -0.011 | -12.4% | -12.5% |
| tier1_stack | -0.000 | -3.5% | -3.7% |

## Stock models (top-15 portfolios)

| Model | Budget | IC | Within-sector IC | Top-k net return | Nifty 500 | Excess |
| --- | --- | --- | --- | --- | --- | --- |
| equal_weight | FY2024-25 | n/a | n/a | -12.6% | -6.3% | -6.3% |
| equal_weight | FY2025-26 | n/a | n/a | 0.3% | 6.6% | -6.3% |
| momentum_12m | FY2024-25 | -0.403 | -0.134 | -26.6% | -6.3% | -20.3% |
| momentum_12m | FY2025-26 | 0.127 | -0.037 | 14.0% | 6.6% | 7.4% |
| ridge | FY2024-25 | -0.172 | -0.203 | -23.5% | -6.3% | -17.2% |
| ridge | FY2025-26 | -0.123 | -0.040 | 2.0% | 6.6% | -4.6% |
| sector_then_momentum | FY2024-25 | -0.038 | -0.134 | -18.2% | -6.3% | -11.9% |
| sector_then_momentum | FY2025-26 | 0.109 | -0.037 | -6.5% | 6.6% | -13.1% |
| tier2_ranker | FY2024-25 | -0.084 | 0.000 | -8.2% | -6.3% | -1.9% |
| tier2_ranker | FY2025-26 | 0.189 | 0.098 | 2.2% | 6.6% | -4.4% |

Mean over the two budgets:

| Model | Mean IC | Mean net return | Mean excess vs Nifty 500 |
| --- | --- | --- | --- |
| equal_weight | n/a | -6.2% | -6.3% |
| momentum_12m | -0.138 | -6.3% | -6.4% |
| ridge | -0.147 | -10.7% | -10.9% |
| sector_then_momentum | 0.036 | -12.3% | -12.5% |
| tier2_ranker | 0.053 | -3.0% | -3.1% |

## Interval coverage (80% target, 75-85% accepted)

| Model | Level | Forecasts | Coverage |
| --- | --- | --- | --- |
| bayes_hier | sector | 28 | 92.9% |
| lgbm_ranker | sector | 28 | 57.1% |
| tier1_blend | sector | 28 | 64.3% |
| tier1_stack | sector | 28 | 67.9% |
| tier2_ranker | stock | 212 | 87.3% |

Intervals are walk-forward conformal (Phase 7), calibrated on earlier resolved out-of-sample errors only.

## IT Services (control sector)

| Model | Budget | Predicted rank (of 15) | Realised rank |
| --- | --- | --- | --- |
| last_years_winners | FY2024-25 | 13.0 | 2.0 |
| last_years_winners | FY2025-26 | 3.0 | 9.0 |
| biggest_allocation_increase | FY2024-25 | 2.0 | 2.0 |
| biggest_allocation_increase | FY2025-26 | 3.0 | 9.0 |
| ridge | FY2024-25 | 5.0 | 2.0 |
| ridge | FY2025-26 | 1.0 | 9.0 |
| lgbm_ranker | FY2024-25 | 9.0 | 2.0 |
| lgbm_ranker | FY2025-26 | 13.0 | 9.0 |
| bayes_hier | FY2024-25 | 2.0 | 2.0 |
| bayes_hier | FY2025-26 | 2.0 | 9.0 |
| tier1_blend | FY2024-25 | 3.5 | 2.0 |
| tier1_blend | FY2025-26 | 8.0 | 9.0 |
| tier1_stack | FY2024-25 | 3.5 | 2.0 |
| tier1_stack | FY2025-26 | 10.0 | 9.0 |

Predictions with their three reasons and intervals: `reports/holdout_predictions.csv`.

