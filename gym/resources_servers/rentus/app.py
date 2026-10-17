"""NeMo Gym resources server for the Rentus Operator sandbox.

Tools: every rentus_tools tool is a POST route `/<tool_name>` (the simple_agent posts each function
call there). The body is the tool's JSON arguments; the response is the contract's result envelope.
State: /seed_session builds a fresh World + scripted counterparts for the rollout's task (one
RolloutSession per Gym session id). verify(): runs gym/rentus_env/verify.py over that session's
trace and final state. reward = fraction of checks passed; task_pass = 1.0 when all pass.

The same rentus_env code backs gym/run_eval.py's local loop, so both paths score identically.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

GYM = Path(__file__).resolve().parents[2]
REPO = GYM.parent
for p in (GYM, REPO / "tools", REPO / "operator"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import FastAPI, Request  # noqa: E402
from pydantic import ConfigDict, Field  # noqa: E402

from nemo_gym.base_resources_server import (  # noqa: E402
    BaseResourcesServerConfig,
    BaseSeedSessionRequest,
    BaseSeedSessionResponse,
    BaseVerifyRequest,
    BaseVerifyResponse,
    SimpleResourcesServer,
)
from nemo_gym.server_utils import SESSION_ID_KEY  # noqa: E402

from rentus_env import RolloutSession, verify  # noqa: E402
from rentus_env.backend import Backend  # noqa: E402


class RentusResourcesServerConfig(BaseResourcesServerConfig):
    tools_backend: str = "auto"      # auto | tools | shim
    surface_replies: bool = True     # renter replies come back inside the send_message result


class RentusSeedSessionRequest(BaseSeedSessionRequest):
    model_config = ConfigDict(extra="allow")
    task: Dict[str, Any]


class RentusVerifyRequest(BaseVerifyRequest):
    model_config = ConfigDict(extra="allow")
    task: Dict[str, Any]


class RentusVerifyResponse(BaseVerifyResponse):
    model_config = ConfigDict(extra="allow")
    task_pass: float
    checks_passed: int
    checks_total: int
    tool_calls: int
    category: Optional[str] = None
    checks: List[Dict[str, Any]] = Field(default_factory=list)


def _final_text(response) -> str:
    out = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
            for c in getattr(item, "content", None) or []:
                t = getattr(c, "text", None)
                if t:
                    out.append(t)
    return "\n".join(out)


_BACKEND: Backend | None = None


class RentusResourcesServer(SimpleResourcesServer):
    config: RentusResourcesServerConfig
    sessions: Dict[str, Any] = Field(default_factory=dict)

    def setup_webserver(self) -> FastAPI:
        global _BACKEND
        app = super().setup_webserver()
        _BACKEND = Backend(self.config.tools_backend)
        for name in _BACKEND.tool_names():
            app.post(f"/{name}")(self._tool_route(name))
        return app

    def _tool_route(self, name: str):
        async def route(request: Request) -> dict:
            sid = request.session[SESSION_ID_KEY]
            s = self.sessions.get(sid)
            if s is None:
                return {"ok": False, "error": {"code": "NOT_FOUND", "message": "no session; seed_session first",
                                               "retryable": False}}
            try:
                args = await request.json()
            except Exception:  # noqa: BLE001
                args = "<<invalid json>>"
            return s.call(name, args)
        route.__name__ = f"tool_{name}"
        return route

    async def seed_session(self, request: Request, body: RentusSeedSessionRequest) -> BaseSeedSessionResponse:
        sid = request.session[SESSION_ID_KEY]
        self.sessions[sid] = RolloutSession(body.task, backend=_BACKEND,
                                            surface_replies=self.config.surface_replies)
        return BaseSeedSessionResponse()

    async def verify(self, request: Request, body: RentusVerifyRequest) -> RentusVerifyResponse:
        sid = request.session[SESSION_ID_KEY]
        s = self.sessions.pop(sid, None)
        if s is None:
            r = {"reward": 0.0, "pass": False, "checks_passed": 0, "checks_total": len(body.task.get("checks", [])),
                 "tool_calls": 0, "category": body.task.get("category"), "checks": []}
        else:
            r = verify(body.task, s.trace, s.final_state(), _final_text(body.response))
        return RentusVerifyResponse(**body.model_dump(), reward=r["reward"], task_pass=float(r["pass"]),
                                    checks_passed=r["checks_passed"], checks_total=r["checks_total"],
                                    tool_calls=r["tool_calls"], category=r["category"], checks=r["checks"])


if __name__ == "__main__":
    RentusResourcesServer.run_webserver()
