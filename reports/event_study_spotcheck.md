# Event-study spot check

Budget **FY2021-22** (presented 2021-02-01; day 0 = 2021-02-01). Recomputed by `scripts/verify_event_study.py` directly from `prices_daily.csv`, `index_daily.csv` and `sector_map.json`, without importing the project's event-study module, and compared with `data/csv/event_study.csv`.

Market model on trading days -250..-31 inclusive: alpha, beta by OLS; CAR = sum of (r - alpha - beta * r_m) over the window.

## defence (sector)

Estimation days used: 220; alpha = 0.00026874, beta = 0.872274, residual variance = 3.788e-04

| Window | Hand CAR | Table CAR | Abs diff | Hand t | Table t |
| --- | ---: | ---: | ---: | ---: | ---: |
| [-5,-1] | 0.02094324 | 0.02094324 | 3.66e-12 | 0.4754 | 0.4754 |
| 0 | -0.02397397 | -0.02397397 | 2.56e-13 | -1.2171 | -1.2171 |
| [0,+5] | -0.01925284 | -0.01925284 | 1.02e-12 | -0.3979 | -0.3979 |
| [0,+30] | 0.05537087 | 0.05537087 | 1.71e-12 | 0.4784 | 0.4784 |
| [0,+90] | 0.02452880 | 0.02452880 | 4.43e-12 | 0.1111 | 0.1111 |

## HAL (stock)

Estimation days used: 220; alpha = 0.00072010, beta = 0.492969, residual variance = 1.045e-03

| Window | Hand CAR | Table CAR | Abs diff | Hand t | Table t |
| --- | ---: | ---: | ---: | ---: | ---: |
| [-5,-1] | -0.01864445 | -0.01864445 | 4.66e-12 | -0.2548 | -0.2548 |
| 0 | -0.03873751 | -0.03873751 | 1.86e-12 | -1.1842 | -1.1842 |
| [0,+5] | 0.06150600 | 0.06150600 | 1.05e-12 | 0.7654 | 0.7654 |
| [0,+30] | 0.09435492 | 0.09435492 | 4.75e-12 | 0.4909 | 0.4909 |
| [0,+90] | -0.01298216 | -0.01298216 | 4.06e-12 | -0.0354 | -0.0354 |

Finding from the first run of this check: the pipeline originally used days -250..-32 (it excluded day -31), which gave CAR differences up to 1.7e-2 for Defence [0,+90]. `events/study.py` and the beta window in `features/stock_features.py` now use -250..-31 inclusive as the README specifies; after the fix the hand computation and the table agree to floating-point precision.

**Result: MATCH** (largest absolute CAR difference 4.75e-12).
