# Rules updates log (append-only)

New organizer rulings, Discord announcements, and corrections go here first, newest at the bottom, each with date, time (ET) if known, source, and exact wording. Then fold the change into `README.md` and note which section changed. Never edit or delete past entries; add a correcting entry instead.

---

## 2026-10-17 — Initial ingestion

- **What:** Built `README.md` (rules source of truth), `slides.md` (slide-by-slide transcription) and `source/` (kickoff PDF, raw Notion dump, Notion images incl. Brev screenshots).
- **Sources:** kickoff deck "Small Models Hack Raleigh_Kickoff Pres.pdf" (31 pages, all pages read as images); Notion page https://concrete-panther-c83.notion.site/nv-rh-small-models-hack plus subpages "Demo Video Instructions", "Submission Checklist" and "Best Use of NVIDIA Nemotron Lightning"; linked resources (Nemotron 3.5 Lightning BF16 + NVFP4 model cards on Hugging Face, NeMo Gym GitHub README and `vllm_model` README, Brev docs overview + quickstart).
- **Organizer clarification (kickoff, also on slides p.6 and in Notion "Challenge Rules"):** "all code required to run MUST be written during the hackathon. Open source code is allowed only if it's been open-sourced for 2+ weeks."
- **Housekeeping:** The NeMo Gym slides (pp.15-18) are marked "NVIDIA CONFIDENTIAL. DO NOT DISTRIBUTE." and this repo is public, so `source/.gitignore` excludes `kickoff-slides.pdf`. Decide before committing whether `slides.md` pp.15-18 should be committed.
- **Open questions:** 22 items in `README.md` section 10, still to be asked.

## 2026-10-17 ~12:50 ET — organizer answers on the 33B limit (relayed by the owner)
Questions asked: (1) does the limit cover only the running system, or also models used for testing/preparation (simulated users in evaluation, graders, offline data generation)? (2) do several agents on one model count it once? (3) do LoRA add-ons count extra?
Answers, verbatim:
> 1. For the running system.
> 2. No, its just about the models that are loaded to run your app. For MOE models the total parameters are counted, not just active parameters.
> 3. Technically yes, but I think its unlikely that you will add so many parameters to where it significantly increases parameter count.

Impact: simulators, graders and offline data generators don't count, so the Gym may use a model-driven renter simulator and a larger model may generate synthetic data. One loaded model counts once however many agents use it, so the multi-agent backup on Lightning is viable. LoRA weights count but are tiny.
