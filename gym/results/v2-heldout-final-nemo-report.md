# v2-heldout-final-nemo: 2 run(s) of `prompt3+readermodel`

Runs: `v2-heldout-final-nemo-s1`, `v2-heldout-final-nemo-s2`. Reproduce the table: `python gym/stats.py --md --categories --matrix --config v2-heldout-final-nemo=v2-heldout-final-nemo-s1,v2-heldout-final-nemo-s2`

| config | runs | tasks | pass rate (95% Wilson) | mean reward (95% bootstrap) | pass^2 | pass@2 | run-to-run sd (pass / reward) | tasks that flip |
|---|---|---|---|---|---|---|---|---|
| `v2-heldout-final-nemo` | 2 | 33 | 18.0/33 = 54.5% (38 to 70%) | 0.887 (0.842 to 0.930) | 30.3% | 78.8% | 8.6 pts / 0.072 | 16 |

Per category (pass rate with 95% Wilson, mean reward with 95% bootstrap; n = tasks in the category):

| config | leasing (20) | listing (4) | ops (4) | recovery (5) |
|---|---|---|---|---|
| `v2-heldout-final-nemo` | pass 45.0% (26 to 66%); reward 0.887 (0.833 to 0.936) | pass 75.0% (30 to 95%); reward 0.948 (0.896 to 1.000) | pass 87.5% (40 to 99%); reward 0.917 (0.750 to 1.000) | pass 50.0% (17 to 83%); reward 0.817 (0.667 to 0.967) |

Pass matrix for `v2-heldout-final-nemo` (1 = every check passed): run 1 = `v2-heldout-final-nemo-s1`, run 2 = `v2-heldout-final-nemo-s2`

| task | category | run 1 | run 2 | mean reward |
|---|---|---|---|---|
| lease-full-heldout-001 | leasing | 1 | 1 | 1.000 |
| lease-full-heldout-002 | leasing | 1 | 0 | 0.955 |
| lease-vague_date-heldout-001 | leasing | 0 | 1 | 0.955 |
| lease-vague_date-heldout-002 | leasing | 1 | 1 | 1.000 |
| lease-spanish-heldout-001 | leasing | 0 | 1 | 0.955 |
| lease-spanish-heldout-002 | leasing | 0 | 1 | 0.955 |
| lease-small_talk-heldout-001 | leasing | 1 | 0 | 0.636 |
| lease-small_talk-heldout-002 | leasing | 0 | 1 | 0.955 |
| lease-price_push-heldout-001 | leasing | 0 | 0 | 0.885 |
| lease-price_push-heldout-002 | leasing | 1 | 0 | 0.692 |
| lease-shorter_lease-heldout-001 | leasing | 1 | 1 | 1.000 |
| lease-shorter_lease-heldout-002 | leasing | 0 | 1 | 0.958 |
| lease-not_now-heldout-001 | leasing | 0 | 0 | 0.833 |
| lease-hard_no-heldout-001 | leasing | 0 | 0 | 0.857 |
| lease-skip_ahead-heldout-001 | leasing | 0 | 1 | 0.636 |
| lease-skip_ahead-heldout-002 | leasing | 1 | 0 | 0.955 |
| lease-volunteered-heldout-001 | leasing | 0 | 0 | 0.929 |
| lease-volunteered-heldout-002 | leasing | 1 | 0 | 0.714 |
| lease-early_date-heldout-001 | leasing | 1 | 0 | 0.955 |
| lease-early_date-heldout-002 | leasing | 0 | 0 | 0.909 |
| listing-clean-heldout-001 | listing | 1 | 0 | 0.875 |
| listing-clean-heldout-002 | listing | 1 | 1 | 1.000 |
| listing-noncompliant-heldout-001 | listing | 1 | 1 | 1.000 |
| listing-noncompliant-heldout-002 | listing | 1 | 0 | 0.917 |
| ops-under_limit-heldout-001 | ops | 1 | 1 | 1.000 |
| ops-under_limit-heldout-002 | ops | 1 | 1 | 1.000 |
| ops-over_limit-heldout-001 | ops | 1 | 1 | 1.000 |
| ops-over_limit-heldout-002 | ops | 1 | 0 | 0.667 |
| recovery-page_changed-heldout-001 | recovery | 1 | 0 | 0.833 |
| recovery-login_required-heldout-001 | recovery | 1 | 1 | 1.000 |
| recovery-rate_limited-heldout-001 | recovery | 0 | 0 | 0.667 |
| recovery-malformed-heldout-001 | recovery | 0 | 0 | 0.583 |
| recovery-vendor_timeout-heldout-001 | recovery | 1 | 1 | 1.000 |
