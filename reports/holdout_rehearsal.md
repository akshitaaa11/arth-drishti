# Hold-out REHEARSAL on FY2022-23 and FY2023-24 (NOT the hold-out)

**This is a rehearsal of the hold-out machinery on two already-unlocked budgets. It is not the hold-out result and says nothing about FY2024-25 or FY2025-26.** It exists to show, before the hold-out is spent, that the runner works end to end and that its earlier folds reproduce the saved Phase 5 predictions.

- Evaluation budgets: FY2022-23, FY2023-24. Plan: `config/holdout_plan.json` (frozen before the run). Procedure: The Phase 5 walk-forward is run unchanged (same code, seeds, tuning trials, alpha grid, costs) with the hold-out budgets added as two more test folds; every model is trained only on budgets before the test budget whose 12m label was resolved on its day 0, so FY2025-26 is trained on all earlier budgets including FY2024-25. The first 12 folds must reproduce the saved Phase 5 predictions (drift check). All models and baselines are reported; none is selected or promoted because of its hold-out result.
- Two budgets cannot support a significance test; hold-out results are descriptive. FY2024-25's window runs from 2024-07-24 to the next budget on 2025-02-01 (about six months), FY2025-26's from 2025-02-03 to 2026-02-02 (twelve months).
- Not included: speech features (no speeches exist; Phase 6 re-run blocked); company fundamentals and order wins (not built); the live year FY2026-27 (sealed, unresolved).
- Run: commit `8e399ed21cafdcafdf039a1bf1208d6649ad652e`, tag `n/a (rehearsal)`, freeze tag `holdout-freeze-v1`.
- Drift check (largest absolute difference between the recomputed and saved Phase 5 scores on the earlier folds): equal_weight 0.0e+00, last_years_winners 5.0e-09, biggest_allocation_increase 0.0e+00, ridge 5.0e-09, lgbm_ranker 5.0e-09, bayes_hier 5.0e-09, tier1_blend 3.3e-09, tier1_stack 3.3e-09.

## Pre-registered decision rules, applied mechanically

| Rule | Statement | Values (per budget) | Result |
| --- | --- | --- | --- |
| P1 | IC of the 14 budget-sensitive sectors is at least the bar in BOTH hold-out budgets | IC -0.191, -0.219 | not met |
| S1 | tier1_blend top-3 net return exceeds the equal_weight (all 14) net return in BOTH hold-out budgets | net return minus equal weight: -17.9%, -56.2% | not met |
| S2 | tier1_blend 80% interval coverage over the 28 hold-out forecasts (14 sectors x 2 budgets) lies in 75%-85% | coverage 67.9% | not met |
| S3 | tier2_ranker pooled IC is positive in BOTH hold-out budgets and its top-15 net return exceeds the stock equal_weight net return in BOTH | IC 0.035, -0.028; net return minus equal weight: -8.2%, 18.7% | not met |
| S4 | IT Services (control) is not ranked in the predicted top 3 by tier1_blend in BOTH hold-out budgets | IT in predicted top 3: no, no | **MET** |

P1 is the primary rule; S1-S4 are secondary; values are listed per budget in the order of the evaluation budgets above. No model is selected or promoted because of these results.

## Sector models (14 budget-sensitive sectors)

| Model | Budget | IC | Top-3 hit | Top-k net return | Nifty 500 | Excess |
| --- | --- | --- | --- | --- | --- | --- |
| equal_weight | FY2022-23 | n/a | n/a | 15.0% | 0.3% | 14.7% |
| equal_weight | FY2023-24 | n/a | n/a | 103.1% | 34.4% | 68.7% |
| last_years_winners | FY2022-23 | -0.147 | 0.0% | 8.5% | 0.3% | 8.1% |
| last_years_winners | FY2023-24 | 0.270 | 33.3% | 184.3% | 34.4% | 149.9% |
| biggest_allocation_increase | FY2022-23 | -0.420 | 0.0% | 2.8% | 0.3% | 2.5% |
| biggest_allocation_increase | FY2023-24 | 0.385 | 66.7% | 196.7% | 34.4% | 162.4% |
| ridge | FY2022-23 | -0.262 | 0.0% | -0.8% | 0.3% | -1.1% |
| ridge | FY2023-24 | 0.121 | 33.3% | 157.8% | 34.4% | 123.5% |
| lgbm_ranker | FY2022-23 | 0.029 | 0.0% | 9.6% | 0.3% | 9.2% |
| lgbm_ranker | FY2023-24 | -0.191 | 0.0% | 68.4% | 34.4% | 34.1% |
| bayes_hier | FY2022-23 | -0.226 | 0.0% | 2.8% | 0.3% | 2.5% |
| bayes_hier | FY2023-24 | -0.178 | 0.0% | 109.8% | 34.4% | 75.4% |
| tier1_blend | FY2022-23 | -0.191 | 0.0% | -2.9% | 0.3% | -3.2% |
| tier1_blend | FY2023-24 | -0.219 | 0.0% | 46.9% | 34.4% | 12.5% |
| tier1_stack | FY2022-23 | -0.191 | 0.0% | -2.9% | 0.3% | -3.2% |
| tier1_stack | FY2023-24 | -0.219 | 0.0% | 46.9% | 34.4% | 12.5% |

