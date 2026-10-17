# Rules updates log (append-only)

New organizer rulings, Discord announcements, and corrections go here first, newest at the bottom, each with date, time (ET) if known, source, and exact wording. Then fold the change into `README.md` and note which section changed. Never edit or delete past entries; add a correcting entry instead.

---

## 2026-10-17 — Initial ingestion

- **What:** Built `README.md` (rules source of truth), `slides.md` (slide-by-slide transcription) and `source/` (kickoff PDF, raw Notion dump, Notion images incl. Brev screenshots).
- **Sources:** kickoff deck "Small Models Hack Raleigh_Kickoff Pres.pdf" (31 pages, all pages read as images); Notion page https://concrete-panther-c83.notion.site/nv-rh-small-models-hack plus subpages "Demo Video Instructions", "Submission Checklist" and "Best Use of NVIDIA Nemotron Lightning"; linked resources (Nemotron 3.5 Lightning BF16 + NVFP4 model cards on Hugging Face, NeMo Gym GitHub README and `vllm_model` README, Brev docs overview + quickstart).
- **Organizer clarification (kickoff, also on slides p.6 and in Notion "Challenge Rules"):** "all code required to run MUST be written during the hackathon. Open source code is allowed only if it's been open-sourced for 2+ weeks."
- **Housekeeping:** The NeMo Gym slides (pp.15-18) are marked "NVIDIA CONFIDENTIAL. DO NOT DISTRIBUTE." and this repo is public, so `source/.gitignore` excludes `kickoff-slides.pdf`. Decide before committing whether `slides.md` pp.15-18 should be committed.
- **Open questions:** 22 items in `README.md` section 10, still to be asked.
