# NeMo Gym: what we use and how it works

Source: https://github.com/NVIDIA-NeMo/Gym (Apache-2.0). **Pinned: v0.6.0** (tag 2026-09-08, PyPI `nemo-gym==0.6.0` uploaded 2026-09-09), which is more than two weeks before the event (cutoff Oct 3). v0.7.0 (Oct 8–12) is too new, so we do not use it.

## Install

NeMo Gym needs Python >= 3.13.14 and `uv`. Our system uv (0.10.7) cannot download 3.13.14, so `gym/setup_nemo_gym.sh` uses a newer uv through `uvx` only to fetch the interpreter, then installs `nemo-gym==0.6.0` into `gym/.venv-nemo` (gitignored). That venv provides the `gym` CLI plus the built-in `simple_agent` and `vllm_model` servers. When `gym env start` launches our resources server it builds that server its own venv at `resources_servers/rentus/.venv`, from `requirements.txt`, with `nemo-gym==0.6.0` from PyPI.

## The three servers

An environment run is three HTTP servers plus a head server, all started by `gym env start` and wired together by YAML config:

1. **Resources server** (ours, `resources_servers/rentus/app.py`): the environment. It subclasses `nemo_gym.base_resources_server.SimpleResourcesServer` and provides:
   - **tools**: one `POST /<tool_name>` route per tool. The agent posts each function call's JSON arguments there, and whatever the route returns becomes the tool output the model sees. We register one route for every `rentus_tools` tool.
   - **`/seed_session`**: called once per rollout with the whole dataset row. Session state is keyed by `request.session[SESSION_ID_KEY]`, a signed cookie the agent carries through every call of that rollout. This is where we build the rollout's own World and its scripted counterparts.
   - **`/verify`**: called at the end with the dataset row and the agent's final `response`. It returns `BaseVerifyResponse` with `reward: float` and any other fields. Extra top-level numeric fields (our `task_pass`, `checks_passed`) are averaged into the aggregate metrics automatically.
   - `/aggregate_metrics` (inherited) computes `mean/<field>`, pass@k and so on from the verify responses.
2. **Agent server** (built-in `responses_api_agents/simple_agent`): the harness. `run()` calls `seed_session`, then loops: it asks the model through the Responses API, posts every `function_call` to the resources server at `/<name>`, appends a `function_call_output`, and stops when the model answers with a message and no tool calls, or when it reaches `max_steps`. Then it calls `verify`.
3. **Model server** (built-in `responses_api_models/vllm_model`): it turns Responses API requests into vLLM `POST /v1/chat/completions` calls, so vLLM's own `--tool-call-parser` and `--reasoning-parser` do the parsing. Config: `base_url`, `api_key`, `model`, set from `--model-url`, `--model-api-key` and `--model` (`policy_base_url`, `policy_api_key` and `policy_model_name` in the config). It works with any OpenAI-compatible endpoint, which is how our offline stub endpoint plugs in.

## Task JSONL format

Each line is one task. It must contain `responses_create_params` (the OpenAI Responses request: `input` messages, `tools` in the flat Responses form `{"type":"function","name","description","parameters","strict"}`, plus `temperature` and `max_output_tokens`). Every other key (for us `task` and `task_id`) passes through untouched to `seed_session` and `verify`. Our rows are written by `run_eval.nemo_rows()`: the operator's system prompt for the chosen RunConfig, the same opening turn the local loop uses, and the tool schemas in the chosen description variant.

Datasets are declared on the agent in the config (`datasets: [{name, type: train|validation|example, jsonl_fpath, license}]`). `license` must come from NeMo Gym's fixed list. Ours is `CC BY-SA 4.0`, inherited from the reader set's SGD rows.

## Collecting rollouts and rewards

```bash
gym env start --config resources_servers/rentus/configs/rentus.yaml --model-type vllm_model \
    --model <name> --model-url http://localhost:8000/v1 --model-api-key EMPTY
gym eval run --no-serve --agent rentus_simple_agent --input <rows.jsonl> --output <rollouts.jsonl> --num-repeats 1
```

`gym eval run` without `--no-serve` starts the servers itself but accepts only the prepared dataset split, not an `--input` file. We pass a per-config input file, so we start the servers ourselves and use `--no-serve`. The outputs are `<out>.jsonl` (one verify response per rollout, which includes `reward`, `task_pass` and the per-check list), `<out>_materialized_inputs.jsonl` and `<out>_aggregate_metrics.json` (`mean/reward`, `mean/task_pass`, ...). `gym eval profile` gives per-task pass rates.

## How this maps to the bounty

"Tasks, tools the agent can use, and code that scores each attempt" correspond to `tasks/*.jsonl`, the tool routes and `verify()`. "Baseline vs final on the same held-out tasks and eval config" is `ablate.py`, which changes one RunConfig factor at a time while the tasks and the verifier stay fixed (the slides' ablation model: tasks fixed, agent varied, verifier fixed).

## Caveats we hit

- `error_on_almost_servers`: an invalid dataset `license` silently turns the agent into an "almost-server" and aborts the run.
- The simple_agent has no verifier, retries or loop guard. Those belong to our operator harness, so the `verifier` RunConfig knob applies only to the local runner. Prompt, tool descriptions and reader apply to both.
- Renter replies arrive inside the `send_message` result (`data.replies`) because the harness has no inbox clock. The local runner does the same, so both runners score the same way.
