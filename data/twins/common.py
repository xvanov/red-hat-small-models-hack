"""Shared pieces of the twins pipeline: paths, the local-only model client, PII scrubbing,
language detection, the reader-schema labeler and small IO helpers.

Privacy rules this module enforces (see data/twins/README.md):
  * Real conversations live OUTSIDE the repo: $RENTUS_PRIVATE_DIR (default ~/rentus-private-data),
    input/ and work/. `Paths` refuses a private dir that resolves inside the repo.
  * Model calls go only to local endpoints (OPERATOR_BASE_URL = Lightning, READER_BASE_URL = reader).
    `LocalLLM` refuses any base URL whose host is not loopback, private (RFC 1918), CGNAT/tailnet
    (100.64.0.0/10) or listed in TWINS_EXTRA_LOCAL_HOSTS. There is no code path to a hosted API.
  * Only aggregates and filtered synthetic twins are written to the published dir.

Env (read by name, never printed): OPERATOR_BASE_URL, OPERATOR_MODEL, OPERATOR_API_KEY,
READER_BASE_URL, READER_MODEL, READER_API_KEY, RENTUS_PRIVATE_DIR, TWINS_OWNER_NAMES,
TWINS_REASONING (on|off, default on: Lightning labels far better with reasoning), TWINS_EXTRA_LOCAL_HOSTS.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "reader"))  # reader/prompt.py: the reader schema prompt, shared on purpose

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

try:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env", override=False)
except ImportError:  # pragma: no cover
    pass

import prompt as reader_prompt  # noqa: E402

FIELDS = reader_prompt.FIELDS
INTENTS = reader_prompt.INTENTS
STATUSES = reader_prompt.STATUSES


# --------------------------------------------------------------------------------------------- paths
@dataclass
class Paths:
    fixture: bool
    input: Path
    work: Path
    published: Path
    tasks_out: Path

    split: str | None = None
    cache: Path | None = None
    root: Path | None = None

    @classmethod
    def make(cls, fixture: bool, split: str | None = None) -> "Paths":
        """split (real mode only): 'heldout' or 'dev' (eval-protocol section 2.2). Each split has its own
        work/<split>/ files and published outputs; the model cache and the salt are shared."""
        if fixture:
            fx = HERE / "fixtures"
            p = cls(True, fx / "input", fx / "out" / "work", fx / "out" / "published",
                    fx / "out" / "published" / "gym_tasks_v3.jsonl")
            p.root = p.work
        else:
            priv = Path(os.environ.get("RENTUS_PRIVATE_DIR", Path.home() / "rentus-private-data")).expanduser().resolve()
            for d in (priv, priv / "input", priv / "work"):
                if d == REPO or REPO in d.parents:
                    sys.exit(f"refusing: private data dir {d} is inside the repo")
            root = priv / "work" / "twins"
            if split:
                pub = REPO / "data" / "published" / "twins" / ("" if split == "heldout" else split)
                p = cls(False, priv / "input", root / split, pub, REPO / "gym" / "tasks" / "v3" / f"{split}.jsonl")
            else:
                p = cls(False, priv / "input", root, REPO / "data" / "published" / "twins",
                        REPO / "gym" / "tasks" / "v3" / "heldout.jsonl")
            p.root = root
        p.split = split
        p.cache = p.root / "cache"
        for d in (p.root, p.work, p.published, p.tasks_out.parent):
            d.mkdir(parents=True, exist_ok=True)
        if not fixture:
            for d in (p.root, p.work):
                os.chmod(d, 0o700)
        return p

    def salt(self) -> str:
        f = (self.root or self.work) / "salt"
        if not f.exists():
            f.write_text(secrets.token_hex(16))
            os.chmod(f, 0o600)
        return f.read_text().strip()


# One cap on in-flight model requests for the whole process (vLLM serves 32-64 concurrent well, see
# serving/bench-results.md). Worker threads only wait on I/O, so threads + this semaphore behave like an
# async client with a fixed number of requests in flight.
_INFLIGHT = threading.BoundedSemaphore(int(os.environ.get("TWINS_CONCURRENCY", "32")))


def set_concurrency(n: int) -> None:
    global _INFLIGHT
    _INFLIGHT = threading.BoundedSemaphore(max(1, n))


def common_args(ap):
    ap.add_argument("--fixture", action="store_true", help="run on data/twins/fixtures (fake data, outputs committed)")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N threads (dry runs)")
    ap.add_argument("--sample", type=int, default=None,
                    help="stratified sample of N threads (channel x language x outcome), seeded; caps total work")
    ap.add_argument("--concurrency", type=int, default=int(os.environ.get("TWINS_CONCURRENCY", "32")),
                    help="model requests in flight (default 32, env TWINS_CONCURRENCY)")
    ap.add_argument("--workers", type=int, default=None, help=argparse_suppress())
    ap.add_argument("--split", choices=["heldout", "dev"], default=None,
                    help="real data split (eval-protocol 2.2): work/<split>/ files, split-specific outputs")
    return ap


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS


def setup(a) -> None:
    """Apply --concurrency; worker threads = 2x in-flight so queued work is always ready."""
    set_concurrency(a.concurrency)
    a.workers = a.workers or a.concurrency * 2


def stratified_sample(items: list[dict], n: int | None, key, seed: str = "twins") -> list[dict]:
    """Up to n items, spread across strata (key(item) -> hashable) as evenly as the strata allow:
    round-robin over strata, each stratum in a seeded order. Deterministic for the same input."""
    if not n or n >= len(items):
        return items
    import random
    groups: dict = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    rng = random.Random(seed)
    order = sorted(groups, key=str)
    for g in order:
        rng.shuffle(groups[g])
    out = []
    while len(out) < n:
        for g in order:
            if groups[g] and len(out) < n:
                out.append(groups[g].pop())
    return out


def hid(*parts: str, n: int = 10) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:n]


# --------------------------------------------------------------------------------------------- io
def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def pmap(fn, items, workers: int):
    """Ordered parallel map with a progress line on stderr."""
    out = [None] * len(items)
    done = 0
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(fn, it): k for k, it in enumerate(items)}
        for fut in cf.as_completed(futs):
            out[futs[fut]] = fut.result()
            done += 1
            if done % 10 == 0 or done == len(items):
                print(f"  {done}/{len(items)}", file=sys.stderr)
    return out


# --------------------------------------------------------------------------------------------- PII scrub
URL_RE = re.compile(r"\b(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|co|us|me|ly|gl)/\S*", re.I)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE_RE = re.compile(r"(?<![\w+])(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")
PHONE_PARTIAL_RE = re.compile(r"(?<![\w+])\(?\d{3}\)?[\s.\-]\d{4}(?!\d)|(?<!\d)\d{7}(?!\d)")
STREET_SUFFIX = (r"st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|blvd|boulevard|way|pl|place|cir|circle|"
                 r"pkwy|parkway|hwy|highway|ter|terrace|trl|trail|loop|run|pt|point|sq|square|xing|crossing")
STREET_RE = re.compile(r"\b\d{1,6}[A-Za-z]?\s+(?:[A-Za-z0-9'.\-]+\s+){0,4}(?:" + STREET_SUFFIX + r")\b\.?", re.I)
STREET_ES_RE = re.compile(r"\b(?:calle|avenida|av\.|camino|carretera)\s+[\w'.\- ]{1,40}?\s*#?\s*\d{1,6}\b", re.I)
UNIT_RE = re.compile(r"\b(?:apt|apartment|unit|suite|ste|#)\s*\.?\s*[A-Za-z]?\d+[A-Za-z]?\b", re.I)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")

PLACEHOLDER_RE = re.compile(r"\[(?:URL|EMAIL|PHONE|PHONE_PARTIAL|ADDRESS|UNIT|ID|NAME|REDACTED)[^\]]*\]")


def scrub(text: str) -> tuple[str, dict]:
    """Second-layer PII scrub of REAL text. Returns (scrubbed, counts). Order matters: URLs and
    emails before phones (digits inside URLs), full phones before partial ones."""
    counts = {}

    def sub(rx, tag, t):
        new, n = rx.subn(tag, t)
        if n:
            counts[tag] = counts.get(tag, 0) + n
        return new

    t = text or ""
    t = sub(URL_RE, "[URL]", t)
    t = sub(EMAIL_RE, "[EMAIL]", t)
    t = sub(SSN_RE, "[ID]", t)
    t = sub(CARD_RE, "[ID]", t)
    t = sub(PHONE_RE, "[PHONE]", t)
    t = sub(PHONE_PARTIAL_RE, "[PHONE_PARTIAL]", t)
    t = sub(STREET_RE, "[ADDRESS]", t)
    t = sub(STREET_ES_RE, "[ADDRESS]", t)
    t = sub(UNIT_RE, "[UNIT]", t)
    return t, counts


FICTIONAL_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]?555[\s.\-]?01\d\d")


def pii_hits(text: str, allowed_phones: tuple[str, ...] = ()) -> list[str]:
    """PII-shaped strings in SYNTHETIC text. Fictional 555-01xx numbers we assigned are allowed."""
    hits = []
    if URL_RE.search(text):
        hits.append("url")
    if EMAIL_RE.search(text):
        hits.append("email")
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())[-10:]
        if not any(digits == re.sub(r"\D", "", a)[-10:] for a in allowed_phones):
            hits.append("phone")
            break
    if STREET_RE.search(text) or STREET_ES_RE.search(text):
        hits.append("address")
    if SSN_RE.search(text):
        hits.append("id")
    return hits


# --------------------------------------------------------------------------------------------- language
_ES_WORDS = set("""hola gracias cuarto habitacion habitación quiero para está esta estoy disponible renta rentar
alquiler mes meses sí buenas buenos tengo puedo cuando cuándo donde dónde que qué el la los las de por favor
mudar mudarme mudanza trabajo soy somos con una uno pero también tambien muy bien vale claro todavía todavia
sigue precio depósito deposito casa ver visita mañana manana hoy semana nosotros usted ustedes necesito""".split())
_EN_WORDS = set("""the is room available i you and to for what when thanks thank hi hello hey my me we it
this that still rent lease move in on at can could would will be are do does how much yes no ok okay please
looking interested see tomorrow today week month job work just about have has""".split())


def detect_lang(text: str, prev: str | None = None) -> str:
    t = (text or "").lower()
    words = re.findall(r"[a-záéíóúñü]+", t)
    es = sum(w in _ES_WORDS for w in words) + 2 * len(re.findall(r"[ñ¿¡]", t)) + len(re.findall(r"[áéíóú]", t))
    en = sum(w in _EN_WORDS for w in words)
    if es == en:
        return prev or "en"
    if max(es, en) < 2 and prev:
        return prev
    return "es" if es > en else "en"


# --------------------------------------------------------------------------------------------- local model client
def _is_local_host(host: str) -> bool:
    extra = {h.strip().lower() for h in os.environ.get("TWINS_EXTRA_LOCAL_HOSTS", "").split(",") if h.strip()}
    if not host:
        return False
    if host.lower() in {"localhost", "localhost.localdomain"} | extra:
        return True
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if not (ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")):
            return False
    return True


class LocalLLM:
    """OpenAI-compatible chat client restricted to local endpoints, with an on-disk response cache
    (work/cache/<role>/) so every step is idempotent and re-runs cost nothing."""

    def __init__(self, role: str, cache_dir: Path, temperature: float = 0.2, max_tokens: int = 8000,
                 reasoning: bool | None = None):
        import requests  # noqa: F401  (fail early if missing)
        self.role = role
        pre = {"operator": "OPERATOR", "reader": "READER"}[role]
        default = {"operator": "http://localhost:8000/v1", "reader": "http://localhost:8001/v1"}[role]
        self.base = os.environ.get(f"{pre}_BASE_URL", default).rstrip("/")
        host = urlparse(self.base).hostname or ""
        if not _is_local_host(host):
            sys.exit(f"refusing: {pre}_BASE_URL does not point at a local/private host. Real conversation text "
                     f"may only go to local vLLM endpoints (set TWINS_EXTRA_LOCAL_HOSTS for a private host).")
        self.key = os.environ.get(f"{pre}_API_KEY") or None
        self.model = os.environ.get(f"{pre}_MODEL") or self._first_model()
        self.temperature, self.max_tokens = temperature, max_tokens
        self.cache = cache_dir / role
        self.cache.mkdir(parents=True, exist_ok=True)
        r = os.environ.get("TWINS_REASONING", "on").lower()
        self.reasoning = None if role == "reader" else (reasoning if reasoning is not None else r == "on")
        self.calls = self.cache_hits = self.failures = 0
        self.completion_tokens = self.prompt_tokens = 0
        self._lock = threading.Lock()

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _first_model(self) -> str:
        import requests
        r = requests.get(self.base + "/models", headers=self._headers(), timeout=15)
        r.raise_for_status()
        return r.json()["data"][0]["id"]

    def chat(self, messages: list[dict], *, temperature: float | None = None, json_mode: bool = False,
             max_tokens: int | None = None, cache_key: str = "", escalate: bool = True) -> str | None:
        """escalate: when reasoning uses up max_tokens before answering, retry with 1.5x the budget. Callers
        that can simply try again another way (twin drafts) pass False and get "" instead."""
        import requests
        temp = self.temperature if temperature is None else temperature
        body = {"model": self.model, "messages": messages, "temperature": temp,
                "max_tokens": max_tokens or self.max_tokens}
        if json_mode:  # off by default: vLLM guided JSON made Lightning pad with whitespace and drop braces
            body["response_format"] = {"type": "json_object"}
        if self.reasoning is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self.reasoning}
        key = hid(json.dumps(body, sort_keys=True, ensure_ascii=False), cache_key, n=32)
        f = self.cache / f"{key}.json"
        if f.exists():
            with self._lock:
                self.cache_hits += 1
            return json.loads(f.read_text())["text"]
        # Connection errors, timeouts and 5xx (the vLLM container being restarted) are retried with backoff
        # for up to TWINS_MAX_WAIT_S seconds (default 1800); other errors get 3 attempts.
        max_wait = float(os.environ.get("TWINS_MAX_WAIT_S", "1800"))
        waited, attempt, other = 0.0, 0, 0
        while True:
            attempt += 1
            try:
                with _INFLIGHT:
                    resp = requests.post(self.base + "/chat/completions", headers=self._headers(), json=body,
                                         timeout=900)
                if resp.status_code >= 500:
                    raise ConnectionError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                js = resp.json()
                msg = js["choices"][0]["message"]
                u = js.get("usage") or {}
                with self._lock:
                    self.completion_tokens += u.get("completion_tokens") or 0
                    self.prompt_tokens += u.get("prompt_tokens") or 0
                text = msg.get("content") or ""
                if "</think>" in text:
                    text = text.split("</think>")[-1]
                if not text.strip():  # reasoning ran out of tokens before answering
                    if not escalate or other >= 2:
                        f.write_text(json.dumps({"text": ""}))
                        return ""
                    other += 1
                    body["max_tokens"] = int(body["max_tokens"] * 1.5)
                    continue
                with self._lock:
                    self.calls += 1
                f.write_text(json.dumps({"text": text}, ensure_ascii=False))
                return text
            except (requests.ConnectionError, requests.Timeout, ConnectionError) as e:
                if waited >= max_wait:
                    break
                pause = min(60.0, 3.0 * attempt)
                print(f"  [{self.role}] endpoint unavailable ({type(e).__name__}); retry in {pause:.0f}s "
                      f"(waited {waited:.0f}s)", file=sys.stderr)
                time.sleep(pause)
                waited += pause
            except Exception as e:  # noqa: BLE001
                other += 1
                print(f"  [{self.role}] retry {other}: {type(e).__name__}", file=sys.stderr)
                if other >= 3:
                    break
                time.sleep(2 * other)
        with self._lock:
            self.failures += 1
        return None

    def chat_json(self, messages, **kw) -> dict | None:
        return reader_prompt.parse_output(self.chat(messages, **kw))

    def require_healthy(self, what: str) -> None:
        """Stop before writing outputs if any call failed (endpoint down or timing out). Finished calls are
        cached, so a rerun resumes where this one stopped."""
        if self.failures:
            sys.exit(f"{what}: {self.failures} model calls failed ({self.role} endpoint down?). Nothing written; "
                     f"rerun when the endpoint is back (finished calls are cached).")

    def stats(self) -> dict:
        return {"model": self.model, "reasoning": self.reasoning, "calls": self.calls, "cache_hits": self.cache_hits,
                "failures": self.failures, "completion_tokens": self.completion_tokens,
                "prompt_tokens": self.prompt_tokens}


def log_timing(work: Path, step: str, n_threads: int, seconds: float, llms: list) -> dict:
    """Append this step's throughput and token use to work/timing.jsonl (counts only)."""
    rec = {"step": step, "threads": n_threads, "seconds": round(seconds, 1),
           "threads_per_min": round(n_threads / seconds * 60, 2) if seconds else None,
           "models": [l.stats() for l in llms]}
    with open(work / "timing.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[{step}] {n_threads} threads in {rec['seconds']} s = {rec['threads_per_min']} threads/min; "
          f"{sum(l.completion_tokens for l in llms)} completion tokens", file=sys.stderr)
    return rec


