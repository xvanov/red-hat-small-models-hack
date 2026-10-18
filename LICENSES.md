# Licenses

Owner decision D28 (`docs/DECISIONS.md`, 2026-10-18).

| What | License | Notes |
|---|---|---|
| All code in this repository | **Apache-2.0** (`LICENSE`) | |
| Reader set, `data/published/reader/` (incl. `train_full.jsonl.gz`) | **CC BY-SA 4.0** | Mixes rows derived from Google SGD (CC BY-SA 4.0), so share-alike applies to the whole set |
| Reader weights (`xvanov/rentus-reader-qwen3-0.6b`, release `reader-v1`) | **CC BY-SA 4.0** | Trained on the reader set above; base model Qwen3-0.6B (Apache-2.0) |
| Synthetic twins, `data/published/twins/`, and v3 Gym tasks | **CC BY 4.0** | Built from the owner's own conversations (labels only, never text) and nvidia/Nemotron-Personas-USA (CC BY 4.0, attribution kept on every persona). Contains no SGD content. Twin text and labels are outputs of Nemotron 3.5 Lightning, used under NVIDIA's open model license |
| Gym tasks v1/v2, `gym/tasks/` | **CC BY 4.0** | Built only from the synthetic, team-authored rows of the reader set; no SGD-derived row is used (all 258 v2 utterances checked) |
| Owner style statistics and example replies, `data/style/` | **CC BY 4.0** | Aggregate numbers only (no text) plus 30 synthetic example replies written by an agent |
| Sandbox inventory, `data/published/inventory*.json` | **CC BY 4.0** | Derived from UCI Apartment for Rent Classified (CC BY 4.0), Inside Airbnb (CC BY 4.0) and Zillow ZORI ratios (Zillow terms of use, attribution: "Zillow Observed Rent Index (ZORI)") |

Third-party sources and their own licenses are listed in `docs/data-provenance.md`.
