"""Step 1: load the owner's anonymized conversation exports and normalize them to threads.

Input (real mode): $RENTUS_PRIVATE_DIR/input/ (default ~/rentus-private-data/input/)
  imazing/   iMazing iPhone message exports, *.csv (one or more chats per file)
  facebook/  Facebook "Download your information" (JSON). Any message_*.json under it is read:
             messages/inbox, archived_threads, filtered_threads, message_requests, e2ee_cutover.
             Both the classic format (sender_name / timestamp_ms / content, latin-1 mojibake) and
             the newer E2EE format (senderName / timestamp / text) are handled.
  generic/   *.csv or *.jsonl with columns thread_id, ts, sender, text (optional: role, channel).
             ts = ISO 8601 or epoch seconds/milliseconds. role = owner|renter overrides the name match.
Owner identification: names in TWINS_OWNER_NAMES (comma-separated, case-insensitive) or --owner-names.
iMazing "Outgoing" rows are always the owner.

Output: work/threads.jsonl, one thread per line:
  {"thread_id", "source", "channel", "language", "languages", "language_switch", "start",
   "rental": {"kept", "by", "score", "category"}, "turns": [{"i", "role", "ts", "text", "lang"}]}
plus work/ingest_report.json (counts only). Sender names are never stored; thread ids are salted hashes.
Text gets a second regex PII scrub (phones, emails, URLs, street addresses, unit numbers, ids).

Usage:
  data/twins/.venv/bin/python data/twins/ingest.py --fixture
  data/twins/.venv/bin/python data/twins/ingest.py --owner-names "Kalin Ivanov,Rentus Homes" --limit 20
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from common import LocalLLM, Paths, common_args, detect_lang, hid, pmap, scrub, write_json, write_jsonl

TZ = ZoneInfo(os.environ.get("TWINS_TZ", "America/New_York"))
MAX_TURNS = 80

FB_SYSTEM = re.compile(
    r"^(you can now (message|call)|you are now connected|say hi to your new|.* sent an attachment\.?$|"
    r".* sent a (photo|video|sticker|gif|voice message|link)\.?$|.* reacted .* to your message|"
    r".* missed (your|a) (video )?call|the (video )?(call|chat) ended|.* unsent a message|"
    r".* (named|changed) the group|.* set the nickname|.* started (sharing|a video chat)|"
    r"this message was deleted|.* changed the theme|.* waved at you|you waved at)", re.I)
MEDIA_ONLY = re.compile(r"^\s*(\[attachment\]|￼|￼)?\s*$")

RENTAL_KW = re.compile(
    r"\b(room|rooms|rent|rental|renting|lease|leasing|available|availability|deposit|move[- ]?in|moving|"
    r"utilities|roommates?|showing|tour|apartment|bedroom|bathroom|bath|listing|sublet|landlord|"
    r"per month|/mo|a month|application|furnished|"
    r"cuarto|habitaci[oó]n|renta|rentar|alquiler|alquilar|disponible|dep[oó]sito|mudar|mudanza|contrato|"
    r"al mes|por mes|amueblad[oa]|compa[nñ]er[oa]s?)\b", re.I)


# --------------------------------------------------------------------------------------------- helpers
def fix_mojibake(s: str) -> str:
    """Facebook writes UTF-8 bytes as latin-1 code points ("Ã©" for "é"). Undo it only when the
    round trip is valid, so already-correct text (newer exports) is left alone."""
    if not s:
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def parse_ts(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", v.strip())):
        x = float(v)
        if x > 1e11:
            x /= 1000.0
        return datetime.fromtimestamp(x, tz=timezone.utc).astimezone(TZ)
    s = str(v).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p",
                "%m/%d/%Y %H:%M", "%m/%d/%y %H:%M", "%d/%m/%Y %H:%M:%S", "%b %d, %Y at %I:%M:%S %p",
                "%b %d, %Y %I:%M:%S %p"):
        try:
            d = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
        except ValueError:
            continue
        return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)
    return None


def read_csv_any(path: Path) -> list[dict]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [{(k or "").strip().lower(): (v or "") for k, v in row.items()}
            for row in csv.DictReader(io.StringIO(text), dialect=dialect)]


def col(row: dict, *names: str) -> str:
    for n in names:
        if row.get(n):
            return row[n]
    return ""


# --------------------------------------------------------------------------------------------- loaders
# Each loader yields raw threads: {"key", "source", "channel", "msgs": [(ts, role|None, sender, text)]}

def load_imazing(root: Path):
    for path in sorted(root.rglob("*.csv")):
        rows = read_csv_any(path)
        if not rows or "text" not in rows[0]:
            print(f"  skip {path.name}: no Text column", file=sys.stderr)
            continue
        by = defaultdict(list)
        for r in rows:
            typ = col(r, "type").lower()
            if typ not in ("incoming", "outgoing", "sent", "received"):
                continue  # notifications, system rows
            text = col(r, "text").strip()
            if not text:
                continue
            ts = parse_ts(col(r, "message date", "date", "timestamp"))
            session = col(r, "chat session", "conversation", "chat") or path.stem
            role = "owner" if typ in ("outgoing", "sent") else None
            sender = col(r, "sender name", "sender id", "sender")
            channel = "sms"
            by[session].append((ts, role, sender, text, channel))
        for session, msgs in by.items():
            yield {"key": f"imazing:{path.name}:{session}", "source": "imazing", "channel": "sms",
                   "msgs": [m[:4] for m in msgs]}


def load_facebook(root: Path):
    groups = defaultdict(list)
    for path in sorted(root.rglob("message_*.json")):
        groups[path.parent].append(path)
    for folder, files in sorted(groups.items()):
        msgs = []
        for f in files:
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                print(f"  skip {f}: unreadable JSON", file=sys.stderr)
                continue
            for m in obj.get("messages", []):
                if m.get("is_unsent") or m.get("isUnsent"):
                    continue
                sender = fix_mojibake(m.get("sender_name") or m.get("senderName") or "")
                text = m.get("content") if "content" in m else m.get("text")
                text = fix_mojibake(text or "").strip()
                if not text or FB_SYSTEM.match(text) or MEDIA_ONLY.match(text):
                    continue
                if m.get("type") not in (None, "Generic", "text", "Share"):
                    continue
                ts = parse_ts(m.get("timestamp_ms") or m.get("timestamp"))
                msgs.append((ts, None, sender, text))
        if msgs:
            yield {"key": f"facebook:{folder.relative_to(root)}", "source": "facebook", "channel": "messenger",
                   "msgs": msgs}


def load_generic(root: Path):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() == ".csv":
            rows += [(path, r) for r in read_csv_any(path)]
        elif path.suffix.lower() in (".jsonl", ".ndjson"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    rows.append((path, {str(k).lower(): v for k, v in r.items()}))
    by = defaultdict(list)
    channel = {}
    for path, r in rows:
        text = str(r.get("text") or "").strip()
        if not text or not r.get("thread_id"):
            continue
        role = str(r.get("role") or "").lower() or None
        role = {"owner": "owner", "operator": "owner", "landlord": "owner", "renter": "renter"}.get(role) if role else None
        key = f"generic:{path.name}:{r['thread_id']}"
        by[key].append((parse_ts(r.get("ts")), role, str(r.get("sender") or ""), text))
        channel[key] = str(r.get("channel") or "sms").lower()
    for key, msgs in by.items():
        yield {"key": key, "source": "generic", "channel": channel[key], "msgs": msgs}


# --------------------------------------------------------------------------------------------- normalize
def normalize(raw: dict, owners: set[str], salt: str, scrub_counts: Counter) -> dict | None:
    msgs = sorted([m for m in raw["msgs"] if m[0] is not None], key=lambda m: m[0])
    if not msgs:
        return None
    turns, prev_lang = [], None
    for ts, role, sender, text in msgs[:MAX_TURNS]:
        if role is None:
            role = "owner" if sender.strip().casefold() in owners else "renter"
        clean, counts = scrub(text)
        scrub_counts.update(counts)
        lang = detect_lang(clean, prev_lang)
        if role == "renter":
            prev_lang = lang
        turns.append({"i": len(turns), "role": role, "ts": ts.replace(tzinfo=None).isoformat(timespec="minutes"),
                      "text": clean, "lang": lang})
    if not any(t["role"] == "renter" for t in turns):
        return None
    rl = [t["lang"] for t in turns if t["role"] == "renter"]
    langs = sorted(set(rl))
    switch = any(a != b for a, b in zip(rl, rl[1:]))
    lang = Counter(rl).most_common(1)[0][0]
    return {"thread_id": "th_" + hid(salt, raw["key"]), "source": raw["source"], "channel": raw["channel"],
            "language": lang, "languages": langs, "language_switch": switch, "start": turns[0]["ts"],
            "turns": turns, "_owner_turns": sum(t["role"] == "owner" for t in turns)}


CLASSIFY_SYSTEM = (
    "You sort anonymized chat threads from a small landlord's phone and Messenger. Decide what the thread is. "
    "inquiry = someone asking about renting a room or home from the landlord (availability, price, showing, "
    "application, lease, move-in), even if it goes nowhere. tenant = an existing tenant's matters (repairs, rent "
    "payment, move-out). other = anything else (friends, family, services, spam). "
    'Return JSON only: {"category": "inquiry"|"tenant"|"other"}')


def classify(llm: LocalLLM, th: dict) -> str:
    lines = [f"{'landlord' if t['role'] == 'owner' else 'other person'}: {t['text'][:300]}" for t in th["turns"][:14]]
    out = llm.chat_json([{"role": "system", "content": CLASSIFY_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
                        temperature=0.0, max_tokens=4000, cache_key="classify")
    cat = (out or {}).get("category")
    return cat if cat in ("inquiry", "tenant", "other") else "unknown"


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--owner-names", default=None, help="comma-separated owner display names (else TWINS_OWNER_NAMES)")
    ap.add_argument("--classify", choices=["auto", "all", "none"], default="auto",
                    help="auto: keyword score decides clear cases, Lightning the ambiguous ones; all: Lightning "
                         "for every thread; none: keywords only")
    ap.add_argument("--keep-tenant", action="store_true", help="also keep existing-tenant threads")
    a = ap.parse_args()
    P = Paths.make(a.fixture)
    names = a.owner_names or os.environ.get("TWINS_OWNER_NAMES") or ("Fixture Owner" if a.fixture else "")
    owners = {n.strip().casefold() for n in names.split(",") if n.strip()}
    if not owners:
        sys.exit("set the owner's display name(s): --owner-names or TWINS_OWNER_NAMES")
    salt = P.salt()

    raws = []
    for sub, loader in (("imazing", load_imazing), ("facebook", load_facebook), ("generic", load_generic)):
        d = P.input / sub
        if d.exists():
            got = list(loader(d))
            print(f"{sub}: {len(got)} raw threads")
            raws += got
    scrub_counts = Counter()
    threads = [t for t in (normalize(r, owners, salt, scrub_counts) for r in raws) if t]
    no_owner = sum(1 for t in threads if t["_owner_turns"] == 0)
    threads.sort(key=lambda t: (t["start"], t["thread_id"]))
    if a.limit:
        threads = threads[: a.limit]

    # rental filter: keyword score, Lightning for the ambiguous middle (or all, per --classify)
    for t in threads:
        t["rental"] = {"score": len({m.group().lower() for x in t["turns"] for m in RENTAL_KW.finditer(x["text"])})}
    need = [t for t in threads if a.classify == "all" or (a.classify == "auto" and t["rental"]["score"] in (1, 2))]
    if need:
        llm = LocalLLM("operator", P.work / "cache")
        cats = pmap(lambda t: classify(llm, t), need, a.workers)
        for t, c in zip(need, cats):
            t["rental"]["category"], t["rental"]["by"] = c, "lightning"
    for t in threads:
        r = t["rental"]
        if "category" not in r:
            r["by"] = "keywords"
            r["category"] = "inquiry" if r["score"] >= 3 else ("other" if r["score"] == 0 else "unknown")
        if r["category"] == "unknown":  # Lightning failed or --classify none on a borderline thread
            r["category"] = "inquiry" if r["score"] >= 2 else "other"
        r["kept"] = r["category"] == "inquiry" or (a.keep_tenant and r["category"] == "tenant")
        t.pop("_owner_turns", None)

    kept = [t for t in threads if t["rental"]["kept"]]
    write_jsonl(P.work / "threads.jsonl", kept)
    report = {
        "raw_threads": len(raws), "normalized_threads": len(threads), "threads_without_owner_turns": no_owner,
        "kept": len(kept), "dropped_by_category": dict(Counter(t["rental"]["category"] for t in threads
                                                               if not t["rental"]["kept"])),
        "decided_by": dict(Counter(t["rental"]["by"] for t in threads)),
        "by_source": dict(Counter(t["source"] for t in kept)), "by_language": dict(Counter(t["language"] for t in kept)),
        "language_switch_threads": sum(t["language_switch"] for t in kept),
        "messages": sum(len(t["turns"]) for t in kept), "pii_scrubbed": dict(scrub_counts),
    }
    write_json(P.work / "ingest_report.json", report)
    print(json.dumps(report, indent=1))
    if no_owner:
        print(f"WARNING: {no_owner} threads have no owner turns; check --owner-names", file=sys.stderr)


if __name__ == "__main__":
    main()
