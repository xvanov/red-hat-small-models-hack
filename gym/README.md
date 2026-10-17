# gym/: the Rentus Operator NeMo Gym environment (W4)

This folder has the tasks, the tools the agent uses and the code that scores every attempt, plus the scripts that measure a baseline and isolate each improvement on held-out tasks.

```
rentus_env/            pure-Python core (3.12+), shared by both runners and the console
  session.py           RolloutSession: one World per rollout, wraps rentus_tools.call, records the trace
  counterparts.py      scripted renters, tenants and vendors (no model, decision D4)
  verify.py            the scorer: 7 check types, reward = fraction of checks passed
  backend.py           finds rentus_tools (W3), falling back to the operator shim
resources_servers/rentus/   the NeMo Gym resources server (tool routes, seed_session, verify) + config + data
tasks/{train,heldout}.jsonl  51 train + 31 held-out tasks; stats.json
build_tasks.py         regenerates tasks/ (seeded, reproducible)
oracle.py              privileged reference policy: proves every task is solvable (31/31, 51/51)
run_eval.py            score one config on one split, local loop or NeMo Gym rollout collection
ablate.py              baseline + one-knob-at-a-time variants -> results/ablations.md
stub_endpoint.py       offline OpenAI-compatible stand-in for vLLM (plumbing tests only)
NOTES_nemo_gym.md      how NeMo Gym works and how we plug into it
```

## Setup

```bash
gym/setup_nemo_gym.sh      # gym/.venv-nemo: Python 3.13.14 + nemo-gym==0.6.0; gym/.venv: openai, jsonschema, pytest
```

NeMo Gym is pinned to **v0.6.0** (released 2026-09-08). That is more than two weeks before the event, so it meets the open-source rule.

## Run scoring

```bash
# The model endpoint: vLLM serving Lightning (W1). Defaults to $OPERATOR_BASE_URL or http://localhost:8000/v1
gym/.venv/bin/python gym/run_eval.py --split heldout --run-name baseline                # local operator loop
gym/.venv/bin/python gym/run_eval.py --split heldout --run-name baseline-nemo --via nemo  # NeMo Gym rollouts
gym/.venv/bin/python gym/ablate.py --baseline-from gym/results/baseline                   # one-factor ablations

# No GPU: the stub endpoint exercises the same paths. Its numbers are a floor, NOT a model score.
gym/.venv/bin/python gym/run_eval.py --split heldout --run-name stub --stub [--via nemo]

gym/.venv/bin/python gym/oracle.py --split heldout      # every task solvable, scorer awards 1.0
gym/.venv/bin/python -m pytest -q gym/tests
```

Each run writes `results/<run_name>/summary.json` (pass rate, mean reward, by category, pass rate per check type, the full RunConfig, git commit, tools backend) and `per_task.jsonl` (reward, pass and each check's result and detail). The local runner also writes `transcripts/<task>.json` (the model's messages, the tool trace, what the renter saw). The NeMo runner keeps NeMo's own `rollouts.jsonl`, `*_aggregate_metrics.json` and logs under `nemo/`.

### Two runners, one scorer

