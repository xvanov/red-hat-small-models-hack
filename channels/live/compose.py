"""Live-channel delivery shaping: the operator's several send_message calls in one turn become ONE reply.

The evaluated operator (frozen) sends short messages one by one (the Gym's style rules: one fact per message). On
a real phone that reads as a burst of 5 texts. Here, per turn:
  - sentences are pooled in order; exact and near-duplicate sentences are dropped;
  - only the LAST question is kept (repeated / earlier questions are dropped), and it goes at the end;
  - the sentence that answers the renter's question (rent, availability, pets, ...) is moved first;
  - the result is split per channel: SMS one message <= 320 chars (two if longer), Messenger at most two,
    email one.
"""
from __future__ import annotations

import difflib
import re

SMS_MAX = 320
MSGR_MAX = 600

# renter question keyword -> words that mark the answering sentence
TOPICS = [
    (r"\b(sign|lease link|send the lease|send me the lease|paperwork|contract)\b", r"https?://"),
    (r"\b(rent|price|cost|how much|\$|per month|monthly)\b", r"\$\s?\d|\brent\b"),
    (r"\b(deposit)\b", r"\bdeposit\b"),
    (r"\b(available|availability|move in|move-in|earlier|when can|start date|still open)\b",
     r"\bavailable\b|\bmove[- ]in\b|\bfrom (january|february|march|april|may|june|july|august|september|october|"
     r"november|december)\b"),
    (r"\b(pet|pets|dog|cat)\b", r"\bpets?\b|\bdogs?\b|\bcats?\b"),
    (r"\b(lease|how long|month to month|short term)\b", r"\blease\b"),
    (r"\b(utilities|internet|wifi|electric)\b", r"\butilities\b|\binternet\b|\bwi-?fi\b"),
    (r"\b(where|address|location|located|area)\b", r"\b(way|street|road|durham|raleigh|chapel hill)\b"),
    (r"\b(bath|bathroom)\b", r"\bbath(room)?\b"),
    (r"\b(parking|park)\b", r"\bpark(ing)?\b"),
]

_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9¿¡\"'(])")


def sentences(text: str) -> list[str]:
    out = []
    for line in (text or "").splitlines():
        out += [s.strip() for s in _SPLIT.split(line.strip()) if s.strip()]
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9$ ]", "", s.lower()).strip()


def _near_dup(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    if re.findall(r"\d+", na) != re.findall(r"\d+", nb):  # different numbers ($750 vs $850) are different facts
        return False
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.88


STOP = {"with", "that", "this", "your", "have", "from", "will", "just", "also", "there", "here", "its", "it's",
        "they", "them", "then", "than", "what", "when", "would", "could", "about", "a", "an", "the", "is", "are"}


def _tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}|\d+", s.lower()) if w not in STOP}


def _covered(s: str, kept: list[str]) -> bool:
    """A statement whose numbers were all already stated and whose content words are mostly already said
    ("Rent is $750 a month." after "...a private bath for $750 a month.") adds nothing."""
    if s.rstrip().endswith("?"):
        return False
    toks = _tokens(s)
    nums = {t for t in toks if t.isdigit()}
    if not toks or not nums:
        return False
    have = set().union(*(_tokens(k) for k in kept)) if kept else set()
    return nums <= have and len(toks & have) / len(toks) >= 0.6


LINK_REF = re.compile(r"\b(link|lease|it)\b.{0,40}\b(is |are )?(included|attached|below|above|in this (message|email|text))\b",
                      re.I)


# sentences that talk about the machinery (prompt, model, tools, the "gate" checklist) never reach a renter
INTERNAL = re.compile(r"system prompt|my (instructions|prompt)|language model|nemotron|\bLLM\b|tool call|\bgate\b|"
                      r"datos de la puerta|\bthread\b|\bregister\b|does not count|doesn't count|no cuenta", re.I)


PHONE_RE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _invented_phone(s: str, renter_text: str) -> bool:
    """A sentence that echoes a phone number the renter did not write (e.g. "12345" padded to "+11234567890")."""
    said = re.sub(r"\D", "", renter_text or "")
    for m in PHONE_RE.finditer(s):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) >= 7 and d not in said and d.removeprefix("1") not in said:
            return True
    return False


def _only_refers_to_link(s: str, pool: list[str]) -> bool:
    """"The lease link is included in this message." adds nothing when the link itself is in the reply."""
    return "http" not in s and bool(LINK_REF.search(s)) and any("http" in k for k in pool)


GATE_Q = {  # a question about this gate item (EN + ES)
    "lease": r"\blease\b|one year|1 year|12 month|how long|contrato|un año|cu[aá]nto tiempo",
    "move_in": r"move[- ]?in|when .*mov|moving date|mudar|mudanza|fecha",
    "phone": r"phone|number to reach|best number|tel[eé]fono|n[uú]mero",
    "reason": r"reason|why .*mov|what brings|motivo|por qu[eé]",
    "occupants": r"how many (people|person)|who .*(living|live)|just you|personas|cu[aá]nt[oa]s|solo usted|solo t[uú]",
}
FIRST_KEEP = re.compile(r"\$\s?\d|available|disponible|private bath|baño privado|bathroom", re.I)
FIRST_DROP = re.compile(r"house rules|reglas de la casa|I'll confirm|confirmar[eé]|pets?|mascotas", re.I)


