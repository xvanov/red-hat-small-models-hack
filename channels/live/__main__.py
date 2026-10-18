"""CLI for the live channels.

  .venv/bin/python -m channels.live                         run the daemon (poll forever)
  .venv/bin/python -m channels.live --once                  one poll + turns
  .venv/bin/python -m channels.live status                  channel status (no secrets)
  .venv/bin/python -m channels.live start sms|email|messenger <to> "<text>" [--line tollfree|local]
  .venv/bin/python -m channels.live deliveries               provider delivery status of recent sends
  .venv/bin/python -m channels.live messenger-whoami [--hours 2]   names + PSIDs in recently updated Page chats
  .venv/bin/python -m channels.live archive <thread_id|all>   hide threads (kept on disk); unarchive <thread_id>
  .venv/bin/python -m channels.live stop | resume            kill switch file runs/live/STOP
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="channels.live")
    ap.add_argument("cmd", nargs="?", default="run")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--line")
    ap.add_argument("--hours", type=float, default=2.0)
    a = ap.parse_args(argv)
    from . import api, config, outbound
    from .store import Store

    if a.cmd == "run":
        from .daemon import main as run
        return run(once=a.once)
    if a.cmd == "status":
        print(json.dumps(api.status(), indent=1))
        return 0
    if a.cmd == "start":
        if len(a.args) != 3:
            print(__doc__)
            return 2
        print(json.dumps(api.start_conversation(a.args[0], a.args[1], a.args[2], line=a.line), indent=1))
        return 0
    if a.cmd == "deliveries":
        st = Store()
        p = st.root / "sends.jsonl"
        rows = [r for r in (json.loads(x) for x in p.read_text().splitlines()[-40:]) if not r.get("reserved")] if p.exists() else []
        provs = outbound.get_providers()
        for r in rows:
            out = {k: r.get(k) for k in ("thread_id", "channel", "line", "ok", "provider_status", "error_code")}
            if r.get("channel") == "sms" and r.get("provider_id") and r.get("line") in provs["sms"]:
                out["delivery"] = provs["sms"][r["line"]].delivery(r["provider_id"])
            if r.get("channel") == "email" and r.get("ok") and provs.get("email"):
                t = st.get_thread(r["thread_id"]) or {}
                from datetime import datetime, timedelta, timezone
                ref = "[ref " + outbound.email_ref(t) + "]" if t else None
                out["delivery"] = {"in_test_inbox": provs["email"].find_delivered(
                    ref, datetime.now(timezone.utc) - timedelta(days=1))} if ref else None
            print(json.dumps(out))
        return 0
    if a.cmd == "messenger-whoami":
        for p in outbound.get_providers()["messenger"].recent_participants(a.hours):
            print(json.dumps(p, ensure_ascii=False))
        return 0
    if a.cmd in ("archive", "unarchive"):
        if len(a.args) != 1:
            print(__doc__)
            return 2
        fn = api.archive_thread if a.cmd == "archive" else api.unarchive_thread
        print(json.dumps(fn(a.args[0])))
        return 0
    if a.cmd in ("stop", "resume"):
        f = config.live_dir() / "STOP"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch() if a.cmd == "stop" else f.unlink(missing_ok=True)
        print(json.dumps({"send_enabled": config.send_enabled()}))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
