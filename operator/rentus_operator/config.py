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
    renter_guard: bool = False            # P2.1 (a): a renter-facing run may not end on plain text while the
                                          # renter's last message is unanswered; the harness bounces it back
    renter_guard_rounds: int = 3          # max bounces per run
    burst_guard: bool = False             # renter guard also bounces a run that ends with the renter holding no
                                          # question while gate items are missing (not closed/parked/escalated);
                                          # shares renter_guard_rounds, needs renter_guard on
    guard_stand_down: bool = False        # renter guard does not bounce a run on a thread the owner took over
                                          # (thread owner_owned / stand_down), where the agent must send nothing
    format_facts: bool = False            # P2.1 (g): showing hours rendered "10:00 to 18:00" as the NeMo rows do,
                                          # instead of the raw policy dict
    style_precheck: bool = False          # P2.1 (d): verifier checks send_message style rules BEFORE the call and
                                          # returns a rewrite request instead of sending (needs verifier on)
    router: bool = False                  # triage router (rentus_operator.router): the reader reads every inbound
                                          # renter message first; NO_OP / RECORD_ONLY / BATCH / ESCALATE_DIRECT skip or
                                          # shrink Lightning's turn; renter replies are still written only by Lightning
    router_quiet_s: float = 0.0           # live inbox: wait this long after a renter's last message before routing,
                                          # so a burst is one BATCH (the Gym's renters answer instantly: 0)

    # model / endpoint
    model: str = field(default_factory=lambda: os.environ.get("OPERATOR_MODEL", "nemotron"))
    base_url: str = field(default_factory=lambda: os.environ.get("OPERATOR_BASE_URL", "http://localhost:8000/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("OPERATOR_API_KEY", "EMPTY"))
    temperature: float = 0.2
    max_tokens: int = 2048
    api: str = "openai"                   # "openai" (vLLM, the running system) | "anthropic" (REFERENCE ONLY:
                                          # frontier model via anthropic_client.py, never part of the system)
                                          # | "claude_code" (REFERENCE ONLY: frontier model via the local Claude
                                          # Code CLI + Agent SDK, native tool use; claude_code.py)
    effort: str | None = None             # api=anthropic/claude_code only: output_config.effort (None = adapter default "high")
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
        out = (f"prompt={self.prompt_version} tools={self.tool_descriptions} "
               f"verifier={'on' if self.verifier else 'off'} reader={'on' if self.reader else 'off'}")
        if self.renter_guard:
            out += " renter_guard=on"
        if self.burst_guard:
            out += " burst_guard=on"
        if self.guard_stand_down:
            out += " guard_stand_down=on"
        if self.style_precheck:
            out += " style_precheck=on"
        if self.format_facts:
            out += " format_facts=on"
        if self.keep_reasoning_in_history:
            out += " reasoning_history=on"
        if self.router:
            out += " router=on"
        if self.api != "openai":
            out += f" api={self.api} model={self.model}" + (f" effort={self.effort}" if self.effort else "")
        if self.reasoning is not None:
            out += f" reasoning={'on' if self.reasoning else 'off'}"
        return out


def load_prompt(cfg: RunConfig, world_facts: dict) -> str:
    template = (PROMPTS_DIR / f"system_{cfg.prompt_version}.md").read_text()
    reader = (PROMPTS_DIR / ("reader_on.md" if cfg.reader else "reader_off.md")).read_text().strip()
    if cfg.router:
        reader += "\n" + (PROMPTS_DIR / "router_on.md").read_text().strip()
    if cfg.format_facts and isinstance(world_facts.get("showing_hours"), dict):
        sh = world_facts["showing_hours"]
        world_facts = {**world_facts, "showing_hours": f"{sh.get('start')} to {sh.get('end')}"}
    facts = {"today": "unknown", "spend_limit_usd": "unknown", "showing_hours": "8 AM to 8 PM",
             **{k: v for k, v in world_facts.items() if v is not None}}
    return template.replace("{reader_rules}", reader).format(**facts)
