Confirmatory family with H2 on the combined 90 rows (Amendment 7), Holm one-sided alpha 0.025, m = 5:

| hypothesis | tested | p | Holm p | alpha at rank | decision |
|---|---|---|---|---|---|
| H1 | yes | <0.001 | <0.001 | 0.0050 | supported |
| H2a | yes | 0.002 | 0.009 | 0.0063 | supported |
| H2b | yes | 0.994 | 1.000 | 0.0125 | not supported |
| H4 | yes | 0.011 | 0.033 | 0.0083 | not supported |
| H3 | yes | 1.000 | 1.000 | 0.0250 | not supported |

| H2 | rows | n (rows / threads) | reader acc | comparator acc | Δ (95% CI) | one-sided lb | p (boot / t) | reader-only / comparator-only rows |
|---|---|---|---|---|---|---|---|---|
| H2a | all_90 (primary) | 90 / 29 | 0.522 | 0.267 | +0.256 (+0.093 to +0.405) | +0.093 | 0.001 / 0.002 | 28 / 5 |
| H2a | real_twin_61 (secondary) | 61 / 22 | 0.508 | 0.311 | +0.197 (-0.020 to +0.365) | -0.020 | 0.046 / 0.033 | 17 / 5 |
| H2a | pilot_29 (secondary) | 29 / 7 | 0.552 | 0.172 | +0.379 (+0.118 to +0.667) | +0.118 | <0.001 / 0.025 | 11 / 0 |
| H2a | informative (secondary) | 21 / 8 | 0.524 | 0.048 | +0.476 (+0.182 to +0.800) | +0.182 | <0.001 / 0.015 | 10 / 0 |
| H2b | all_90 (primary) | 90 / 29 | 0.522 | 0.667 | -0.144 (-0.260 to -0.026) | -0.260 | 0.994 / 0.983 | 2 / 15 |
| H2b | real_twin_61 (secondary) | 61 / 22 | 0.508 | 0.574 | -0.066 (-0.152 to +0.029) | -0.152 | 0.932 / 0.900 | 1 / 5 |
| H2b | pilot_29 (secondary) | 29 / 7 | 0.552 | 0.862 | -0.310 (-0.559 to +0.000) | -0.559 | 0.982 / 0.957 | 1 / 10 |
| H2b | informative (secondary) | 21 / 8 | 0.524 | 0.905 | -0.381 (-0.625 to -0.133) | -0.625 | 1.000 / 0.980 | 0 / 8 |

Per-field accuracy, all 90 rows (secondary): 

| system | em_primary |
|---|---|
| finetuned | 0.522 |
| lightning | 0.267 |
| frontier | 0.667 |
