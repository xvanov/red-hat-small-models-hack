"""RunConfig: every knob the Gym ablations flip, one at a time."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass(frozen=True)
class RunConfig:
    # ablation knobs
    prompt_version: str = "v1"            # prompts/system_<version>.md
    tool_descriptions: str = "verbose"    # "verbose" | "terse"
    verifier: bool = True                 # deterministic verifier on/off
    reader: bool = True                   # expose read_reply + reader rules in prompt

    # model / endpoint
    model: str = field(default_factory=lambda: os.environ.get("OPERATOR_MODEL", "nemotron"))
    base_url: str = field(default_factory=lambda: os.environ.get("OPERATOR_BASE_URL", "http://localhost:8000/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("OPERATOR_API_KEY", "EMPTY"))
    temperature: float = 0.2
    max_tokens: int = 2048
    reasoning: bool | None = None         # None = server default; True/False sent as chat_template_kwargs
    keep_reasoning_in_history: bool = False

    # loop limits
    max_steps: int = 30
    max_retries: int = 2                  # retries per call for retryable errors
    backoff_base_s: float = 0.5
    loop_guard_repeats: int = 3           # same failing call N times -> force escalate
    self_check_rounds: int = 1            # how many times to bounce a false final claim back

    def with_(self, **kw) -> "RunConfig":
        return replace(self, **kw)

    def label(self) -> str:
        return (f"prompt={self.prompt_version} tools={self.tool_descriptions} "
                f"verifier={'on' if self.verifier else 'off'} reader={'on' if self.reader else 'off'}")


def load_prompt(cfg: RunConfig, world_facts: dict) -> str:
    template = (PROMPTS_DIR / f"system_{cfg.prompt_version}.md").read_text()
    reader = (PROMPTS_DIR / ("reader_on.md" if cfg.reader else "reader_off.md")).read_text().strip()
    facts = {"today": "unknown", "spend_limit_usd": "unknown", "showing_hours": "8 AM to 8 PM",
             **{k: v for k, v in world_facts.items() if v is not None}}
    return template.replace("{reader_rules}", reader).format(**facts)