def merge(texts: list[str], renter_text: str = "", filled: set | None = None, first_sms: bool = False) -> list[str]:
    """Pooled, de-duplicated sentences: statements (answer first), then the last question."""
    pool: list[str] = []
    for t in texts:
        for s in sentences(t):
            if not any(_near_dup(s, k) for k in pool) and not _covered(s, pool):
                pool.append(s)
    pool = [s for s in pool if not _only_refers_to_link(s, pool) and not INTERNAL.search(s)
            and not _invented_phone(s, renter_text)]
    questions = [s for s in pool if s.rstrip().endswith("?")]
    statements = [s for s in pool if not s.rstrip().endswith("?")]
    if filled:  # never re-ask a gate item the register already has
        questions = [q for q in questions
                     if not any(re.search(GATE_Q[k], q, re.I) for k in filled if k in GATE_Q)]
    rq = (renter_text or "").lower()
    for ask, ans in TOPICS:
        if re.search(ask, rq):
            hit = next((s for s in statements if re.search(ans, s, re.I)), None)
            if hit:
                statements.remove(hit)
                statements.insert(0, hit)
            break
    if first_sms and len(statements) > 2:  # a first text: the answer + the key facts, the rest comes later
        keep = statements[:1] + [x for x in statements[1:] if FIRST_KEEP.search(x) and not FIRST_DROP.search(x)]
        statements = keep[:2] if len(keep) >= 2 else (keep + [x for x in statements if x not in keep
                                                              and not FIRST_DROP.search(x)])[:2]
    return statements + questions[-1:]


def _pack(sents: list[str], limit: int, max_parts: int) -> list[str]:
    whole = " ".join(sents)
    if len(whole) <= limit or max_parts == 1 or len(sents) < 2:
        return [whole] if whole else []
    # two parts, split at the sentence boundary closest to the middle
    best, best_d = 1, None
    for i in range(1, len(sents)):
        d = abs(len(" ".join(sents[:i])) - len(" ".join(sents[i:])))
        if best_d is None or d < best_d:
            best, best_d = i, d
    return [" ".join(sents[:best]), " ".join(sents[best:])]


def compose(texts: list[str], channel: str, renter_text: str = "", filled: set | None = None,
            first: bool = False) -> list[str]:
    sents = merge(texts, renter_text, filled, first_sms=first and channel in ("sms", "messenger"))
    if not sents:
        return []
    if channel == "email":  # one email, no length limit: statements, each link line, the question
        q = [x for x in sents if x.rstrip().endswith("?")]
        links = [x for x in sents if "http" in x and x not in q]
        rest = [x for x in sents if x not in q and x not in links]
        paras = [" ".join(rest)] + links + q
        return ["\n\n".join(p_ for p_ in paras if p_).strip()]
    if channel == "sms":
        return _pack(sents, SMS_MAX, 2)
    return _pack(sents, MSGR_MAX, 2)


LIVE_NOTE = """## Live channel (real renter, real phone)
- Answer the renter's actual question first, in the first sentence (for example the rent amount if they asked about rent). Then ask exactly one qualifying question that has not been answered yet. Never repeat a question in the same reply.
- Your send_message calls in this turn are combined into ONE reply to the renter, so do not repeat facts or questions across them. Each send_message is still at most 2 short sentences: put a third sentence in another send_message.
- Never send a message you already sent on this thread; read the thread and move the conversation forward.
- Before replying to anything the renter states, record it: `read_reply` on their message, then `upsert_renter` with every answered gate item (lease, move_in, phone, reason, occupants) and `capture_demand` with new criteria."""


# ---------------------------------------------------------------- email: a human-looking message

def _first_name(t: dict) -> str:
    n = (t.get("renter_name") or "").strip().split(" ")[0]
    return n if n and "@" not in n and n.lower() not in ("a", "renter") else ""


def email_body(t: dict, text: str, signoff: str = "Kalin\nRentus Homes") -> tuple[str, str]:
    """(plain, html): greeting with the first name, the reply, a sign-off, and the renter's last message quoted
    ("On <date>, <name> wrote:" with > lines)."""
    import html as _h
    from datetime import datetime
    name = _first_name(t)
    greeting = f"Hi {name}," if name else "Hi,"
    plain = f"{greeting}\n\n{text.strip()}\n\nBest,\n{signoff}\n"
    last = next((m for m in reversed(t.get("messages", [])) if m.get("direction") == "in"), None)
    quote_plain = quote_html = ""
    if last and (last.get("text") or "").strip():
        try:
            d = datetime.fromisoformat(str(last.get("ts")).replace("Z", "+00:00"))
            when = d.strftime("%a, %b %-d, %Y at %-I:%M %p")
        except (TypeError, ValueError):
            when = "an earlier date"
        who = (t.get("renter_name") or "").strip() or t.get("contact", "")
        if t.get("contact") and "@" in t["contact"] and t["contact"] not in who:
            who = f"{who} <{t['contact']}>".strip()
        header = f"On {when}, {who} wrote:"
        quote_plain = "\n" + header + "\n" + "\n".join("> " + ln for ln in last["text"].strip().splitlines()) + "\n"
        quote_html = (f'<div class="gmail_quote"><div>{_h.escape(header)}</div><blockquote style="margin:0 0 0 .8ex;'
                      f'border-left:1px solid #ccc;padding-left:1ex">{_h.escape(last["text"].strip()).replace(chr(10), "<br>")}'
                      "</blockquote></div>")
    paras = [greeting] + [p for p in text.strip().split("\n\n") if p.strip()]

    def _p(x: str) -> str:
        e = _h.escape(x)
        return __import__("re").sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', e)

    html = ("<div style=\"font-family:Arial,sans-serif;font-size:14px\">"
            + "".join(f"<p>{_p(x)}</p>" for x in paras)
            + "<p>Best,<br>" + "<br>".join(_h.escape(x) for x in signoff.split("\n")) + "</p></div>" + quote_html)
    return plain + quote_plain, html
