"""Rule-based audit of the owner's blind labels (eval-protocol Amendment 3: adjudication).

    labeler/.venv/bin/python labeler/audit.py [--source auto|real|fixture]   # writes labeler/out/audit_summary.json

NO MODEL OF ANY KIND is used here: not the fine-tuned reader, not Lightning, not any LLM, and not the twin
pipeline's own gold (`output` in reader_test.jsonl, which the fine-tuned reader wrote). The owner's labels are
the gold those systems are scored against, so a model suggesting changes would bias the gold toward a model.
Every flag comes from a fixed, deterministic rule over the item's own text (message + last operator line) and
its "today" date, following data/reader_schema.md. A flag is only a question to the owner: the owner keeps or
changes each one on /audit, and a change is appended as a new owner label with reason "audit".
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

# ---------------------------------------------------------------- text helpers


def norm(s: str) -> str:
    """lowercase, accents stripped (so 'sábado' == 'sabado')."""
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def words(s: str) -> list[str]:
    return re.findall(r"[a-zñ']+", norm(s))


MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
WD_RE = "|".join(WEEKDAYS)
DAYWORD = {"first": 1, "primero": 1, "1ro": 1, "1o": 1}
ORD = r"(\d{1,2})(?:st|nd|rd|th|ro|o)?"


def next_on_or_after(today: date, month: int, day: int) -> date | None:
    for y in (today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def next_day_of_month(today: date, day: int) -> date | None:
    y, m = today.year, today.month
    for _ in range(13):
        try:
            d = date(y, m, day)
            if d >= today:
                return d
        except ValueError:
            pass
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None


def resolve_dates(text: str, today: date) -> list[tuple[date, str]]:
    """Every resolvable calendar day in the text (schema 'answered' move-in), each as the next occurrence on or
    after `today`, with the span that produced it. Numeric dates whose parts are both 1-12 and differ are NOT
    resolvable (schema: vague); they are returned by `ambiguous_numeric` instead."""
    t = norm(text)
    out: list[tuple[date, str]] = []
    # "Nov 1st", "November 24", "March 22"
    for m in re.finditer(rf"\b({MONTH_RE})\.?\s+(?:the\s+)?{ORD}\b", t):
        d = next_on_or_after(today, MONTHS[m.group(1)], int(m.group(2)))
        if d:
            out.append((d, m.group(0)))
    # "1st of November", "el 9 de enero", "9 de enero", "el primero de noviembre"
    for m in re.finditer(rf"\b(?:{ORD}|(first|primero))\s+(?:of|de)\s+({MONTH_RE})\b", t):
        day = int(m.group(1)) if m.group(1) else DAYWORD[m.group(2)]
        d = next_on_or_after(today, MONTHS[m.group(3)], day)
        if d:
            out.append((d, m.group(0)))
    # numeric 11/25, 25/11, 11/25/2026 (only when unambiguous)
    for m in re.finditer(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t):
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 12 and b <= 12 and a != b:
            continue
        month, day = (a, b) if b > 12 or a == b else (b, a) if a > 12 else (None, None)
        if month and 1 <= month <= 12:
            d = next_on_or_after(today, month, day)
            if d:
                out.append((d, m.group(0)))
    # "this Saturday", "next Friday", "este sabado", "el sabado"
    for m in re.finditer(rf"\b(this|next|este|el|on|el proximo|proximo)\s+({WD_RE})\b", t):
        wd = WEEKDAYS[m.group(2)]
        delta = (wd - today.weekday()) % 7
        if m.group(1) in ("next", "proximo", "el proximo") and delta == 0:
            delta = 7
        out.append((today + timedelta(days=delta), m.group(0)))
    # "tomorrow", "manana" (only as a word, not "por la manana"), "today"/"hoy"
    if re.search(r"\btomorrow\b", t) or re.search(r"(?<!la )\bmanana\b", t):
        out.append((today + timedelta(days=1), "tomorrow"))
    if re.search(r"\b(today|hoy)\b", t):
        out.append((today, "today"))
    # "the 15th" / "el 15" (bare day of month, not 'around the 15th', not followed by a month: handled above)
    for m in re.finditer(rf"\b(?<!around )(?<!alrededor del )(?:the|el|on the)\s+{ORD}\b(?!\s+(?:of|de|people|persons|personas|rooms|bedrooms|months|weeks|days|meses|semanas|dias|years|anos)\b)", t):
        day = int(m.group(1))
        if 1 <= day <= 31:
            d = next_day_of_month(today, day)
            if d:
                out.append((d, m.group(0)))
    seen, uniq = set(), []
    for d, span in out:
        if d not in seen:
            seen.add(d)
            uniq.append((d, span))
    return uniq


def ambiguous_numeric(text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(r"\b(\d{1,2})[/.](\d{1,2})\b", norm(text))
            if int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2)]


VAGUE_DATE = [
    r"\bnext month\b", r"\bsoon\b", r"\basap\b", r"\bas soon as\b", r"\bend of (?:the )?month\b",
    r"\bbeginning of\b", r"\bearly\s+(?:" + MONTH_RE + r")\b", r"\blate\s+(?:" + MONTH_RE + r")\b",
    r"\bmid[- ]?(?:" + MONTH_RE + r")\b", r"\baround the\b", r"\bin a few (?:weeks|days)\b", r"\bin (?:\d+|two|three|a couple of) (?:weeks|days|months)\b",
    r"\ben (?:\d+|dos|tres|unas) (?:semanas|dias|meses)\b", r"\bsometime\b",
    r"\bin (?:" + MONTH_RE + r")\b", r"\bpronto\b", r"\blo antes posible\b", r"\bel (?:proximo|otro) mes\b",
    r"\bmes que viene\b", r"\ba (?:principios|mediados|fines|finales) de\b", r"\ben (?:" + MONTH_RE + r")\b",
    r"\balrededor del\b", r"\bdespues del\b", r"\bafter the\b",
]


def vague_date_spans(text: str) -> list[str]:
    t = norm(text)
    return [m.group(0) for p in VAGUE_DATE for m in re.finditer(p, t)]


PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")


def phones(text: str) -> list[str]:
    return ["+1" + "".join(m.groups()) for m in PHONE_RE.finditer(text or "")]


LEASE_WORDS = r"\b(lease|leases|year|yearly|annual|12[- ]month|twelve months|month[- ]to[- ]month|months?|sublet|" \
              r"contract|commit|sign|contrato|ano|anual|meses|mes a mes|comprometo|comprometerme|firmar|plazo)\b"
SHORTER_WORDS = r"(month[- ]to[- ]month|mes a mes|short[- ]term|shorter|less than (?:a|one|12)|under (?:a year|12)|" \
                r"(?:\b[1-9]|\b1[01]|six|three|four|five|nine)[- ]months?\b|menos de (?:un ano|12)|" \
                r"no quiero comprometerme con un ano|corto plazo|(?:seis|tres|cuatro|nueve) meses|\b[1-9] meses)"
SCHED_WORDS = r"\b(showing|viewing|tour|see the (?:room|place|house|unit)|come by|stop by|visit|ver el cuarto|" \
              r"ver la habitacion|visita|verlo|verla)\b"
MOVE_WORDS = r"\b(move|moving|move-in|movein|start|mudo|mudaria|mudarme|mudanza|entrar|llegar|mudar)\b"
MOVE_Q = r"(move|mudar|mudanza|move-in|when .* (?:start|come)|cuando planeas|fecha)"
QUESTION_WORDS = r"\b(is there|are there|do you|does|can i|can you|could you|would you|what|how|when|where|which|" \
                 r"is it|is the|are the|curious|wondering|want to (?:ask|know)|would like to know|let me know|any info|" \
                 r"quisiera saber|me gustaria saber|quiero saber|una pregunta)\b"
ES_Q_ACCENTED = r"(qué|cómo|cuándo|dónde|cuál|cuánto|cuánta|cuántos|cuántas)"   # accented = interrogative

ES_STOP = {"de", "la", "que", "el", "en", "y", "los", "se", "del", "las", "un", "por", "con", "no", "una", "su",
           "para", "es", "al", "lo", "como", "mas", "pero", "sus", "le", "ya", "o", "este", "si", "porque", "esta",
           "cuando", "muy", "sin", "sobre", "tambien", "me", "hasta", "hay", "donde", "quien", "desde", "todo",
           "nos", "durante", "todos", "uno", "les", "ni", "contra", "otros", "ese", "eso", "ante", "ellos", "e",
           "esto", "mi", "antes", "algunos", "unos", "yo", "otro", "otras", "otra", "el", "tanto", "esa", "estos",
           "mucho", "quienes", "nada", "muchos", "cual", "poco", "ella", "estar", "estas", "algunas", "algo",
           "nosotros", "tu", "te", "ti", "hola", "gracias", "solo", "quiero", "tengo", "puedo", "busco", "cuarto",
           "estoy", "seria", "mudo", "bien", "bueno", "claro", "vale", "dias", "buenas", "cuanto"}
EN_STOP = {"the", "a", "an", "and", "or", "but", "is", "are", "was", "be", "to", "of", "in", "on", "for", "with",
           "at", "by", "from", "this", "that", "it", "i", "i'm", "im", "you", "we", "my", "me", "your", "do", "does",
           "can", "could", "would", "will", "just", "not", "no", "yes", "there", "what", "how", "when", "where",
           "have", "has", "if", "so", "about", "thanks", "thank", "hi", "hello", "hey", "please", "looking",
           "room", "works", "see", "then", "like", "want", "need", "am", "it's", "any", "all", "up", "out", "ok",
           "okay", "sure", "great", "fine", "good"}
AMBIG_STOP = {"no", "me", "a", "o", "y", "e", "si", "solo"}  # shared spellings carry no signal


def language_votes(text: str) -> tuple[int, int]:
    ws = words(text)
    es = sum(1 for w in ws if w in ES_STOP and w not in AMBIG_STOP) + len(re.findall(r"[ñ¿¡áéíóú]", (text or "").lower()))
    en = sum(1 for w in ws if w in EN_STOP and w not in AMBIG_STOP)
    return es, en


def detect_language(text: str) -> str | None:
    """'es' / 'en' when the stopword ratio is clear (>= 2 votes and >= 2/3 of them); None when too short or mixed."""
    es, en = language_votes(text)
    n = es + en
    if n < 2:
        return None
    if es / n >= 2 / 3:
        return "es"
    if en / n >= 2 / 3:
        return "en"
    return None


# ---------------------------------------------------------------- rules

RULES = {
    "move_in_date_mismatch": "labeled exact date is not the next occurrence on/after 'today' of the day written in the text",
    "move_in_resolvable_not_exact": "the text gives a resolvable move-in day, but move-in is not labeled exact",
    "move_in_vague_marked_exact": "move-in labeled exact, but the text only has a month / 'soon' / 'next month' / an ambiguous 1/11-style date",
    "move_in_exact_without_day": "move-in labeled exact, but no calendar day is written in the text",
    "phone_in_text_not_given": "a full 10-digit number is in the text, but phone is not labeled given",
    "phone_given_not_in_text": "phone labeled given, but the text has no full 10-digit number",
    "phone_value_mismatch": "the labeled number differs from the 10-digit number in the text",
    "lease_without_lease_words": "lease labeled yes/no/vague/exception, but neither the message nor the operator line before it mentions a lease",
    "shorter_lease_words_without_intent": "the text asks for a shorter / month-to-month lease, but shorter_lease is not among the intents",
    "language_stopwords": "labeled language disagrees with the stopword ratio of the message (es vs en)",
    "language_changed_from_earlier_save": "the latest save's language differs from an earlier save of the same item (the Back/forward hydration bug could reset the form to 'en')",
    "resaved_before_history": "re-saved under the old labeler, which kept no earlier versions; the latest language may come from a reset form",
    "contradiction": "internally contradictory label",
    "question_without_question": "question intent, but the message has no '?' and no question words",
    "question_mark_without_intent": "the message asks something ('?'), but no question / scheduling / price / shorter-lease intent is labeled",
}

UI_FIELDS = ("lease", "move_in", "move_in_date", "phone", "phone_value", "occupants", "reason", "intents", "language")


def flag(rid, rule, field, owner, suggested, patch, why, label_ts):
    return {"id": rid, "rule": rule, "field": field, "owner_value": owner, "suggested": suggested,
            "patch": patch, "why": why, "rule_text": RULES[rule], "label_ts": label_ts}


def item_flags(rid: str, inp: dict, rec: dict, ui: dict, versions: list[dict], resave_count: int,
               ui_of) -> list[dict]:
    if rec.get("skipped") or not ui:
        return []
    msg = inp.get("message") or ""
    ctx = inp.get("context") or []
    op_prev = next((c["text"] for c in reversed(ctx) if c.get("role") == "operator"), "")
    today = date.fromisoformat(inp["today"])
    tm, top = norm(msg), norm(op_prev)
    ts = rec["ts"]
    F: list[dict] = []
    intents = list(ui.get("intents") or [])

    # --- move-in
    found = resolve_dates(msg, today)
    sched_ctx = bool(re.search(SCHED_WORDS, tm) or re.search(SCHED_WORDS, top))
    move_ctx = bool(re.search(MOVE_WORDS, tm) or re.search(MOVE_Q, top))
    exact = ui.get("move_in") == "exact"
    if exact:
        lab = ui.get("move_in_date")
        if found:
            ds = [d for d, _ in found]
            if lab not in [d.isoformat() for d in ds]:
                want, span = found[0]
                why = f"text says \"{span}\"; today is {today.isoformat()}, so the next {span!r} is {want.isoformat()}"
                try:
                    ld = date.fromisoformat(lab)
                    if (ld.month, ld.day) == (want.day, want.month):
                        why += " (day and month look swapped)"
                    elif (ld.month, ld.day) == (want.month, want.day):
                        why += f" (same day, wrong year: {ld.year} instead of {want.year})"
                    elif ld.day == want.day:
                        why += " (same day, different month)"
                    if ld < today:
                        why += f"; the labeled date is before today ({today.isoformat()})"
                except (TypeError, ValueError):
                    pass
                F.append(flag(rid, "move_in_date_mismatch", "move_in", f"exact {lab}", f"exact {want.isoformat()}",
                              {"move_in": "exact", "move_in_date": want.isoformat()}, why, ts))
        else:
            vs = vague_date_spans(msg) + ambiguous_numeric(msg)
            if vs:
                F.append(flag(rid, "move_in_vague_marked_exact", "move_in", f"exact {lab}", "vague",
                              {"move_in": "vague", "move_in_date": None, "move_in_cond": False},
                              f"text has only \"{vs[0]}\", no calendar day", ts))
            else:
                F.append(flag(rid, "move_in_exact_without_day", "move_in", f"exact {lab}", "check (no day in text)",
                              {}, "no calendar day found in the message", ts))
    elif found and move_ctx and not (sched_ctx and not re.search(MOVE_WORDS, tm)):
        want, span = found[0]
        F.append(flag(rid, "move_in_resolvable_not_exact", "move_in", ui.get("move_in"), f"exact {want.isoformat()}",
                      {"move_in": "exact", "move_in_date": want.isoformat()},
                      f"text says \"{span}\" in a move-in context; next occurrence on/after {today.isoformat()} is {want.isoformat()}", ts))

    # --- phone
    ph = phones(msg)
    if ph and ui.get("phone") not in ("given",):
        F.append(flag(rid, "phone_in_text_not_given", "phone", ui.get("phone"), f"given {ph[0]}",
                      {"phone": "given", "phone_value": ph[0]}, f"the message contains {ph[0]}", ts))
    if ui.get("phone") == "given":
        if not ph:
            F.append(flag(rid, "phone_given_not_in_text", "phone", f"given {ui.get('phone_value')}", "vague or absent",
                          {}, "no full 10-digit number in the message", ts))
        else:
            v = re.sub(r"\D", "", ui.get("phone_value") or "")
            v = "+1" + (v[1:] if len(v) == 11 and v.startswith("1") else v)
            if v not in ph:
                F.append(flag(rid, "phone_value_mismatch", "phone", f"given {ui.get('phone_value')}", f"given {ph[0]}",
                              {"phone": "given", "phone_value": ph[0]}, f"the message contains {ph[0]}", ts))

    # --- lease
    lease_here = bool(re.search(LEASE_WORDS, tm))
    lease_asked = bool(re.search(LEASE_WORDS, top))
    if ui.get("lease") in ("yes", "no", "vague", "exception") and not lease_here and not lease_asked:
        F.append(flag(rid, "lease_without_lease_words", "lease", ui.get("lease"), "absent", {"lease": "absent"},
                      "no lease word (lease, year, months, contract, contrato, año, mes a mes...) in the message or the operator line before it", ts))
    sm = re.search(SHORTER_WORDS, tm)
    if sm and "shorter_lease" not in intents:
        F.append(flag(rid, "shorter_lease_words_without_intent", "intents", intents, intents + ["shorter_lease"],
                      {"intents": intents + ["shorter_lease"]}, f"text says \"{sm.group(0)}\"", ts))

    # --- language
    det = detect_language(msg)
    lang = ui.get("language")
    if det and lang in ("en", "es") and det != lang:
        es, en = language_votes(msg)
        F.append(flag(rid, "language_stopwords", "language", lang, det, {"language": det},
                      f"stopword votes: es {es}, en {en}", ts))
    earlier = [ui_of(v) for v in versions[:-1]] if len(versions) > 1 else []
    changed = [e["language"] for e in earlier if e and e.get("language") != lang]
    if changed:
        F.append(flag(rid, "language_changed_from_earlier_save", "language", lang, changed[-1],
                      {"language": changed[-1]}, f"{len(versions)} saves; an earlier save had language {changed[-1]!r}", ts))
    elif resave_count > 1 and rec.get("save_reason") == "imported_pre_log":
        sugg = det or lang
        F.append(flag(rid, "resaved_before_history", "language", lang, sugg,
                      {"language": sugg} if sugg != lang else {},
                      f"saved {resave_count} times under the old labeler; only the last save survived. "
                      f"Stopword rule says {det or 'unclear'}", ts))

    # --- contradictions
    def contra(why, patch, sugg):
        F.append(flag(rid, "contradiction", "intents", intents, sugg, patch, why, ts))
    s = set(intents)
    if "hard_no" in s and "scheduling" in s:
        contra("hard_no together with scheduling", {"intents": [i for i in intents if i != "scheduling"]},
               "drop scheduling or hard_no")
    if "hard_no" in s and "not_now" in s:
        contra("hard_no together with not_now", {}, "keep only one of hard_no / not_now")
    if "hard_no" in s and "price_negotiation" in s:
        contra("hard_no together with price_negotiation", {}, "keep only one")
    answered = [k for k in ("lease", "move_in", "phone", "reason") if ui.get(k) not in ("absent", None)] + \
               (["occupants"] if ui.get("occupants") not in ("absent", None) else [])
    if "small_talk" in s and (len(s) > 1 or answered):
        contra("small_talk (no content, no request) together with " + ", ".join(sorted(s - {"small_talk"}) + answered),
               {"intents": [i for i in intents if i != "small_talk"]}, "drop small_talk")
    if "shorter_lease" in s and ui.get("lease") in ("yes",):
        contra("shorter_lease together with lease = yes (a full year)", {}, "lease no/vague, or drop shorter_lease")
    if ui.get("move_in") == "exact" and "not_now" in s:
        contra("exact move-in date together with not_now", {}, "check")
    if "question" in s and "?" not in msg and "¿" not in msg and not re.search(QUESTION_WORDS, tm) \
            and not re.search(ES_Q_ACCENTED, msg.lower()):
        F.append(flag(rid, "question_without_question", "intents", intents, [i for i in intents if i != "question"],
                      {"intents": [i for i in intents if i != "question"]},
                      "no '?' and no question word in the message", ts))
    if ("?" in msg or "¿" in msg) and not (s & {"question", "scheduling", "price_negotiation", "shorter_lease"}):
        qs = re.findall(r"[^.!?¿]*\?", msg)
        q = (qs[-1].strip() if qs else msg[:80])[:120]
        F.append(flag(rid, "question_mark_without_intent", "intents", intents, intents + ["question"],
                      {"intents": intents + ["question"]}, f"message asks: \"{q}\"", ts))
    return F


def run(row_ids: list[str], by_id: dict, labels: dict, versions: dict, history: list[dict], ui_of) -> list[dict]:
    resaves: dict[str, int] = {}
    for h in history:
        if h.get("event") == "save":
            resaves[h["id"]] = resaves.get(h["id"], 0) + 1
    flags = []
    for rid in row_ids:
        rec = labels.get(rid)
        if not rec:
            continue
        # only the INPUT of the row is read; row["output"] (twin gold written by the fine-tuned reader) never is
        flags += item_flags(rid, by_id[rid]["input"], rec, ui_of(rec), versions.get(rid, []), resaves.get(rid, 0), ui_of)
    return flags


def main():
    import argparse
    import json
    import sys
    from collections import Counter
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import server

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["auto", "real", "fixture"], default="auto")
    a = ap.parse_args()
    server.ARGS.source = a.source
    mode, _ = server.current_mode()
    st = server.load(mode)
    recs = server.read_log(mode)
    labels, versions = server.effective(recs)
    hist = server.read_jsonl(server.OUT / f"history.{mode}.jsonl")
    flags = run(st["manifest"]["row_ids"], st["by_id"], labels, versions, hist, server.ui_of)
    per_rule = Counter(f["rule"] for f in flags)
    summary = {
        "what": "rule-based audit of the owner's blind labels (eval-protocol Amendment 3). No model predictions of "
                "any kind were used; rules from data/reader_schema.md over each item's own text and 'today'. "
                "The owner decides every flag on /audit.",
        "mode": mode,
        "labels_file": str(server.MODES[mode]["labels"].relative_to(server.REPO)) if server.MODES[mode]["labels"].is_relative_to(server.REPO) else str(server.MODES[mode]["labels"]),
        "labels_sha256": server.sha256_file(server.MODES[mode]["labels"]) if server.MODES[mode]["labels"].exists() else None,
        "sample_rows": len(st["manifest"]["row_ids"]),
        "labeled": len(labels),
        "skipped": sum(1 for r in labels.values() if r.get("skipped")),
        "flags_total": len(flags),
        "items_flagged": len({f["id"] for f in flags}),
        "flags_per_rule": {r: per_rule.get(r, 0) for r in RULES},
        "items_per_rule": {r: len({f["id"] for f in flags if f["rule"] == r}) for r in RULES},
        "rules": RULES,
        "created_at": server.now(),
    }
    server.OUT.mkdir(exist_ok=True)
    server.write_json_atomic(server.OUT / "audit_summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("mode", "labeled", "flags_total", "items_flagged", "flags_per_rule")}, indent=2))


if __name__ == "__main__":
    main()
