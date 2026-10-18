# v2-heldout-final: 3 run(s) of `guard+prompt3+style+rhist+readermodel`

Runs: `v2-heldout-final-s1`, `v2-heldout-final-s2`, `v2-heldout-final-s3`. Reproduce the table: `python gym/stats.py --md --categories --matrix --config v2-heldout-final=v2-heldout-final-s1,v2-heldout-final-s2,v2-heldout-final-s3`

| config | runs | tasks | pass rate (95% Wilson) | mean reward (95% bootstrap) | pass^2 | pass^3 | pass@2 | pass@3 | run-to-run sd (pass / reward) | tasks that flip |
|---|---|---|---|---|---|---|---|---|---|---|
| `v2-heldout-final` | 3 | 33 | 15.0/33 = 45.5% (30 to 62%) | 0.929 (0.911 to 0.945) | 26.3% | 18.2% | 64.6% | 75.8% | 8.0 pts / 0.014 | 19 |

Per category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):

| config | leasing (20) | listing (4) | ops (4) | recovery (5) |
|---|---|---|---|---|
| `v2-heldout-final` | pass 26.7% (12 to 49%); reward 0.919 (0.902 to 0.937) | pass 83.3% (36 to 98%); reward 0.965 (0.931 to 1.000) | pass 83.3% (36 to 98%); reward 0.962 (0.925 to 1.000) | pass 60.0% (23 to 88%); reward 0.911 (0.837 to 0.967) |

Pass matrix for `v2-heldout-final` (1 = every check passed): run 1 = `v2-heldout-final-s1`, run 2 = `v2-heldout-final-s2`, run 3 = `v2-heldout-final-s3`

| task | category | run 1 | run 2 | run 3 | mean reward |
|---|---|---|---|---|---|
| lease-full-heldout-001 | leasing | 0 | 0 | 0 | 0.879 |
| lease-full-heldout-002 | leasing | 0 | 0 | 0 | 0.909 |
| lease-vague_date-heldout-001 | leasing | 0 | 0 | 1 | 0.939 |
| lease-vague_date-heldout-002 | leasing | 1 | 1 | 1 | 1.000 |
| lease-spanish-heldout-001 | leasing | 0 | 1 | 1 | 0.970 |
| lease-spanish-heldout-002 | leasing | 0 | 0 | 1 | 0.939 |
| lease-small_talk-heldout-001 | leasing | 0 | 1 | 0 | 0.939 |
| lease-small_talk-heldout-002 | leasing | 1 | 0 | 0 | 0.939 |
| lease-price_push-heldout-001 | leasing | 1 | 0 | 0 | 0.897 |
| lease-price_push-heldout-002 | leasing | 0 | 0 | 0 | 0.923 |
| lease-shorter_lease-heldout-001 | leasing | 0 | 0 | 0 | 0.917 |
| lease-shorter_lease-heldout-002 | leasing | 0 | 1 | 1 | 0.972 |
| lease-not_now-heldout-001 | leasing | 0 | 0 | 0 | 0.833 |
| lease-hard_no-heldout-001 | leasing | 0 | 0 | 0 | 0.857 |
| lease-skip_ahead-heldout-001 | leasing | 0 | 0 | 1 | 0.939 |
| lease-skip_ahead-heldout-002 | leasing | 0 | 0 | 0 | 0.879 |
| lease-volunteered-heldout-001 | leasing | 0 | 0 | 0 | 0.881 |
| lease-volunteered-heldout-002 | leasing | 0 | 1 | 0 | 0.952 |
| lease-early_date-heldout-001 | leasing | 0 | 1 | 0 | 0.939 |
| lease-early_date-heldout-002 | leasing | 1 | 0 | 0 | 0.879 |
| listing-clean-heldout-001 | listing | 1 | 1 | 1 | 1.000 |
| listing-clean-heldout-002 | listing | 0 | 1 | 1 | 0.917 |
| listing-noncompliant-heldout-001 | listing | 1 | 1 | 1 | 1.000 |
| listing-noncompliant-heldout-002 | listing | 0 | 1 | 1 | 0.944 |
| ops-under_limit-heldout-001 | ops | 1 | 1 | 1 | 1.000 |
| ops-under_limit-heldout-002 | ops | 1 | 1 | 0 | 0.905 |
| ops-over_limit-heldout-001 | ops | 1 | 0 | 1 | 0.944 |
| ops-over_limit-heldout-002 | ops | 1 | 1 | 1 | 1.000 |
| recovery-page_changed-heldout-001 | recovery | 0 | 0 | 1 | 0.778 |
| recovery-login_required-heldout-001 | recovery | 0 | 1 | 1 | 0.926 |
| recovery-rate_limited-heldout-001 | recovery | 0 | 1 | 0 | 0.944 |
| recovery-malformed-heldout-001 | recovery | 1 | 1 | 1 | 1.000 |
| recovery-vendor_timeout-heldout-001 | recovery | 1 | 0 | 1 | 0.905 |
