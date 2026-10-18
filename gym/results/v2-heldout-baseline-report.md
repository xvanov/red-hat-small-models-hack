# v2-heldout-baseline: 3 run(s) of `base`

Runs: `v2-heldout-baseline-s1`, `v2-heldout-baseline-s2`, `v2-heldout-baseline-s3`. Reproduce the table: `python gym/stats.py --md --categories --matrix --config v2-heldout-baseline=v2-heldout-baseline-s1,v2-heldout-baseline-s2,v2-heldout-baseline-s3`

| config | runs | tasks | pass rate (95% Wilson) | mean reward (95% bootstrap) | pass^2 | pass^3 | pass@2 | pass@3 | run-to-run sd (pass / reward) | tasks that flip |
|---|---|---|---|---|---|---|---|---|---|---|
| `v2-heldout-baseline` | 3 | 33 | 4.0/33 = 12.1% (5 to 27%) | 0.570 (0.493 to 0.648) | 7.1% | 6.1% | 17.2% | 21.2% | 0.0 pts / 0.017 | 5 |

Per category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):

| config | leasing (20) | listing (4) | ops (4) | recovery (5) |
|---|---|---|---|---|
| `v2-heldout-baseline` | pass 5.0% (1 to 24%); reward 0.425 (0.360 to 0.492) | pass 8.3% (1 to 57%); reward 0.799 (0.750 to 0.847) | pass 50.0% (15 to 85%); reward 0.893 (0.786 to 1.000) | pass 13.3% (2 to 57%); reward 0.710 (0.596 to 0.824) |

Pass matrix for `v2-heldout-baseline` (1 = every check passed): run 1 = `v2-heldout-baseline-s1`, run 2 = `v2-heldout-baseline-s2`, run 3 = `v2-heldout-baseline-s3`

| task | category | run 1 | run 2 | run 3 | mean reward |
|---|---|---|---|---|---|
| lease-full-heldout-001 | leasing | 1 | 0 | 1 | 0.758 |
| lease-full-heldout-002 | leasing | 0 | 0 | 0 | 0.273 |
| lease-vague_date-heldout-001 | leasing | 0 | 1 | 0 | 0.515 |
| lease-vague_date-heldout-002 | leasing | 0 | 0 | 0 | 0.273 |
| lease-spanish-heldout-001 | leasing | 0 | 0 | 0 | 0.455 |
| lease-spanish-heldout-002 | leasing | 0 | 0 | 0 | 0.273 |
| lease-small_talk-heldout-001 | leasing | 0 | 0 | 0 | 0.273 |
| lease-small_talk-heldout-002 | leasing | 0 | 0 | 0 | 0.273 |
| lease-price_push-heldout-001 | leasing | 0 | 0 | 0 | 0.564 |
| lease-price_push-heldout-002 | leasing | 0 | 0 | 0 | 0.410 |
| lease-shorter_lease-heldout-001 | leasing | 0 | 0 | 0 | 0.250 |
| lease-shorter_lease-heldout-002 | leasing | 0 | 0 | 0 | 0.444 |
| lease-not_now-heldout-001 | leasing | 0 | 0 | 0 | 0.556 |
| lease-hard_no-heldout-001 | leasing | 0 | 0 | 0 | 0.429 |
| lease-skip_ahead-heldout-001 | leasing | 0 | 0 | 0 | 0.667 |
| lease-skip_ahead-heldout-002 | leasing | 0 | 0 | 0 | 0.394 |
| lease-volunteered-heldout-001 | leasing | 0 | 0 | 0 | 0.571 |
| lease-volunteered-heldout-002 | leasing | 0 | 0 | 0 | 0.571 |
| lease-early_date-heldout-001 | leasing | 0 | 0 | 0 | 0.273 |
| lease-early_date-heldout-002 | leasing | 0 | 0 | 0 | 0.273 |
| listing-clean-heldout-001 | listing | 0 | 0 | 0 | 0.750 |
| listing-clean-heldout-002 | listing | 0 | 0 | 0 | 0.750 |
| listing-noncompliant-heldout-001 | listing | 0 | 0 | 0 | 0.833 |
| listing-noncompliant-heldout-002 | listing | 1 | 0 | 0 | 0.861 |
| ops-under_limit-heldout-001 | ops | 0 | 0 | 0 | 0.857 |
| ops-under_limit-heldout-002 | ops | 0 | 0 | 0 | 0.714 |
| ops-over_limit-heldout-001 | ops | 1 | 1 | 1 | 1.000 |
| ops-over_limit-heldout-002 | ops | 1 | 1 | 1 | 1.000 |
| recovery-page_changed-heldout-001 | recovery | 0 | 0 | 0 | 0.704 |
| recovery-login_required-heldout-001 | recovery | 0 | 1 | 0 | 0.852 |
| recovery-rate_limited-heldout-001 | recovery | 0 | 0 | 0 | 0.583 |
| recovery-malformed-heldout-001 | recovery | 0 | 0 | 1 | 0.556 |
| recovery-vendor_timeout-heldout-001 | recovery | 0 | 0 | 0 | 0.857 |
