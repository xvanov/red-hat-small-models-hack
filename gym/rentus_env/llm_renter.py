"""Model-played renter (counterpart mode `llm_renter`). Opt-in per counterpart; scripted is the default.

The organizers ruled that simulator models do not count toward the 33B budget (docs/hackathon/updates.md,
2026-10-17 12:50 ET): this model plays the renter during evaluation only and is never part of the app.

A counterpart spec with `"mode": "llm_renter"` replaces the scripted lines with a persona and a hidden
truth sheet. The scorer is unchanged: the task's checks compare the final World with the truth sheet
(the converter in gym/llm_renter_tasks.py builds both from the same expected values).

    {"id": "renter:kevin", "name": "Kevin", "thread_id": "t_kevin", "channel": "craigslist", "language": "en",
     "room_of_interest": "R005", "listing_id": "L_R005", "classifier": "v2",
     "mode": "llm_renter",
     "opening": ["Hi there, I saw your listing for 1316 Marrowstone St. Still free?"],   # fixed, verbatim
     "persona": "Kevin, 29, line cook ... texts in short lowercase bursts, sometimes an emoji",
     "truth": {"move_in": "2026-10-07",               # what the checks expect
               "move_in_vague": "in a few weeks",     # optional: said first if behaviors.vague_first
               "move_in_first": {"date": "2027-01-30", "accept": "2027-03-01"},   # optional (early date):
                                                      # asks for `date` first, takes `accept` once told the room
                                                      # is not free before it
               "phone": "+19845550134", "occupants": 1, "occupants_desc": "just me",
               "reason": "my rent went up too much",
               "lease": "yes" | "shorter_then_yes", "lease_ask": "3 month leases",
               "pets": "none"},
     "behaviors": {"vague_first": true, "price_push": "any discount if I pay 3 months upfront?",
                   "ghost_after": 9,                   # stops replying after N replies (patience); null = never
                   "max_facts_per_reply": 2},          # never dumps everything at once
     "simulator": {"base_url": null, "model": null, "temperature": 0.0, "seed": 7, "max_tokens": 300}}

How a turn works (deterministic given the same operator text, seed and server):
1. Code (the "director") tracks what the renter has already revealed and turns the truth sheet and the
   behaviors into a short note for this turn ("they asked for the move-in date for the first time: answer
   only vaguely"). Hard facts (dates, phone, head-count) live only in code and the note.
2. The simulator model writes the reply as JSON {"reply", "revealed"} under a JSON schema (vLLM
   structured output), temperature 0 with a fixed seed, thinking off.
3. A consistency guard rejects a reply that states a phone number other than the truth (or an operator's
   wrong read-back accepted as correct), and retries once with the reason; on a second failure the turn falls
   back to a plain templated line. Every turn is logged (`log`) and emitted as a `renter_message` event with
   actor `renter:<id>`.

Endpoint: spec.simulator.base_url, else $RENTER_SIM_BASE_URL, else $OPERATOR_BASE_URL, else
http://localhost:8000/v1 (the local Lightning server). Key: $RENTER_SIM_API_KEY, else $OPERATOR_API_KEY.
Model: spec.simulator.model, else $RENTER_SIM_MODEL, else the endpoint's first model.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date

from .counterparts import classify_question

REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "revealed": {"type": "array", "items": {"type": "string", "enum": [
            "lease", "move_in_vague", "move_in", "phone", "occupants", "reason", "showing_ok", "none"]}},
    },
    "required": ["reply", "revealed"],
}

_MODEL_CACHE: dict[str, str] = {}
_LOCK = threading.Lock()

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]


def say_date(iso: str, lang: str = "en", year: bool = False) -> str:
    d = date.fromisoformat(iso)
    if lang == "es":
        return f"el {d.day} de {MONTHS_ES[d.month - 1]}" + (f" de {d.year}" if year else "")
    return f"{MONTHS_EN[d.month - 1]} {d.day}" + (f", {d.year}" if year else "")


def phone_digits(s: str) -> list[str]:
    """10-digit US numbers in a text (a leading 1 dropped)."""
    out = []
    for m in re.finditer(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", s or ""):
        d = re.sub(r"\D", "", m.group(0))
        out.append(d[-10:])
    return out


def _resolve_endpoint(sim: dict) -> tuple[str, str, str | None]:
    base = sim.get("base_url") or os.environ.get("RENTER_SIM_BASE_URL") or os.environ.get("OPERATOR_BASE_URL") \
        or "http://localhost:8000/v1"
    key = os.environ.get("RENTER_SIM_API_KEY") or os.environ.get("OPERATOR_API_KEY") or "EMPTY"
    model = sim.get("model") or os.environ.get("RENTER_SIM_MODEL")
    return base, key, model


class LLMRenter:
    """Same surface as counterparts.Counterpart: id, thread_id, script (openers), opening(), respond()."""

    def __init__(self, spec: dict, task: dict | None = None, client=None):
        self.spec = spec
        self.id = spec["id"]
        self.channel = spec.get("channel", "marketplace")
        self.language = spec.get("language", "en")
        self.name = spec.get("name") or self.id.split(":", 1)[-1].replace("_", " ").title()
        self.thread_id = spec.get("thread_id") or "t_" + self.id.split(":", 1)[-1]
        self.room_id = spec.get("room_of_interest")
        self.listing_id = spec.get("listing_id")
        self.classifier = spec.get("classifier", "v2")
        self.opening_lines = list(spec.get("opening") or [])
        self.script = [{"after": "start", "say": s} for s in self.opening_lines]   # run_eval.opening_goal reads this
        self.truth = dict(spec.get("truth") or {})
        self.behaviors = dict(spec.get("behaviors") or {})
        self.persona = spec.get("persona") or f"{self.name}, looking for a room to rent"
        self.sim = {"temperature": 0.0, "seed": 7, "max_tokens": 300, **(spec.get("simulator") or {})}
        self.task = task or {}
        self._client = client
        self.history: list[tuple[str, str]] = [("renter", s) for s in self.opening_lines]
        self.revealed: set[str] = set(self.behaviors.get("volunteered") or [])
        self.asked_count: dict[str, int] = {}
        self.replies_sent = 0
        self.log: list[dict] = []
        self.ghosted = False

    # ------------------------------------------------------------------------------- endpoint
    def client(self):
        if self._client is None:
            from openai import OpenAI
            base, key, _ = _resolve_endpoint(self.sim)
            self._client = OpenAI(base_url=base, api_key=key, timeout=120, max_retries=2)
        return self._client

    def model(self) -> str:
        base, _, model = _resolve_endpoint(self.sim)
        if model:
            return model
        with _LOCK:
            if base not in _MODEL_CACHE:
                _MODEL_CACHE[base] = self.client().models.list().data[0].id
            return _MODEL_CACHE[base]

    # ------------------------------------------------------------------------------- prompting
    def _listing_text(self) -> str:
        st = self.task.get("initial_state") or {}
        for l in st.get("listings") or []:
            if l.get("listing_id") == self.listing_id or l.get("room_id") == self.room_id:
                return f"{l.get('title', '')}. {l.get('body', '')}".strip()
        return "a room for rent"

    def _today(self) -> str:
        now = ((self.task.get("initial_state") or {}).get("clock") or {}).get("now") or ""
        return now[:10] or "unknown"

    def system_prompt(self) -> str:
        t, b, es = self.truth, self.behaviors, self.language == "es"
        lang = "Spanish (casual, the way you text)" if es else "English (casual, the way you text)"
        facts = []
        if t.get("move_in_first"):
            mf = t["move_in_first"]
            facts.append(f"- You would like to move in on {say_date(mf['date'], year=True)}. If the owner tells you the "
                         f"room is not available until {say_date(mf['accept'], year=True)} (or later than your date), "
                         f"you accept {say_date(mf['accept'], year=True)} as your move-in date and say so clearly.")
        elif t.get("move_in"):
            facts.append(f"- Your move-in date: {say_date(t['move_in'], year=True)}.")
        if t.get("phone"):
            d = phone_digits(t["phone"])[0] if phone_digits(t["phone"]) else t["phone"]
            facts.append(f"- Your phone number: {d[:3]}-{d[3:6]}-{d[6:]}.")
        if t.get("occupants") is not None:
            facts.append(f"- People moving in, you included: {t['occupants']} ({t.get('occupants_desc', '')}). No pets.")
        if t.get("reason"):
            facts.append(f"- Why you are moving (how you once put it): {t['reason']}")
        if t.get("lease") == "shorter_then_yes":
            facts.append(f"- Lease: you would prefer a shorter lease ({t.get('lease_ask', 'a few months')}). Once the owner "
                         f"says the minimum is longer, you agree to a one-year lease and say it plainly "
                         f"(\"ok a year works\").")
        elif t.get("lease") == "no":
            facts.append("- Lease: you will not sign a one-year lease.")
        else:
            facts.append("- Lease: a one-year lease is fine with you.")
        rules = [
            "Write ONE short text message (1 to 2 short sentences), in your own voice. Never sound like an assistant.",
            "Answer what the owner's latest message asks, using only the facts above. Never invent other facts "
            "(no other dates, numbers or people). If asked something the facts don't cover, give a short, plausible, "
            "harmless answer or say you're not sure.",
            f"Do not volunteer facts nobody asked for. At most {b.get('max_facts_per_reply', 2)} facts per message: "
            "if the owner asks for more at once, answer some and leave the rest for later.",
            "If the owner reads one of your facts back wrongly, correct them. If they read it back correctly, confirm.",
            "If the owner proposes a showing time, accept it.",
            "You never ask for the owner's personal details and you never agree to pay or sign anything in chat.",
        ]
        if b.get("vague_first") and t.get("move_in_vague"):
            rules.append(f"The first time the move-in date comes up, answer only vaguely (\"{t['move_in_vague']}\"). "
                         "Give the exact date only when they ask again.")
        if b.get("price_push"):
            rules.append("You already asked about a discount. If the owner says no or that they'll check, accept that "
                         "and keep going; do not keep pushing.")
        return (f"You are role-playing a person who is texting a landlord about a room. Stay in character.\n\n"
                f"Who you are: {self.persona}\nLanguage: {lang}.\nToday is {self._today()}.\n"
                f"The listing you are answering: {self._listing_text()}\n\n"
                f"Your private facts (the truth; never contradict them):\n" + "\n".join(facts) +
                "\n\nRules:\n" + "\n".join(f"- {r}" for r in rules) +
                "\n\nReturn JSON: {\"reply\": <your message>, \"revealed\": <list of the facts your message gives: "
                "lease, move_in_vague, move_in, phone, occupants, reason, showing_ok, or none>}.")

    def director_note(self, asked: str | None) -> str:
        """Per-turn steering from code: behaviors that must not be left to the model's memory."""
        t, b = self.truth, self.behaviors
        notes = []
        if asked == "move_in" and b.get("vague_first") and t.get("move_in_vague") and "move_in_vague" not in self.revealed \
                and "move_in" not in self.revealed:
            notes.append(f"They are asking when you want to move in. Answer ONLY vaguely, like \"{t['move_in_vague']}\". "
                         "Do not give an exact date in this message.")
        elif asked == "move_in" and t.get("move_in_first"):
            mf = t["move_in_first"]
            notes.append(f"Your preferred date is {say_date(mf['date'], self.language)}. If the owner has said the room is "
                         f"not free until {say_date(mf['accept'], self.language)}, accept {say_date(mf['accept'], self.language)} "
                         "and say that date; otherwise give your preferred date.")
        elif asked == "move_in" and "move_in" not in self.revealed and t.get("move_in"):
            notes.append(f"If you give a date now, say it with the month and day ({say_date(t['move_in'], self.language)}).")
        if asked == "lease" and t.get("lease") == "shorter_then_yes" and self.asked_count.get("lease", 0) <= 1 \
                and "lease" not in self.revealed:
            notes.append(f"First time the lease comes up: ask whether they do {t.get('lease_ask', 'shorter leases')} "
                         "instead of agreeing.")
        return " ".join(notes)

    # ---------------------------------------------------------------------------------- turns
    def opening(self) -> list[str]:
        return list(self.opening_lines)

    def respond(self, operator_text: str) -> tuple[str | None, str | None]:
        asked = classify_question(operator_text, self.classifier)   # same item label the scorer's `asked` uses
        if asked:
            self.asked_count[asked] = self.asked_count.get(asked, 0) + 1
        self.history.append(("operator", operator_text))
        ghost = self.behaviors.get("ghost_after")
        if ghost is not None and self.replies_sent >= int(ghost):
            self.ghosted = True
            self.log.append({"turn": len(self.log) + 1, "operator": operator_text, "asked": asked, "reply": None,
                             "ghosted": True})
            return asked, None
        note = self.director_note(asked)
        entry = {"turn": len(self.log) + 1, "operator": operator_text, "asked": asked, "director": note, "attempts": []}
        reply, revealed = None, []
        feedback = ""
        for attempt in range(2):
            raw, err, meta = self._generate(note, feedback)
            entry["attempts"].append({"raw": raw, "error": err, **meta})
            if err:
                feedback = ""
                continue
            reply, revealed = raw.get("reply", "").strip(), [r for r in raw.get("revealed") or [] if r != "none"]
            problem = self.consistency_problem(reply, operator_text)
            if not problem:
                break
            entry["attempts"][-1]["rejected"] = problem
            feedback = problem
            reply = None
        if not reply:
            reply, revealed = self.fallback_line(asked), ["fallback"]
            entry["fallback"] = True
        self.revealed.update(r for r in revealed if r != "fallback")
        self.history.append(("renter", reply))
        self.replies_sent += 1
        entry.update(reply=reply, revealed=revealed)
        self.log.append(entry)
        return asked, reply

    def _generate(self, note: str, feedback: str) -> tuple[dict | None, str | None, dict]:
        msgs = [{"role": "system", "content": self.system_prompt()}]
        for who, text in self.history:
            msgs.append({"role": "assistant" if who == "renter" else "user", "content": text})
        steer = " ".join(x for x in (note, f"Your previous draft was rejected: {feedback}. Fix that." if feedback else "") if x)
        if steer:
            msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + f"\n\n[stage direction for you only: {steer}]"}
        kw = {"model": self.model(), "messages": msgs, "temperature": float(self.sim["temperature"]),
              "max_tokens": int(self.sim["max_tokens"]), "seed": int(self.sim["seed"]),
              "response_format": {"type": "json_schema", "json_schema": {"name": "renter_reply", "schema": REPLY_SCHEMA}},
              "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
        t0 = time.time()
        try:
            r = self.client().chat.completions.create(**kw)
        except Exception as e:  # noqa: BLE001
            return None, f"{type(e).__name__}: {str(e)[:200]}", {"latency_s": round(time.time() - t0, 2)}
        text = (r.choices[0].message.content or "").strip()
        meta = {"latency_s": round(time.time() - t0, 2),
                "usage": {"in": getattr(r.usage, "prompt_tokens", None), "out": getattr(r.usage, "completion_tokens", None)}
                if getattr(r, "usage", None) else None}
        try:
            obj = json.loads(text[text.find("{"): text.rfind("}") + 1])
            if not isinstance(obj.get("reply"), str):
                raise ValueError("no reply")
            return obj, None, meta
        except Exception as e:  # noqa: BLE001
            return None, f"unparseable: {text[:160]!r} ({e})", meta

    def consistency_problem(self, reply: str, operator_text: str) -> str | None:
        if not reply:
            return "the message is empty"
        true_phone = phone_digits(self.truth.get("phone", ""))
        for d in phone_digits(reply):
            if true_phone and d != true_phone[0]:
                return f"it states the phone number {d}, which is not your number"
        if true_phone:   # an operator read-back with the wrong number must not be confirmed
            for d in phone_digits(operator_text):
                if d != true_phone[0] and re.match(r"\s*(yes|yep|yeah|correct|right|s[ií]|exacto|correcto)\b", reply, re.I):
                    return "the owner read back the wrong phone number and you confirmed it; correct them"
        norm = lambda x: re.sub(r"\W+", " ", x or "").strip().lower()
        if norm(reply) and norm(reply) == norm(operator_text):
            return "you repeated the owner's message word for word; answer it as yourself"
        if len(reply) > 400:
            return "the message is far too long for a text"
        return None

    def fallback_line(self, asked: str | None) -> str:
        """Deterministic last resort when the simulator fails twice. Plain and truthful."""
        t, es = self.truth, self.language == "es"
        mi = (t.get("move_in_first") or {}).get("accept") if self.asked_count.get("move_in", 0) >= 2 else None
        mi = mi or (t.get("move_in_first") or {}).get("date") or t.get("move_in")
        pd = phone_digits(t.get("phone", ""))
        lines = {
            "move_in": (f"Me gustaría mudarme {say_date(mi, 'es')}." if es else f"I'd like to move in {say_date(mi)}.") if mi else None,
            "phone": (f"Mi número es {pd[0][:3]}-{pd[0][3:6]}-{pd[0][6:]}." if es else
                      f"My number is {pd[0][:3]}-{pd[0][3:6]}-{pd[0][6:]}.") if pd else None,
            "occupants": (f"Seríamos {t.get('occupants')}." if es else f"It would be {t.get('occupants')} of us total.")
            if t.get("occupants") is not None else None,
            "reason": t.get("reason"),
            "lease": "Sí, un año está bien." if es else "Yes, a year is fine.",
            "showing": "Sí, me funciona." if es else "Yes, that works.",
        }
        return lines.get(asked or "") or ("¿Qué más necesitas saber?" if es else "What else do you need to know?")
