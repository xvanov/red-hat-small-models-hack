"""ToolError: raised inside tool implementations, turned into the error envelope by call()."""
from __future__ import annotations

CODES = {
    "INVALID_ARGS", "NOT_FOUND", "CONFLICT", "RATE_LIMITED", "TIMEOUT", "LOGIN_REQUIRED",
    "PAGE_CHANGED", "UPSTREAM_ERROR", "POLICY_BLOCKED", "BUDGET_EXCEEDED",
}

# Default retryability per code (contracts/tools.md section 2). A ToolError may override it.
RETRYABLE = {
    "INVALID_ARGS": False, "NOT_FOUND": False, "CONFLICT": False, "RATE_LIMITED": True,
    "TIMEOUT": True, "LOGIN_REQUIRED": False, "PAGE_CHANGED": False, "UPSTREAM_ERROR": True,
    "POLICY_BLOCKED": False, "BUDGET_EXCEEDED": False,
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None, retryable: bool | None = None,
                 details: dict | None = None):
        assert code in CODES, code
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.retryable = RETRYABLE[code] if retryable is None else retryable
        self.details = details

    def envelope(self) -> dict:
        err = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.hint:
            err["hint"] = self.hint
        if self.details:
            err["details"] = self.details
        return {"ok": False, "error": err}


def ok(data) -> dict:
    return {"ok": True, "data": data}