- **local** (`--via local`, the default): `rentus_operator.run()` (W2's harness: prompt, tool-description variant, verifier, reader, retries, loop guard). Every tool call goes through `RolloutSession.call`. It's fast and every RunConfig knob applies.
- **nemo** (`--via nemo`): `gym env start` launches our resources server, NeMo's `simple_agent` and NeMo's `vllm_model` server, and `gym eval run --no-serve` collects the rollouts. This is NeMo Gym's own rollout and reward collection, which the bounty asks for. `simple_agent` is NeMo's harness, so the `verifier` knob doesn't apply on this path. Prompt, tool descriptions and reader do.

Both runners score with `rentus_env.verify` over the same trace format. On the stub, the two paths give the same held-out mean reward (0.2184).

## Task schema

The format is `contracts/tools.md` §7, plus a few fields:

```json
{"id": "lease-vague_date-heldout-001", "split": "heldout", "category": "leasing", "subcategory": "vague_date",
 "owner_instruction": "optional; listing and ops tasks",
 "initial_state": {"clock": {"now": "2026-10-21T10:00:00"}, "listings": [...], "vendors": {"$replace": [...]}, "policy": {...}},
 "counterparts": [{"id": "renter:hayden", "thread_id": "t_hayden", "channel": "marketplace", "language": "en",
                   "room_of_interest": "R026", "listing_id": "L_R026",
                   "script": [{"after": "start", "say": "is the room still available?"},
                              {"when_asked": "move_in", "say": "next month", "src": "syn-test-000412"},
                              {"when_asked": "move_in", "say": "on Dec 1st would be ideal", "src": "syn-test-000176"}]}],
 "faults": [{"tool": "publish_listing", "kind": "page_changed", "times": 1}],
 "max_turns": 30,
 "checks": [{"type": "state", "path": "register[t_hayden].gate.move_in.date", "equals": "2026-12-01", "normalize": "date"}, "..."]}
```

**Counterparts.** A counterpart's thread opens with its `after: start` lines. After each `send_message` to that thread, the operator's last question is classified as lease, move_in, phone, reason, occupants, showing or other (English and Spanish keyword rules in `counterparts.py`). The counterpart answers with the next unused line for that item, or with a `when_asked: "any"` line, or stays silent if nothing fits. The reply is appended to the thread and also returned as `data.replies` in the `send_message` result.

**Check types** (`verify.py`). Each check passes or fails. `reward = passed / total`, and a task passes when every check passes.

| type | passes when |
|---|---|
| `state` | a value in the final World equals / is in / contains / does not contain / exists / meets a count or numeric bound. Paths look like `register[t_x].gate.phone.value` or `listings[room_id=R003].price` |
| `never` | a tool is never attempted, never attempted before a condition (`before: gate_complete` for that thread, using the tools' own gate rule, or `before: tool:<name>`), or an item is never asked again on a thread (`asked`) |
| `style` | every message the operator attempted (blocked ones count too) keeps to max 2 sentences / one question / no long dash / the renter's language / first person |
| `tool_called` | a tool succeeded with matching args, min/max times, optionally over distinct values of one arg |
| `escalated` | an owner escalation exists (or doesn't), optionally matching ref and reason keywords |
| `budget` | booked spend stays at or under the policy limit, the number of tool calls stays under a cap, no failing call is repeated more than N times |
| `message` | text actually sent to a thread contains or avoids given phrases |

## Tasks

`build_tasks.py` writes these. Renter utterances come from the published reader set: **train tasks only from `data/published/reader/train.jsonl`, held-out tasks only from `test.jsonl`**, and the generator asserts there is no overlap. Each utterance's published label is the expected value. A task's clock is set to the `today` of its move-in row, so relative dates resolve the way the label says. Rooms are split too: train uses even inventory indexes, held-out uses odd ones. The template pools for openers, owner instructions and acknowledgements are disjoint between the splits.

| category | subcategories (train / held-out counts) |
|---|---|
| leasing (28 / 18) | full gate, vague date, Spanish, small talk, price push (escalate, rent unchanged), shorter-lease push (6-month floor), not now, hard no, skip ahead to scheduling, info volunteered out of order (don't re-ask) |
| listing (7 / 4) | owner instruction leads to a record update, compliance check before publishing, publish to 2–3 channels, report. Some tasks include a non-compliant phrase that must not reach the listing |
| ops (6 / 4) | create job, find vendors, 2+ quotes (one vendor never responds), book the cheapest responder at or under the limit, notify the tenant, report. In the over-limit tasks: no booking, escalate |
| recovery (10 / 5) | page_changed and login_required on publishing (publish elsewhere, escalate), rate_limited on the inbox, malformed get_room (don't quote garbage), timeout on a vendor quote |

## How improvements are isolated

The tasks (`tasks/heldout.jsonl`) and the scorer (`rentus_env/verify.py`) stay fixed. Held-out tasks are never used to tune prompts or train. The baseline is `RunConfig()`: prompt v1, verbose tool descriptions, verifier on, reader on, temperature 0.2. `ablate.py` reruns the held-out split with exactly one knob flipped per variant (prompt version, tool descriptions, verifier, reader, reasoning), so each row's delta is that knob's effect alone. Any new improvement (a prompt v2, a reader fine-tune, an operator LoRA) gets added as a new value of one knob and measured against the same baseline. Then the final config is run on the same held-out tasks with the same eval config. Train tasks are the ones to iterate on.

## Known limitations

- Counterparts match questions by keyword. An operator question phrased in an unusual way can get no reply, which shows up as an unanswered gate item.
- `never` and `budget` checks pass for an operator that does nothing. They are guards, and the action checks (`tool_called`, `state`) carry the signal. The stub's 0.22 floor comes from these guards.
- The stub endpoint is a plumbing test, not a model.