# --------------------------------------------------------------------------------------------- labeler
PLACEHOLDER_NOTE = (
    "\nThe text is anonymized. [PHONE] stands for a complete 10-digit US phone number the renter wrote "
    "(status answered, value null); [PHONE_PARTIAL] for an incomplete number (vague). [ADDRESS], [UNIT], "
    "[EMAIL], [URL], [NAME] are removed details.")


def label_message(llm: LocalLLM, today: str, context: list[dict], message: str, tag: str = "") -> dict | None:
    """Reader-schema labels for one renter message, using the reader's own prompt (reader/prompt.py),
    so labels mean exactly what the reader and the Gym mean. Returns the canonical dict or None."""
    ctx = context[-8:]
    if llm.role == "reader":  # the reader serves a 4k context: keep long earlier messages short
        ctx = [{**c, "text": c["text"][:300]} for c in ctx]
        message = message[:1200]
    inp = {"today": today, "context": ctx, "message": message}
    msgs = reader_prompt.build_messages(inp)
    msgs[0] = {"role": "system", "content": msgs[0]["content"] + PLACEHOLDER_NOTE}
    for k in range(2):
        out = llm.chat_json(msgs, temperature=0.0, max_tokens=600 if llm.role == "reader" or llm.reasoning is False else 8000,
                            cache_key=f"label{k}{tag}")
        if reader_prompt.schema_valid(out):
            return reader_prompt.canonical(out)
    return None


def is_cp(t: dict) -> bool:
    """A counterpart turn (renter, tenant or vendor): anything not written by the owner side."""
    return t["role"] != "owner"


def to_context(turns: list[dict]) -> list[dict]:
    return [{"role": "renter" if is_cp(t) else "operator", "text": t["text"]} for t in turns]


def norm_text(t: str) -> str:
    t = PLACEHOLDER_RE.sub(" ", t or "").lower()
    t = unicodedata.normalize("NFKC", t)
    return re.sub(r"\s+", " ", t).strip()
