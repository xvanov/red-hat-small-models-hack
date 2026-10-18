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

from common import LocalLLM, Paths, common_args, setup, detect_lang, hid, pmap, scrub, write_json, write_jsonl

TZ = ZoneInfo(os.environ.get("TWINS_TZ", "America/New_York"))
MAX_TURNS = 80          # imazing / facebook / generic threads
ANON_MAX_TURNS = 600    # anonymized owner export: whole threads are kept; episodes are cut below
EPISODE_TURNS = 40      # a twin mirrors one episode of at most this many messages

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


# --------------------------------------------------------------------------------------------- anonymized export
# The owner's anonymized phone-message export (raw/anonymized-YYYY-MM-DD/): {tenants,contractors}/messages.jsonl,
# one message per line: conv, dataset, type ("1:1"|"group"), house, ts, sender ("me" or a person id), sender_name,
# text, attachments, edited; plus people.csv (id, roles incl. "partner", conversations). Selection and the
# held-out/dev split come from split.py (work/twins/selection.json).
TAPBACK = re.compile(
    r"^(Liked|Loved|Laughed at|Emphasized|Disliked|Questioned|Reacted|Removed an? \w+ from|Le gustó|Le encantó|"
    r"Se rió de|Enfatizó|No le gustó|Cuestionó|Reaccionó)\b.*[“\"]|^\S{1,3} (to|a) [“\"]", re.S)
MEDIA_KIND = {"image": "[photo]", "video": "[video]", "audio": "[audio]", "application": "[file]", "file": "[file]",
              "text": "[file]"}
