"""A deterministic stand-in for the vLLM endpoint (OpenAI chat-completions), for plumbing tests
when no GPU is up. NOT a model and never scored as one: it reads the inbox, opens the first
thread, and stops. It lets `run_eval.py --via nemo` exercise NeMo Gym's full rollout path
(agent -> model server -> tool routes on our resources server -> verify) offline.

    python gym/stub_endpoint.py --port 8011     # then OPERATOR_BASE_URL=http://127.0.0.1:8011/v1
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def policy(messages: list[dict], tools: list[dict]) -> dict:
    names = {(t.get("function") or t).get("name") for t in tools or []}
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    if not tool_msgs and "list_threads" in names:
        return {"tool": ("list_threads", {"unanswered_only": True})}
    if len(tool_msgs) == 1:
        try:
            env = json.loads(tool_msgs[0]["content"])
            threads = (env.get("data") or {}).get("threads") or []
        except (json.JSONDecodeError, TypeError, AttributeError):
            threads = []
        if threads and "read_thread" in names:
            return {"tool": ("read_thread", {"thread_id": threads[0]["thread_id"]})}
    return {"content": "I checked the inbox. Nothing else to do from the stub."}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": "stub", "object": "model", "owned_by": "gym"}]})
        if self.path.rstrip("/").endswith("/health"):
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": f"stub serves /v1/chat/completions only, not {self.path}"})
        act = policy(body.get("messages") or [], body.get("tools") or [])
        msg = {"role": "assistant", "content": act.get("content")}
        finish = "stop"
        if "tool" in act:
            name, args = act["tool"]
            msg["content"] = None
            msg["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(args)}}]
            finish = "tool_calls"
        self._send(200, {"id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion",
                         "created": int(time.time()), "model": body.get("model", "stub"),
                         "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                         "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def serve(port: int):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    serve(ap.parse_args().port)
