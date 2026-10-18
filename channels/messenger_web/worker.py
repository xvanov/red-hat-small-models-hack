"""The browser worker: the only process that drives the owner's logged-in facebook.com/messages session.

It polls the inbox at a human pace, writes what it reads to runs/live/messenger_web/threads.json, and executes
send requests that the adapter drops into runs/live/messenger_web/outbox/. One process owns the browser profile,
so the daemon and the console never launch Playwright themselves (the adapter is pure file I/O).

Safety:
  * on a login page, checkpoint or captcha it stops reading, sets status "login_required" and never interacts;
  * the only elements it ever clicks are the message box of the thread it is sending to (then Enter);
  * sends happen only for outbox requests (the adapter writes them after outbound.deliver's gates passed);
  * worker-side cap MESSENGER_WEB_MAX_SENDS_HOUR, kill switch runs/live/STOP honored here too.
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from pathlib import Path

from . import common as C


class LoginRequired(Exception):
    pass


# ====================================================================== page helpers (testable without a login)

def detect_wall(page, S: dict) -> dict:
    return page.evaluate(C.EXTRACT_JS, {"fn": "wall", "S": S})


def read_thread_list(page, S: dict) -> list[dict]:
    return page.evaluate(C.EXTRACT_JS, {"fn": "threads", "S": S})


def read_messages(page, S: dict, other_name: str | None = None) -> dict:
    res = page.evaluate(C.EXTRACT_JS, {"fn": "thread", "S": S})
    msgs = res.get("messages") or []
    # incoming groups can carry the sender's name as a text line above the bubbles
    names = {C.norm_name(other_name), C.norm_name((other_name or "").split(" ")[0])} - {""}
    msgs = [m for m in msgs if not (m["dir"] == "in" and C.norm_name(m["text"]) in names)]
    res["messages"] = [{"dir": m["dir"], "text": m["text"], "mid": m.get("mid")} for m in msgs]
    return res


def unanswered_tail(messages: list[dict]) -> list[dict]:
    """Inbound messages after the last outbound one (what still needs a reply)."""
    tail = []
    for m in messages:
        if m["dir"] == "out":
            tail = []
        else:
            tail.append(m)
    return tail


# ====================================================================== worker

class Worker:
    def __init__(self, page=None, root: Path | None = None, *, sleep=time.sleep, clock=time.time):
        self.page = page
        self.S = C.selectors()
        self.root = Path(root) if root else C.data_dir()
        C.assert_private(self.root)
        (self.root / "outbox").mkdir(parents=True, exist_ok=True)
        self.sleep = sleep
        self.clock = clock
        self.poll_s = C.env_num("MESSENGER_WEB_POLL_SECONDS", 30, floor=20)
        self.max_threads = int(C.env_num("MESSENGER_WEB_MAX_THREADS", 5))
        self.backlog_h = C.env_num("MESSENGER_WEB_BACKLOG_HOURS", 48)
        self.opens_per_poll = int(C.env_num("MESSENGER_WEB_OPENS_PER_POLL", 3))
        self.max_sends_hour = int(C.env_num("MESSENGER_WEB_MAX_SENDS_HOUR", 10))
        self.state = "starting"
        self.detail = ""
        self.last_poll = None

    # ---------------------------------------------------------------- files
    @property
    def threads_path(self) -> Path:
        return self.root / "threads.json"

    def threads(self) -> dict:
        return C.read_json(self.threads_path, {}) or {}

    def write_status(self, **extra) -> None:
        st = {"state": self.state, "detail": self.detail, "heartbeat": C.now_iso(), "heartbeat_epoch": self.clock(),
              "last_poll": self.last_poll, "threads": len(self.threads()), "pid": os.getpid()}
        st.update(extra)
        C.write_json(self.root / "status.json", st)

    def _log_send(self, row: dict) -> None:  # audit without message text
        with open(self.root / "sends.jsonl", "a") as fh:
            fh.write(json.dumps({"ts": C.now_iso(), "epoch": self.clock(), **row}) + "\n")

    def sends_last_hour(self) -> int:
        p = self.root / "sends.jsonl"
        if not p.exists():
            return 0
        cut = self.clock() - 3600
        n = 0
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("ok") and r.get("epoch", 0) >= cut:
                n += 1
        return n

    # ---------------------------------------------------------------- navigation
    def _pause(self, lo: float, hi: float) -> None:
        self.sleep(random.uniform(lo, hi))

    def _goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self._pause(2.5, 4.5)  # let the client app render
        w = detect_wall(self.page, self.S)
        if w.get("wall"):
            raise LoginRequired(w.get("reason", "login wall"))

    def check(self) -> dict:
        """Open the inbox once; report login state and thread count (no content)."""
        try:
            self._goto(self.S["inbox_url"])
        except LoginRequired as e:
            return {"state": "login_required", "detail": str(e)}
        rows = read_thread_list(self.page, self.S)
        return {"state": "ok", "threads_visible": len(rows), "marketplace_threads": sum(r["marketplace"] for r in rows)}

    # ---------------------------------------------------------------- read
    def poll_once(self) -> dict:
        self._goto(self.S["inbox_url"])
        rows = read_thread_list(self.page, self.S)[: self.max_threads]
        db = self.threads()
        changed = []
        for r in rows:
            t = db.get(r["thread_id"])
            age_h = C.age_hours(r.get("age"))
            sig = f"{r['name']}|{r['snippet']}"
            if t is None:
                if age_h is not None and age_h > self.backlog_h:
                    continue  # old chat: never opened, never surfaced
                href = r.get("href") or ""
                url = ("https://www.facebook.com" + href) if href.startswith("/") else \
                    self.S["thread_url"].format(thread_id=r["thread_id"])
                db[r["thread_id"]] = t = {"thread_id": r["thread_id"], "name": r["name"],
                                          "listing_title": r["listing_title"], "marketplace": r["marketplace"],
                                          "url": url, "row_sig": None, "age_h": None, "messages": [],
                                          "first_seen": C.now_iso()}
            t["name"] = r["name"] or t.get("name")
            t["listing_title"] = r["listing_title"] or t.get("listing_title")
            t["marketplace"] = bool(r["marketplace"] or t.get("marketplace"))
            t["list_rank"] = rows.index(r)
            # e2ee rows show a fixed snippet, so new activity shows up as the age getting smaller
            newer = age_h is not None and t.get("age_h") is not None and age_h < t["age_h"] - 1e-6
            if t.get("row_sig") != sig or newer:
                changed.append((r["thread_id"], sig))
            t["age_h"] = age_h
        C.write_json(self.threads_path, db)
        opened = 0
        for tid, sig in changed[: self.opens_per_poll]:
            self._pause(3, 7)
            self._read_thread(tid, sig)
            opened += 1
        self.last_poll = C.now_iso()
        return {"rows": len(rows), "changed": len(changed), "opened": opened}

    def _read_thread(self, tid: str, sig: str | None) -> None:
        db = self.threads()
        t = db[tid]
        self._goto(t["url"])
        res = read_messages(self.page, self.S, t.get("name"))
        if res.get("thread_id") and res["thread_id"] != tid:
            return  # redirected elsewhere: don't attribute these messages to this thread
        msgs = res["messages"]
        ids = C.message_ids(tid, msgs)
        known = {m["ext_id"]: m for m in t.get("messages", [])}
        now = C.now_iso()
        merged = []
        for m, mid in zip(msgs, ids):
            old = known.get(mid)
            merged.append({"ext_id": mid, "dir": m["dir"], "text": m["text"],
                           "first_seen": old["first_seen"] if old else now})
        db = self.threads()  # re-read: keep the latest list metadata
        t = db[tid]
        if merged or not t.get("messages"):
            t["messages"] = merged
        t["row_sig"] = sig
        t["read_at"] = now
        if res.get("header") and not t.get("name"):
            t["name"] = res["header"]
        C.write_json(self.threads_path, db)

    # ---------------------------------------------------------------- send
    def _claim_next(self) -> Path | None:
        for p in sorted((self.root / "outbox").glob("*.pending.json")):
            claimed = p.with_name(p.name.replace(".pending.json", ".claimed.json"))
            try:
                os.rename(p, claimed)  # atomic: the adapter can no longer cancel it
                return claimed
            except FileNotFoundError:
                continue
        return None

    def process_outbox(self) -> int:
        n = 0
        while True:
            p = self._claim_next()
            if p is None:
                return n
            req = C.read_json(p, {})
            res = self.send(req.get("thread_id", ""), req.get("text", ""))
            done = p.with_name(p.name.replace(".claimed.json", ".done.json"))
            C.write_json(done, {**req, "text": None, "result": res, "done_at": C.now_iso()})
            p.unlink(missing_ok=True)
            n += 1

    def send(self, tid: str, text: str) -> dict:
        def fail(err, code="failed"):
            self._log_send({"thread_id": tid, "ok": False, "error_code": code})
            return {"ok": False, "provider_id": None, "status": "failed", "error_code": code, "error": err}

        text = (text or "").strip()
        if not text:
            return fail("empty message", "empty")
        if (Path(C.env("LIVE_DIR") or (C.REPO / "runs" / "live")) / "STOP").exists():
            return fail("kill switch runs/live/STOP is set", "stopped")
        if self.sends_last_hour() >= self.max_sends_hour:
            return fail(f"worker send cap reached ({self.max_sends_hour}/hour)", "rate_cap")
        t = self.threads().get(tid)
        if t is None:
            return fail("unknown thread (never read by the worker)", "unknown_thread")
        try:
            self._goto(t["url"])
        except LoginRequired as e:
            self.state, self.detail = "login_required", str(e)
            self.write_status()
            return fail("login required: " + str(e), "login_required")
        res = read_messages(self.page, self.S, t.get("name"))
        if res.get("thread_id") != tid:
            return fail("thread page did not open (id mismatch)", "wrong_thread")
        before_outs = [m["text"] for m in res["messages"] if m["dir"] == "out"]
        box = None
        for sel in self.S["composer"]:
            loc = self.page.locator(sel)
            if loc.count() == 1 and loc.first.is_visible():
                box = loc.first
                break
        if box is None:
            return fail("message box not found", "page_changed")
        if C.norm_text(box.inner_text()):
            return fail("message box already has text (owner typing?); not touching it", "box_busy")
        box.click()
        self._pause(0.6, 1.4)
        lines = text.split("\n")
        for i, line in enumerate(lines):
            self.page.keyboard.type(line, delay=random.randint(35, 85))
            if i < len(lines) - 1:
                self.page.keyboard.press("Shift+Enter")
        self._pause(0.5, 1.2)
        if C.norm_text(box.inner_text()) != C.norm_text(text):
            # never send something other than the approved text: clear the box and report
            box.press("Control+A")
            box.press("Backspace")
            return fail("typed text did not match the approved text; cleared, not sent", "typing_mismatch")
        self.page.keyboard.press("Enter")
        # verify: a new outgoing message with this text appears
        want = C.norm_text(text)
        for _ in range(10):
            self.sleep(1.5)
            after = read_messages(self.page, self.S, t.get("name"))["messages"]
            outs = [m["text"] for m in after if m["dir"] == "out"]
            joined = C.norm_text(" ".join(outs[-len(lines) - 1:]))
            new = len(outs) > len(before_outs) or (outs and before_outs and outs[-1] != before_outs[-1])
            if outs and new and joined.endswith(want[-80:]):
                ids = C.message_ids(tid, after)
                self._log_send({"thread_id": tid, "ok": True, "verified": True})
                return {"ok": True, "provider_id": ids[-1] if ids else None, "status": "sent", "error_code": None,
                        "error": None}
        if not C.norm_text(box.inner_text()):
            self._log_send({"thread_id": tid, "ok": True, "verified": False})
            return {"ok": True, "provider_id": None, "status": "sent_unverified", "error_code": "unverified",
                    "error": "box cleared after Enter but the bubble was not found in the thread"}
        return fail("pressed Enter but the message stayed in the box", "not_sent")

    # ---------------------------------------------------------------- loop
    def run(self, stop_after: int | None = None) -> None:
        polls = 0
        next_poll = 0.0
        login_wait_until = 0.0
        while stop_after is None or polls < stop_after:
            now = self.clock()
            if now >= next_poll and now >= login_wait_until:
                try:
                    r = self.poll_once()
                    self.state, self.detail = "running", f"{r['rows']} threads in view, {r['opened']} opened"
                except LoginRequired as e:
                    self.state, self.detail = "login_required", (
                        f"{e}. Run: channels/.venv/bin/python -m channels.messenger_web login")
                    login_wait_until = now + 300  # look again in 5 minutes, never interact
                except Exception as e:  # keep running; report
                    self.state, self.detail = "error", f"{type(e).__name__}: {str(e)[:200]}"
                polls += 1
                next_poll = self.clock() + self.poll_s + random.uniform(0, 8)
                self.write_status()
            if self.state != "login_required":
                try:
                    if self.process_outbox():
                        self.write_status()
                except Exception as e:
                    self.detail = f"send error {type(e).__name__}: {str(e)[:200]}"
            if int(self.clock()) % 15 == 0:
                self.write_status()
            self.sleep(1.0)


def new_request_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