OPS_KW = re.compile(
    r"\b(leak|leaking|clog|toilet|sink|shower|drain|water heater|hot water|plumb|breaker|outlet|power|electric|"
    r"wifi|wi-fi|internet|router|lock|key|door|ac\b|a/c|heat|hvac|thermostat|fridge|washer|dryer|stove|oven|"
    r"dishwasher|mold|pest|roach|mice|rent|late|pay|paid|zelle|cash ?app|utilit|bill|deposit|move[- ]?out|"
    r"trash|clean|noise|guest|parking|package|renew|repair|fix|broken|not working|"
    r"fuga|gotera|baño|inodoro|ducha|agua caliente|luz|internet|llave|puerta|renta|pago|pagar|utilidades|"
    r"basura|limpi|ruido|arregl|roto|no funciona)", re.I)
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def anon_people(raw_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """(partner ids, conv -> person ids listed as participants)."""
    partners, conv_people = set(), defaultdict(set)
    with open(raw_dir / "people.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if "partner" in (r.get("roles") or ""):
                partners.add(r["id"])
            for c in (r.get("conversations") or "").split():
                conv_people[c].add(r["id"])
    return partners, conv_people


def anon_messages(raw_dir: Path, datasets=("tenants", "contractors")) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for ds in datasets:
        path = raw_dir / ds / "messages.jsonl"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    by[m["conv"]].append(m)
    for msgs in by.values():
        msgs.sort(key=lambda m: m["ts"])
    return by


def anon_turn_text(m: dict) -> str | None:
    """Message text for a twin: tap-back reactions dropped, photo-only messages kept as [photo]/[video]/[file]."""
    text = (m.get("text") or "").strip()
    if text:
        return None if TAPBACK.match(text) else text
    kinds = [a.split()[0].lower() for a in m.get("attachments") or [] if "pluginpayload" not in a]
    return MEDIA_KIND.get(kinds[0], "[file]") if kinds else None


def anon_role(m: dict, partners: set[str], dataset: str) -> str:
    if m["sender"] == "me" or m["sender"] in partners:
        return "owner"  # partners speak for the operator side (lead hand-offs, team)
    return "vendor" if dataset == "contractors" else "renter"


def episode_bounds(turns: list[dict], category: str, tenancy_start: int | None) -> list[tuple[str, int, int]]:
    """[(episode category, start, end)] windows of at most EPISODE_TURNS messages."""
    n = len(turns)
    out = []
    if category in ("leasing", "leasing_then_tenancy"):
        end = min(n, tenancy_start or n) if category == "leasing_then_tenancy" else n
        out.append(("leasing", 0, min(end, EPISODE_TURNS)))
    if category in ("tenancy_ops", "leasing_then_tenancy"):
        lo = (tenancy_start or 0) if category == "leasing_then_tenancy" else 0
        hit = next((k for k in range(lo, n) if turns[k]["role"] != "owner" and OPS_KW.search(turns[k]["text"])), None)
        if hit is not None:
            s0 = max(lo, hit - 2)
            out.append(("ops", s0, min(n, s0 + 30)))
    if category == "contractor":
        out.append(("contractor", 0, min(n, EPISODE_TURNS)))
    return [(c, a, b) for c, a, b in out if b - a >= 2]


def load_anon_selected(raw_dir: Path, selection: dict, salt: str, scrub_counts: Counter) -> dict[str, list[dict]]:
    """Normalized episode threads per split, from split.py's selection (conv -> split, category, ...)."""
    partners, _ = anon_people(raw_dir)
    msgs = anon_messages(raw_dir)
    out = defaultdict(list)
    for conv, sel in sorted(selection["threads"].items()):
        if sel["split"] not in ("heldout", "dev"):
            continue
        ds = sel["dataset"]
        turns, prev_lang = [], None
        for m in msgs[conv][:ANON_MAX_TURNS]:
            text = anon_turn_text(m)
            if text is None:
                continue
            ts = parse_ts(m["ts"])
            role = anon_role(m, partners, ds)
            clean, counts = scrub(text)
            scrub_counts.update(counts)
            lang = detect_lang(clean, prev_lang)
            if role != "owner":
                prev_lang = lang
            turns.append({"role": role, "person": m["sender"], "ts": ts.replace(tzinfo=None).isoformat(timespec="minutes"), "text": clean,
                          "lang": lang, "media": bool(re.fullmatch(r"\[(photo|video|audio|file)\]", clean)),
                          "date_damaged": date_damaged(text)})
        for cat, a, b in episode_bounds(turns, sel["category"], sel.get("tenancy_start")):
            ep = [dict(t, i=k) for k, t in enumerate(turns[a:b])]
            if not any(t["role"] != "owner" and not t["media"] for t in ep):
                continue
            rl = [t["lang"] for t in ep if t["role"] != "owner" and not t["media"]]
            out[sel["split"]].append({
                "thread_id": "th_" + hid(salt, "anon", conv, cat), "conv": conv, "source": "anon", "channel": "sms",
                "category": cat, "counterpart": {"leasing": "renter", "ops": "tenant", "contractor": "vendor"}[cat],
                "split": sel["split"], "language": Counter(rl).most_common(1)[0][0], "languages": sorted(set(rl)),
                "language_switch": any(x != y for x, y in zip(rl, rl[1:])), "start": ep[0]["ts"],
                "episode": [a, b], "thread_turns": len(turns), "turns": ep,
                "rules_period": bool(sel.get("rules_period")),
                "rental": {"kept": True, "by": "selection", "category": cat}})
    return out


STREET_WORDS: set[str] = set()
MONTH_RE = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
            r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
            r"septiembre|octubre|noviembre|diciembre)")


def load_street_words(raw_dir: Path) -> None:
    """Words the anonymizer uses in fake street names (houses.csv, people.csv): it sometimes put one where the day
    of a date was ("<Month> <StreetWord>"), which destroys exact move-in dates (eval-protocol 2.2)."""
    words = set()
    for name in ("houses.csv", "people.csv"):
        with open(raw_dir / name, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                for addr in re.split(r";", (r.get("address") or "") + ";" + (r.get("houses") or "")):
                    m = re.match(r"\s*\d+\s+(.+?),", addr)
                    if m:
                        words |= {w for w in m.group(1).split() if len(w) > 3}
    STREET_WORDS.clear()
    STREET_WORDS.update(w.lower() for w in words)


def date_damaged(raw_text: str) -> bool:
    t = raw_text or ""
    for m in re.finditer(MONTH_RE + r"\.?\s+([A-Za-z]+)", t):
        if m.group(1).lower() in STREET_WORDS:
            return True
    for m in re.finditer(r"\[state\]", t):
        win = t[max(0, m.start() - 25): m.end() + 25]
        if re.search(MONTH_RE + r"|\b\d{1,2}(st|nd|rd|th)?\b|\d{1,2}/\d{1,2}", win, re.I):
            return True
    return False


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
    ap.add_argument("--anon", default=None, metavar="RAW_DIR",
                    help="read the owner's anonymized export (raw/anonymized-*/) instead of input/; needs split.py's "
                         "selection.json; writes work/twins/<split>/threads.jsonl for every split at once")
    a = ap.parse_args()
    setup(a)
    if a.anon:
        return main_anon(a)
    P = Paths.make(a.fixture, a.split)
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
        llm = LocalLLM("operator", P.cache)
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

    if need:
        llm.require_healthy("ingest")
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


def main_anon(a) -> None:
    raw = Path(a.anon).expanduser().resolve()
    P = Paths.make(False)
    sel_path = P.root / "selection.json"
    if not sel_path.exists():
        sys.exit("run split.py first (work/twins/selection.json)")
    selection = json.loads(sel_path.read_text())
    load_street_words(raw)
    scrub_counts = Counter()
    by_split = load_anon_selected(raw, selection, P.salt(), scrub_counts)
    report = {"pii_scrubbed": dict(scrub_counts), "splits": {}}
    for split in ("heldout", "dev"):
        threads = sorted(by_split.get(split, []), key=lambda t: (t["start"], t["thread_id"]))
        SP = Paths.make(False, split)
        write_jsonl(SP.work / "threads.jsonl", threads)
        cp = [t for th in threads for t in th["turns"] if t["role"] != "owner"]
        report["splits"][split] = {
            "episodes": len(threads), "conversations": len({t["conv"] for t in threads}),
            "by_category": dict(Counter(t["category"] for t in threads)),
            "by_language": dict(Counter("mixed" if t["language_switch"] else t["language"] for t in threads)),
            "messages": sum(len(t["turns"]) for t in threads), "counterpart_messages": len(cp),
            "media_only_messages": sum(t["media"] for th in threads for t in th["turns"]),
            "date_damaged_messages": sum(t["date_damaged"] for t in cp),
            "date_damaged_threads": sum(any(t["date_damaged"] for t in th["turns"] if t["role"] != "owner")
                                        for th in threads)}
    # every real line of the export (tenants + contractors, scrubbed): the privacy filter's reference set
    partners, _ = anon_people(raw)
    lines = []
    for conv, msgs in anon_messages(raw).items():
        for m in msgs:
            text = anon_turn_text(m)
            if text and not re.fullmatch(r"\[(photo|video|audio|file)\]", text):
                lines.append({"thread_id": conv, "text": scrub(text)[0]})
    write_jsonl(P.root / "real_lines.jsonl", lines)
    report["real_lines"] = len(lines)
    write_json(P.root / "ingest_report.json", report)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
