# v2-heldout-final-router: 3 run(s) of `guard+prompt3+style+rhist+readermodel+router`

Runs: `v2-heldout-final-router-s1`, `v2-heldout-final-router-s2`, `v2-heldout-final-router-s3`. Reproduce the table: `python gym/stats.py --md --categories --matrix --config v2-heldout-final-router=v2-heldout-final-router-s1,v2-heldout-final-router-s2,v2-heldout-final-router-s3`

| config | runs | tasks | pass rate (95% Wilson) | mean reward (95% bootstrap) | pass^2 | pass^3 | pass@2 | pass@3 | run-to-run sd (pass / reward) | tasks that flip |
|---|---|---|---|---|---|---|---|---|---|---|
| `v2-heldout-final-router` | 3 | 33 | 15.3/33 = 46.5% (31 to 63%) | 0.876 (0.834 to 0.914) | 29.3% | 21.2% | 63.6% | 72.7% | 1.7 pts / 0.018 | 17 |

Per category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):

| config | leasing (20) | listing (4) | ops (4) | recovery (5) |
|---|---|---|---|---|
| `v2-heldout-final-router` | pass 40.0% (22 to 61%); reward 0.871 (0.818 to 0.918) | pass 50.0% (15 to 85%); reward 0.896 (0.854 to 0.931) | pass 83.3% (36 to 98%); reward 0.972 (0.944 to 1.000) | pass 40.0% (12 to 77%); reward 0.800 (0.675 to 0.928) |

Pass matrix for `v2-heldout-final-router` (1 = every check passed): run 1 = `v2-heldout-final-router-s1`, run 2 = `v2-heldout-final-router-s2`, run 3 = `v2-heldout-final-router-s3`

| task | category | run 1 | run 2 | run 3 | mean reward |
|---|---|---|---|---|---|
| lease-full-heldout-001 | leasing | 0 | 1 | 0 | 0.879 |
| lease-full-heldout-002 | leasing | 0 | 0 | 0 | 0.909 |
| lease-vague_date-heldout-001 | leasing | 1 | 1 | 0 | 0.848 |
| lease-vague_date-heldout-002 | leasing | 1 | 1 | 1 | 1.000 |
| lease-spanish-heldout-001 | leasing | 1 | 1 | 1 | 1.000 |
| lease-spanish-heldout-002 | leasing | 1 | 1 | 1 | 1.000 |
| lease-small_talk-heldout-001 | leasing | 1 | 0 | 0 | 0.909 |
| lease-small_talk-heldout-002 | leasing | 0 | 0 | 0 | 0.606 |
| lease-price_push-heldout-001 | leasing | 0 | 0 | 0 | 0.897 |
| lease-price_push-heldout-002 | leasing | 1 | 0 | 1 | 0.974 |
| lease-shorter_lease-heldout-001 | leasing | 0 | 0 | 1 | 0.833 |
| lease-shorter_lease-heldout-002 | leasing | 0 | 0 | 1 | 0.861 |
| lease-not_now-heldout-001 | leasing | 0 | 0 | 0 | 0.833 |
| lease-hard_no-heldout-001 | leasing | 0 | 0 | 0 | 0.857 |
| lease-skip_ahead-heldout-001 | leasing | 0 | 0 | 1 | 0.879 |
| lease-skip_ahead-heldout-002 | leasing | 1 | 1 | 0 | 0.970 |
| lease-volunteered-heldout-001 | leasing | 1 | 1 | 1 | 1.000 |
| lease-volunteered-heldout-002 | leasing | 0 | 0 | 1 | 0.833 |
| lease-early_date-heldout-001 | leasing | 0 | 0 | 0 | 0.727 |
| lease-early_date-heldout-002 | leasing | 0 | 0 | 0 | 0.606 |
| listing-clean-heldout-001 | listing | 1 | 1 | 0 | 0.917 |
| listing-clean-heldout-002 | listing | 1 | 0 | 0 | 0.833 |
| listing-noncompliant-heldout-001 | listing | 0 | 0 | 1 | 0.889 |
| listing-noncompliant-heldout-002 | listing | 0 | 1 | 1 | 0.944 |
| ops-under_limit-heldout-001 | ops | 1 | 1 | 1 | 1.000 |
| ops-under_limit-heldout-002 | ops | 1 | 1 | 1 | 1.000 |
| ops-over_limit-heldout-001 | ops | 1 | 1 | 0 | 0.944 |
| ops-over_limit-heldout-002 | ops | 1 | 1 | 0 | 0.944 |
| recovery-page_changed-heldout-001 | recovery | 0 | 0 | 0 | 0.778 |
| recovery-login_required-heldout-001 | recovery | 0 | 1 | 1 | 0.926 |
| recovery-rate_limited-heldout-001 | recovery | 0 | 0 | 0 | 0.583 |
| recovery-malformed-heldout-001 | recovery | 1 | 1 | 1 | 1.000 |
| recovery-vendor_timeout-heldout-001 | recovery | 0 | 1 | 0 | 0.714 |