Mean over the two budgets:

| Model | Mean IC | Mean net return | Mean excess vs Nifty 500 |
| --- | --- | --- | --- |
| bayes_hier | -0.202 | 56.3% | 39.0% |
| biggest_allocation_increase | -0.018 | 99.8% | 82.4% |
| equal_weight | n/a | 59.0% | 41.7% |
| last_years_winners | 0.062 | 96.4% | 79.0% |
| lgbm_ranker | -0.081 | 39.0% | 21.6% |
| ridge | -0.070 | 78.5% | 61.2% |
| tier1_blend | -0.205 | 22.0% | 4.7% |
| tier1_stack | -0.205 | 22.0% | 4.7% |

## Stock models (top-15 portfolios)

| Model | Budget | IC | Within-sector IC | Top-k net return | Nifty 500 | Excess |
| --- | --- | --- | --- | --- | --- | --- |
| equal_weight | FY2022-23 | n/a | n/a | 13.4% | 0.3% | 13.0% |
| equal_weight | FY2023-24 | n/a | n/a | 109.1% | 34.4% | 74.8% |
| momentum_12m | FY2022-23 | -0.102 | -0.129 | -1.1% | 0.3% | -1.5% |
| momentum_12m | FY2023-24 | 0.192 | 0.117 | 126.7% | 34.4% | 92.3% |
| ridge | FY2022-23 | -0.005 | 0.030 | 4.9% | 0.3% | 4.6% |
| ridge | FY2023-24 | 0.123 | 0.261 | 185.1% | 34.4% | 150.8% |
| sector_then_momentum | FY2022-23 | -0.108 | -0.145 | -10.2% | 0.3% | -10.6% |
| sector_then_momentum | FY2023-24 | -0.175 | 0.117 | 48.5% | 34.4% | 14.1% |
| tier2_ranker | FY2022-23 | 0.035 | -0.038 | 5.1% | 0.3% | 4.8% |
| tier2_ranker | FY2023-24 | -0.028 | -0.023 | 127.8% | 34.4% | 93.5% |

Mean over the two budgets:

| Model | Mean IC | Mean net return | Mean excess vs Nifty 500 |
| --- | --- | --- | --- |
| equal_weight | n/a | 61.2% | 43.9% |
| momentum_12m | 0.045 | 62.8% | 45.4% |
| ridge | 0.059 | 95.0% | 77.7% |
| sector_then_momentum | -0.142 | 19.1% | 1.8% |
| tier2_ranker | 0.003 | 66.5% | 49.1% |

## Interval coverage (80% target, 75-85% accepted)

| Model | Level | Forecasts | Coverage |
| --- | --- | --- | --- |
| bayes_hier | sector | 28 | 67.9% |
| lgbm_ranker | sector | 28 | 67.9% |
| tier1_blend | sector | 28 | 67.9% |
| tier1_stack | sector | 28 | 67.9% |
| tier2_ranker | stock | 202 | 62.4% |

Intervals are walk-forward conformal (Phase 7), calibrated on earlier resolved out-of-sample errors only.

## IT Services (control sector)

| Model | Budget | Predicted rank (of 15) | Realised rank |
| --- | --- | --- | --- |
| last_years_winners | FY2022-23 | 6.0 | 15.0 |
| last_years_winners | FY2023-24 | 15.0 | 13.0 |
| biggest_allocation_increase | FY2022-23 | 3.0 | 15.0 |
| biggest_allocation_increase | FY2023-24 | 3.0 | 13.0 |
| ridge | FY2022-23 | 4.0 | 15.0 |
| ridge | FY2023-24 | 2.0 | 13.0 |
| lgbm_ranker | FY2022-23 | 12.0 | 15.0 |
| lgbm_ranker | FY2023-24 | 11.0 | 13.0 |
| bayes_hier | FY2022-23 | 2.0 | 15.0 |
| bayes_hier | FY2023-24 | 1.0 | 13.0 |
| tier1_blend | FY2022-23 | 7.0 | 15.0 |
| tier1_blend | FY2023-24 | 5.0 | 13.0 |
| tier1_stack | FY2022-23 | 7.0 | 15.0 |
| tier1_stack | FY2023-24 | 5.0 | 13.0 |

Predictions with their three reasons and intervals: `reports/holdout_rehearsal_predictions.csv`.

