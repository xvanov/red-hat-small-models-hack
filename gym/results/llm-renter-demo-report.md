# llm-renter-demo: 1 run(s) of `guard+prompt3+style+rhist`

Runs: `llm-renter-demo-s1`. Reproduce the table: `python gym/stats.py --md --categories --matrix --config llm-renter-demo=llm-renter-demo-s1`

| config | runs | tasks | pass rate (95% Wilson) | mean reward (95% bootstrap) | run-to-run sd (pass / reward) | tasks that flip |
|---|---|---|---|---|---|---|
| `llm-renter-demo` | 1 | 6 | 3.0/6 = 50.0% (19 to 81%) | 0.955 (0.924 to 0.985) | 1 run |  |

Per category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):

| config | leasing (6) |
|---|---|
| `llm-renter-demo` | pass 50.0% (19 to 81%); reward 0.955 (0.924 to 0.985) |

Pass matrix for `llm-renter-demo` (1 = every check passed): run 1 = `llm-renter-demo-s1`

| task | category | run 1 | mean reward |
|---|---|---|---|
| lease-full-train-001-llm | leasing | 0 | 0.909 |
| lease-vague_date-train-001-llm | leasing | 1 | 1.000 |
| lease-spanish-train-001-llm | leasing | 0 | 0.909 |
| lease-price_push-train-001-llm | leasing | 1 | 1.000 |
| lease-shorter_lease-train-001-llm | leasing | 1 | 1.000 |
| lease-early_date-train-001-llm | leasing | 0 | 0.909 |
