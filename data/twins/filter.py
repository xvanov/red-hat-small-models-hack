"""Step 4: privacy filter. Every twin line is compared with EVERY real line; lines that are too close
are rewritten (blind: the rewriter never sees the real line) and re-checked, or the twin is dropped.

A twin line is flagged when, against any distinctive real line:
  * character 8-gram overlap: >= --ngram of the twin line's 8-grams occur in one real line, or a real
    line of 12+ grams is >= --ngram-real contained in the twin line;
  * embedding cosine >= --cos (paraphrase-multilingual-MiniLM-L12-v2, run locally on CPU; embedding
    models are outside the parameter budget);
  * exact match after normalization (lines of 12+ characters);
  * or it holds PII-shaped text (phone other than the twin's fictional 555-01xx number, email, URL,
    street address, id number).
Lines under --min-chars characters ("ok", "just me") carry no identifying content and skip the
similarity tests (they still get the PII test). A real line is "common", and not protected, when a
near-identical line appears in --common-k or more different real threads: a phrase many different
people wrote identifies none of them.

Twins whose draft never had a complete structure (twin.py) are dropped here too. Privacy rewrites are accepted
on the privacy tests alone (no labeler gate), so the filter does not select for easy-to-read text.

Output: work/twins_filtered.jsonl and <published>/filter_report.json (counts and thresholds only).
Usage: data/twins/.venv/bin/python data/twins/filter.py [--fixture] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import defaultdict

import numpy as np

import time

import hashlib

from common import (LocalLLM, Paths, common_args, is_cp, log_timing, setup, norm_text, pii_hits, pmap, read_jsonl,
                    write_json, write_jsonl)

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
N = 8

REWRITE_SYSTEM = """You rewrite ONE message of a synthetic rental chat because its wording is too close to a private text.
Write the same message again with completely different words and sentence structure. Keep: the speaker, the language,
roughly the same length, exactly the same meaning and facts (same dates, same phone number, same yes/no/maybe answers,
same request). Do not add any new information. Never write an address, URL, email or last name.
Return JSON only: {"text": "<new message>"}"""


def grams(s: str) -> set[str]:
    s = norm_text(s)
    return {s[k:k + N] for k in range(max(0, len(s) - N + 1))}


class RealIndex:
    def __init__(self, real_lines: list[tuple[str, str]], embedder, common_k: int, cos_common: float):
        self.texts = [t for _, t in real_lines]
        self.norm = [norm_text(t) for t in self.texts]
        self.grams = [grams(t) for t in self.texts]
        self.inv = defaultdict(set)
        for k, g in enumerate(self.grams):
            for x in g:
                self.inv[x].add(k)
        self.exact = defaultdict(set)
        for k, t in enumerate(self.norm):
            self.exact[t].add(k)
        self.embedder = embedder
        self.emb = self._cached_embed(self.texts) if self.texts else np.zeros((0, 384), dtype=np.float32)
        # distinctiveness: in how many different threads does a near-identical line appear?
        threads = np.array([tid for tid, _ in real_lines])
        self.common = np.zeros(len(self.texts), dtype=bool)
        for s in range(0, len(self.texts), 2048):
            sims = self.emb[s:s + 2048] @ self.emb.T
            for r in range(sims.shape[0]):
                hit = np.where(sims[r] >= cos_common)[0]
                self.common[s + r] = len(set(threads[hit])) >= common_k
        for t, ks in self.exact.items():
            if len({real_lines[k][0] for k in ks}) >= common_k:
                self.common[list(ks)] = True

    _lock = threading.Lock()
    cache_dir = None
    min_real = 12

    def _cached_embed(self, texts):
        if self.cache_dir is None:
            return self._embed(texts)
        key = hashlib.sha256("\x1f".join(texts).encode()).hexdigest()[:16]
        f = self.cache_dir / f"real_emb_{key}.npy"
        if f.exists():
            return np.load(f)
        e = self._embed(texts)
        np.save(f, e)
        return e

    def _embed(self, texts):
        with self._lock:
            return self._encode(texts)

    def _encode(self, texts):
        return self.embedder.encode([norm_text(t) or "." for t in texts], batch_size=64, normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False).astype(np.float32)

    def score(self, text: str) -> dict:
        """Best similarity of `text` to any distinctive real line."""
        g = grams(text)
        counts = defaultdict(int)
        for x in g:
            for k in self.inv.get(x, ()):
                if not self.common[k]:
                    counts[k] += 1
        contain = max((c / len(g) for c in counts.values()), default=0.0) if g else 0.0
        contain_real = max((c / len(self.grams[k]) for k, c in counts.items() if len(self.grams[k]) >= self.min_real),
                           default=0.0)
        cos = 0.0
        if len(self.texts):
            sims = self.emb @ self._embed([text])[0]
            sims[self.common] = -1
            cos = float(sims.max())
        exact = any(not self.common[k] for k in self.exact.get(norm_text(text), ()))
        return {"contain": contain, "contain_real": contain_real, "cos": cos, "exact": exact}


def flags(text: str, idx: RealIndex, a, phone: str) -> tuple[list[str], dict]:
    out = []
    pii = pii_hits(text, (phone,))
    if pii:
        out.append("pii")
    n = len(norm_text(text))
    sc = {"contain": 0.0, "contain_real": 0.0, "cos": 0.0, "exact": False}
    if n >= 12:
        sc = idx.score(text)
        if sc["exact"]:
            out.append("exact")
    if n >= a.min_chars_ngram and (sc["contain"] >= a.ngram or sc["contain_real"] >= a.ngram_real):
        out.append("ngram")
    if n >= a.min_chars:
        if sc["cos"] >= a.cos:
            out.append("embedding")
    return out, sc


def filter_twin(tw: dict, idx: RealIndex, llm: LocalLLM, a) -> dict:
    res = {"flagged": defaultdict(int), "regenerated": 0, "dropped": False, "lines": 0, "short_exempt": 0, "best": []}
    ctx = []
    for t in tw["turns"]:
        res["lines"] += 1
        if len(norm_text(t["text"])) < a.min_chars:
            res["short_exempt"] += 1
        fl, sc = flags(t["text"], idx, a, tw["phone"])
        tries = 0
        while fl and tries < a.rewrites:
            for f in fl:
                res["flagged"][f] += 1
            tries += 1
            spec = (f"Its labels (must stay true): {json.dumps(t['gold'], ensure_ascii=False)}" if t.get("gold")
                    else f"What it does: {', '.join(t.get('acts', []))}")
            who = "landlord" if t["role"] == "owner" else tw.get("counterpart", "renter")
            user = (f"Chat so far:\n" + "\n".join(f"{c['role']}: {c['text']}" for c in ctx[-6:]) +
                    f"\n\nMessage to rewrite ({who}): {t['text']}\n{spec}")
            out = llm.chat_json([{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": user}],
                                temperature=0.9, max_tokens=8000, cache_key=f"rewrite{tries}")
            new = (out or {}).get("text")
            if not isinstance(new, str) or not new.strip():
                continue
            # accepted on the privacy test alone: no model has to "read it correctly" first (no selection by labeler)
            t["text"] = new
            t["privacy_rewritten"] = True
            fl, sc = flags(new, idx, a, tw["phone"])
            if not fl:
                res["regenerated"] += 1
        if fl:
            for f in fl:
                res["flagged"][f] += 1
            res["dropped"] = True
            return res
        res["best"].append(sc)
        ctx.append({"role": t["role"], "text": t["text"]})
    return res


def q(xs, p):
    return round(float(np.quantile(xs, p)), 3) if xs else None


def main():
    ap = common_args(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--ngram", type=float, default=0.5)
    ap.add_argument("--ngram-real", type=float, default=0.6)
    ap.add_argument("--cos", type=float, default=0.90)
    ap.add_argument("--min-chars", type=int, default=15)
    ap.add_argument("--min-chars-ngram", type=int, default=15,
                    help="character n-gram test only for twin lines at least this long (owner export run: 30)")
    ap.add_argument("--min-real-grams", type=int, default=12,
                    help="reverse containment only for real lines with at least this many 8-grams (owner export run: 30)")
    ap.add_argument("--common-k", type=int, default=3)
    ap.add_argument("--cos-common", type=float, default=0.92)
    ap.add_argument("--rewrites", type=int, default=3)
    ap.add_argument("--calibration-note", default="", help="free text recorded in the report (how thresholds were set)")
    a = ap.parse_args()
    setup(a)
    P = Paths.make(a.fixture, a.split)
    twins = read_jsonl(P.work / "twins.jsonl")[: a.limit]
    every = (P.root / "real_lines.jsonl") if P.split else None
    if every and every.exists():  # owner's export: EVERY real line of tenants + contractors, not just this split
        real = [(r["thread_id"], r["text"]) for r in read_jsonl(every)]
    else:
        real = [(th["thread_id"], t["text"]) for th in read_jsonl(P.work / "labeled.jsonl") for t in th["turns"]]
    if not twins:
        sys.exit("no twins: run twin.py first")
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer(EMBED_MODEL, device="cpu")
    RealIndex.cache_dir = P.root
    RealIndex.min_real = a.min_real_grams
    idx = RealIndex(real, embedder, a.common_k, a.cos_common)
    llm = LocalLLM("operator", P.cache)
    t0 = time.time()

    unverified = [t for t in twins if not t.get("verified")]
    todo = [t for t in twins if t.get("verified")]
    results = pmap(lambda tw: filter_twin(tw, idx, llm, a), todo, a.workers)
    llm.require_healthy("filter")
    kept = [tw for tw, r in zip(todo, results) if not r["dropped"]]
    # final pass: nothing published may still be over a threshold
    for tw in kept:
        for t in tw["turns"]:
            fl, _ = flags(t["text"], idx, a, tw["phone"])
            assert not fl, f"filter invariant broken on {tw['twin_id']} turn {t['i']}"
    write_jsonl(P.work / "twins_filtered.jsonl", kept)

    flagged = defaultdict(int)
    for r in results:
        for k, v in r["flagged"].items():
            flagged[k] += v
    best = [s for tw, r in zip(todo, results) if not r["dropped"] for s in r["best"]]
    report = {
        "what": "Privacy filter for synthetic twins: every twin line vs every real line. Counts and thresholds only.",
        "twins_in": len(twins), "dropped_incomplete_structure": len(unverified),
        "by_category_out": {c: sum(tw.get("category", "leasing") == c for tw in kept) for c in ("leasing", "ops", "contractor")},
        "twins_checked": len(todo), "lines_checked": sum(r["lines"] for r in results),
        "lines_short_exempt_from_similarity": sum(r["short_exempt"] for r in results),
        "real_lines": len(real), "real_lines_common": int(idx.common.sum()),
        "flag_events": dict(sorted(flagged.items())),
        "lines_rewritten_and_passed": sum(r["regenerated"] for r in results),
        "twins_dropped_privacy": sum(r["dropped"] for r in results), "twins_out": len(kept),
        "kept_lines_max_similarity": {
            "char8_containment": {"p50": q([s["contain"] for s in best], .5), "p95": q([s["contain"] for s in best], .95),
                                  "max": q([s["contain"] for s in best], 1.0)},
            "embedding_cosine": {"p50": q([s["cos"] for s in best], .5), "p95": q([s["cos"] for s in best], .95),
                                 "max": q([s["cos"] for s in best], 1.0)}},
        "thresholds": {"char_ngram": N, "ngram_containment": a.ngram, "ngram_real_containment": a.ngram_real,
                       "embedding_cosine": a.cos, "min_chars_for_similarity": a.min_chars,
                       "min_chars_for_ngram": a.min_chars_ngram, "min_real_grams_reverse": a.min_real_grams, "common_k_threads": a.common_k,
                       "common_cosine": a.cos_common, "rewrites_per_line": a.rewrites},
        "embedding_model": EMBED_MODEL,
        "calibration": a.calibration_note or None,
    }
    write_json(P.published / "filter_report.json", report)
    log_timing(P.work, "filter", len(twins), time.time() - t0, [llm])
    print(json.dumps({k: report[k] for k in ("twins_in", "dropped_incomplete_structure", "by_category_out", "flag_events",
                                             "lines_rewritten_and_passed", "twins_dropped_privacy", "twins_out")}, indent=1))


if __name__ == "__main__":
    main()
