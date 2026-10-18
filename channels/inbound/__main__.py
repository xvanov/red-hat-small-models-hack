"""Owner CLI for the inbound channels. Nothing here sends a message.

  python -m channels.inbound email-check                    # which IMAP settings are present (names only)
  python -m channels.inbound email-poll [--since-days 14]   # read-only IMAP fetch -> threads (needs CHANNELS_IMAP_CONFIRMED=1)
  python -m channels.inbound email-import FILE.eml ...      # parse saved .eml files into threads
  python -m channels.inbound sms-add --phone N --text T [--name X]   # record an inbound text by hand
  python -m channels.inbound threads [--channel email|sms]  # thread list (ids, platform, message count)
  python -m channels.inbound drafts [--channel email|sms]   # the drafts outbox
"""
from __future__ import annotations

import argparse
import json
import sys

from .email_channel import ingest_files, ingest_lead
from .imap_reader import ImapConfig, ImapNotConfigured, config_status, fetch_leads
from .sms import ingest_text
from .store import ChannelStore


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m channels.inbound")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("email-check")
    p = sub.add_parser("email-poll")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--all-senders", action="store_true", help="scan every sender, not only platform domains")
    p = sub.add_parser("email-import")
    p.add_argument("files", nargs="+")
    p = sub.add_parser("sms-add")
    p.add_argument("--phone", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--name")
    for name in ("threads", "drafts"):
        p = sub.add_parser(name)
        p.add_argument("--channel", choices=["email", "sms"])
    a = ap.parse_args(argv)
    store = ChannelStore()

    if a.cmd == "email-check":
        print(json.dumps(config_status(), indent=2))
        return 0
    if a.cmd == "email-poll":
        try:
            cfg = ImapConfig.from_env()
        except ImapNotConfigured as e:
            print(f"not configured: {e}", file=sys.stderr)
            return 2
        leads, stats = fetch_leads(cfg, since_days=a.since_days, limit=a.limit, platforms_only=not a.all_senders)
        new = sum(int(ingest_lead(store, lead)[1]) for lead in leads)
        by_platform: dict[str, int] = {}
        for lead in leads:
            by_platform[lead.platform] = by_platform.get(lead.platform, 0) + 1
        print(json.dumps({**stats, "new_messages": new, "by_platform": by_platform, "store": str(store.root)}, indent=2))
        return 0
    if a.cmd == "email-import":
        print(json.dumps(ingest_files(store, a.files), indent=2))
        return 0
    if a.cmd == "sms-add":
        t = ingest_text(store, phone=a.phone, text=a.text, name=a.name)
        print(json.dumps({"thread_id": t["thread_id"], "messages": len(t["messages"])}))
        return 0
    if a.cmd == "threads":
        rows = [{"thread_id": t["thread_id"], "platform": t.get("source_platform"), "messages": len(t["messages"]),
                 "last_from": t["messages"][-1]["from"] if t["messages"] else None}
                for t in store.list_threads(a.channel)]
        print(json.dumps(rows, indent=2))
        return 0
    if a.cmd == "drafts":
        print(json.dumps(store.drafts(a.channel), indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
