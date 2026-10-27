# Event-study spot check

Budget **FY2021-22** (presented 2021-02-01; day 0 = 2021-02-01). Recomputed by `scripts/verify_event_study.py` directly from `prices_daily.csv`, `index_daily.csv` and `sector_map.json`, without importing the project's event-study module, and compared with `data/csv/event_study.csv`.

Market model on trading days -250..-31 inclusive: alpha, beta by OLS; CAR = sum of (r - alpha - beta * r_m) over the window.

## defence (sector)

Estimation days used: 220; alpha = 0.00026874, beta = 0.872274, residual variance = 3.788e-04

| Window | Hand CAR | Table CAR | Abs diff | Hand t | Table t |
| --- | ---: | ---: | ---: | ---: | ---: |
| [-5,-1] | 0.02094312 | 0.02094312 | 2.08e-12 | 0.4754 | 0.4754 |
| 0 | -0.02397393 | -0.02397393 | 3.17e-12 | -1.2171 | -1.2171 |
| [0,+5] | -0.01925280 | -0.01925280 | 6.25e-13 | -0.3979 | -0.3979 |
| [0,+30] | 0.05537094 | 0.05537094 | 4.48e-13 | 0.4784 | 0.4784 |
| [0,+90] | 0.02452885 | 0.02452885 | 2.89e-12 | 0.1111 | 0.1111 |

## HAL (stock)

Estimation days used: 220; alpha = 0.00072010, beta = 0.492969, residual variance = 1.045e-03

| Window | Hand CAR | Table CAR | Abs diff | Hand t | Table t |
| --- | ---: | ---: | ---: | ---: | ---: |
| [-5,-1] | -0.01864482 | -0.01864482 | 3.33e-12 | -0.2548 | -0.2548 |
| 0 | -0.03873728 | -0.03873728 | 4.39e-12 | -1.1842 | -1.1842 |
| [0,+5] | 0.06150637 | 0.06150637 | 2.15e-12 | 0.7654 | 0.7654 |
| [0,+30] | 0.09435531 | 0.09435531 | 1.06e-12 | 0.4909 | 0.4909 |
| [0,+90] | -0.01298199 | -0.01298199 | 1.33e-12 | -0.0354 | -0.0354 |

Finding from the first run of this check: the pipeline originally used days -250..-32 (it excluded day -31), which gave CAR differences up to 1.7e-2 for Defence [0,+90]. `events/study.py` and the beta window in `features/stock_features.py` now use -250..-31 inclusive as the README specifies; after the fix the hand computation and the table agree to floating-point precision.

**Result: MATCH** (largest absolute CAR difference 4.39e-12).
