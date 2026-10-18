# operator/ (W2): agent loop, verifier, retries and fallbacks

`rentus_operator` runs the operator model (Nemotron 3.5 Lightning on vLLM) over an OpenAI-compatible chat-completions endpoint. The model talks and calls tools in the same turn. A deterministic verifier (plain code, no model) checks every call before it runs and every result after, decides retries and fallbacks, and confirms at the end that what the model claims it did actually happened.

## Quick start

```bash
cd operator
uv venv .venv && uv pip install --python .venv/bin/python -e . -e ../tools pytest
.venv/bin/python -m pytest -q                      # 37 offline tests, shim + real tools
.venv/bin/python -m rentus_operator.cli --stub "Appling Way room free Nov 1, \$750, private bath"
.venv/bin/python -m rentus_operator.cli "Appling Way room free Nov 1, \$750, private bath"   # live, needs the endpoint
```

Env (read from the repo `.env`, never printed): `OPERATOR_BASE_URL` (default `http://localhost:8000/v1`), `OPERATOR_MODEL` (default: first model the server lists), `OPERATOR_API_KEY`.

Each run writes `runs/<run_id>/events.jsonl` (contract §6).

## API

```python
from rentus_operator import run, RunConfig
res = run(world, "Appling Way room free Nov 1, $750, private bath",   # or an inbound dict:
          client=None,          # default: openai.OpenAI(base_url, api_key)   {"thread_id", "channel", "renter_name", "text"}
          config=RunConfig(prompt_version="v1", tool_descriptions="verbose", verifier=True, reader=True),
          sink=rentus_tools.EventSink.for_run(run_id), backend=rentus_tools,
          history=None)         # pass res.messages back in to continue the same conversation
res.status        # done | done_unverified | max_steps | model_error
res.final_text, res.ledger, res.escalations, res.self_check, res.messages, res.events
```

## Ablation knobs (`RunConfig`, one at a time for the Gym)

| Knob | Values | What changes |
|---|---|---|
| `prompt_version` | `v1`, ... | loads `prompts/system_<v>.md` |
| `tool_descriptions` | `verbose` / `terse` | `rentus_tools.tool_schemas(variant)` |
| `verifier` | on / off | off = raw calls: no repair, no result checks, no retries, no loop guard, no self-check |
| `reader` | on / off | on = `read_reply` tool + `prompts/reader_on.md`; off = tool removed, `reader_off.md` |
| `reasoning` | None / True / False | sent as `chat_template_kwargs.enable_thinking` |
| `router` | off / on | on = triage router (`router.py`): the 0.6B reader reads every inbound renter message first; easy events skip Lightning or shrink its turn; Lightning still writes every renter reply. Adds `prompts/router_on.md`. See below |

## Files

| File | What it does |
|---|---|
| `prompts/system_v1.md` | system prompt: first person as the owner, 2 sentences max, one question at a time, no long dashes, renter's language, strict 5-item gate with exact answers, never commit without the owner, listing and ops procedures |
| `rentus_operator/loop.py` | the loop: calls the model, strips reasoning (separate field or inline `<think>`), recovers tool calls left in text (JSON or qwen3_coder XML), runs parallel calls in order, self-check before ending |
| `rentus_operator/router.py` | triage router + `run_conversation()`, the event-driven driver used when `router` is on |
| `rentus_operator/verifier.py` | pre-call checks + one JSON repair pass, result shape checks (contract §3 to §5), retry policy, loop guard, self-check |
| `rentus_operator/toolbox.py` | adapter: real `rentus_tools` when importable, else `shim.py` |
| `rentus_operator/stub_model.py` | scripted fake OpenAI client for offline tests |
| `rentus_operator/cli.py` | one instruction against the sandbox, readable trace |
| `fixtures/appling_way.json` | fictional Appling Way room, added to the world only if none exists (the demo instruction) |

## Verifier policy

| Situation | What happens |
|---|---|
| unknown tool, bad JSON, schema mismatch | trivial damage (code fences, trailing commas, single quotes, Python literals, missing closing brace, `"750"` for a number) is repaired once; anything else goes back to the model as structured feedback and is not executed |
| `RATE_LIMITED`, `TIMEOUT`, `UPSTREAM_ERROR`, malformed result | retried with backoff 0.5 s, 1 s (max 2), then feedback |
| `request_quote` `TIMEOUT` | fallback: ask the next vendor |
| `PAGE_CHANGED`, `LOGIN_REQUIRED` | fallback: feedback lists the channels not tried yet and says to escalate the broken one |
| `POLICY_BLOCKED`, `BUDGET_EXCEEDED` | no retry; the model gets the reason and hint; repeating the identical call is refused without running it |
| the same failing call 3 times | verifier itself calls `escalate_to_owner` and tells the model to stop |
| step limit reached | forced escalation |
| final answer | every successful call must show in the world, and claims in the summary ("published on X", "booked", "proposed a showing", "escalated", "I sent") must match new state; on a mismatch the model gets one chance to fix it, otherwise the run ends `done_unverified` |

## Triage router (`RunConfig(router=True)`, default off)

Every inbound renter message is routed before Lightning sees it. The reader (`read_reply`, the 0.6B model at `READER_BASE_URL`) reads it, cheap deterministic signals run next to it, and one decision is logged as a `verifier` event with actor `router` (`data.stage = "router"`):

| decision | when | what happens |
|---|---|---|
| `NO_OP` | platform system text ("X reacted to your message"), a duplicate, or an emoji-only / thank-you ack while our last message asked nothing | nothing; Lightning is not called |
| `RECORD_ONLY` | pure data: every field the reader found is high-confidence (the model reader and the rule reader agree, the value validates) and there is no intent | code writes it with `upsert_renter` (actor `router`); Lightning is called only if a reply is owed (it is, unless the renter's file is closed and they asked nothing) |
| `BATCH` | 2+ renter messages before we answered | each is read, the parses are merged, one Lightning turn |
| `ESCALATE_DIRECT` | hard no (both readers agree) or abuse | code escalates to the owner with the reader's summary; a hard no is marked `lost` and Lightning writes the one courteous close; abuse gets no reply |
| `LIGHTNING` | everything else | one Lightning turn |

When Lightning is called, its turn opens with a `[router]` note (the reader's parse, what code already recorded, the gate items still missing) and ends, without another model call, the moment its `send_message` to the thread succeeds. The renter's answer is the next routed event. The router never sends a renter anything. If the model reader is down (`read_reply` fell back to rules), nothing counts as high-confidence and every message goes to Lightning. `router_quiet_s` is the live-inbox quiet window that turns a burst into one BATCH (the Gym's renters answer instantly, so it is 0 there).

## Known limitations

- Self-check reads English claims only; a Spanish summary is not checked.
- Parallel tool calls run one after another, in order.
- The live endpoint has not been tested yet (it was down while this was written).
