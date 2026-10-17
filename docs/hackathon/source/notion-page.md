# Notion page, raw text dump

- Source: https://concrete-panther-c83.notion.site/nv-rh-small-models-hack (page id 3f1f567d-17cc-805e-94e5-fdcbb49b1b81)
- Fetched: 2026-10-17 via notion.site `api/v3/loadCachedPageChunkV2` (the page is JS-rendered), subpages followed.
- Raw output below is unedited. `[BOOKMARK]` blocks print empty in the dump; their targets are:
  - Nemotron bounty subpage bookmark (3f1f567d-...-8013): https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16
  - "NVIDIA Brev Getting Started Overview" (3f2f567d-...-80ba): https://docs.nvidia.com/brev/getting-started/overview
  - Demo Video Instructions example video (d6ef567d-...-824c): https://share.descript.com/view/k2VP36YZgXn ("Policy Angel: Real-Time Factory Safety - NVIDIA Spark DGX Hackathon Demo (2025-12-14)")
- `[IMAGE]` blocks are saved in `notion-img/`:
  - 3f1f567d-...-80a0 (Nemotron bounty) -> nemotron.png
  - 3faf567d-...-8040 (NeMo Gym bounty) -> nemogym.png
  - 3f1f567d-...-80e1 (vLLM bounty) -> vllm.png
  - 3f1f567d-...-807b (Champions Choice) -> champions.png
  - 3f1f567d-...-804a (Weekend Agenda) -> agenda.png
  - 3f2f567d-...-80cd / -8009 / -80dd / -808e / -8012 (Brev steps) -> brev-step1.png ... brev-step5.png

---

NVIDIA x Red Hat Small Models Hack
October 17–18, 2026
In Person
Red Hat Annex 190 Davie St, Raleigh, NC, 27601

  ### Project Submissions

  ### Submission Link:
  [https://airtable.com/appm7NS9oN8K3friP/pagqXe6ElIlXx6oa3/form](https://airtable.com/appm7NS9oN8K3friP/pagqXe6ElIlXx6oa3/form)

  ### Demo Video Instructions:
  [SUBPAGE] Demo Video Instructions (087f567d-17cc-8239-839b-011a10c5c0d3)

  ### Submission Checklist:
  [SUBPAGE] Submission Checklist (9e5f567d-17cc-83c0-9dc7-0160ca887731)

  ### Resources
  - Ask questions, communicate with our team, connect with other hackers on the [#small-models-hack-raleigh](https://discord.gg/aNY2bgn3u) Discord channel
  - Wifi: Once checking in at the front, you should’ve received an email with the subject line: “Your personal passphrase for Red Hat Wi-Fi”. Please use that to connect to the network. 
  ⁉️ If you have any questions, please reach out in the #small-models-hack-raleigh channel in the NVIDIA [Developer Discord](https://discord.com/channels/1019361803752456192/1511402112913772654) server.

  ### The Challenge + Bounties
  Welcome to the Small Models Hack, Hosted by NVIDIA and Red Hat! We’re excited to host a diverse group of builders for a weekend. 

  ### Challenge Rules
  - Total parameters must be ≤ 33 billion (applies to the total params of all generative language models, including any used for verification, critique, routing, or speculative decoding. Embedding and reranking models are excluded). Models must have 33 billion or fewer total parameters, based on the official parameter count published in the model developer's model card. For MoE models, total parameters—not just active parameters—determine eligibility.
  - All submissions must align with one of the three challenge tracks below and meaningfully leverage open data.
    - Existing Open Data: Teams may use publicly available datasets or open-data APIs.
    - Synthetic Data: Teams may generate synthetic datasets during the hackathon, provided they publish the resulting data and methodology openly.
    - Across Tracks: Open data can be used for fine-tuning, multi-agent workflows, or tool-calling applications.
    - Documentation: Teams must reference their data sources and demonstrate how open data is incorporated into their solution.
    - Flexibility: Each track defines how your AI works, not what problem it solves—teams are free to tackle any real-world challenge through the lens of their chosen track.
  - All code required to run MUST be written during the hackathon. Open source code is allowed only if it’s been open-sourced for 2+ weeks.

  ### Main Challenge Tracks
  🎯 1. Fine-Tuned & Specialized
  Focus: A small model that's excellent at one real thing.
  The Goal: Adapt or fine-tune a small model for a specific job—then publish it openly so others can reuse it. Depth over breadth, and evidence that specialization beats general-purpose for your chosen task.
  🕸️ 2. Multi-Agent Systems
  Focus: Many small models beating one big one.
  The Goal: Wire several small models together so they coordinate—dividing up work, passing context back and forth, building on each other's output—to accomplish something no single model could alone.
  🛠️ 3. Tool-Calling
  Focus: A single model that uses real tools reliably.
  The Goal: Deciding when to call, picking the right tool, formatting valid arguments, handling what comes back, recovering from failed or malformed calls, verifying its own work, and falling back gracefully when something breaks.

  ### 💰 Additional Bounties
  Best Use of NVIDIA Nemotron Lighting
  [SUBPAGE] Best Use of [NVIDIA Nemotron](https://developer.nvidia.com/nemotron?ncid=pa-srch-goog-405472&_bt=785763502016&_bk=nvidia%20nemotron&_bm=p&_bn=g&_bg=194843200048&gad_source=1&gad_campaignid=23296574832&gbraid=0AAAAAD4XAoEzf465_17K9U0coJodVtji2&gclid=Cj0KCQiAsNPKBhCqARIsACm01fTPNZhLSPaZsibUxai4o936xFXgMWpSNyzfLqxfxi2Fm1LwrgKxxDkaAvnGEALw_wcB) Lightning (3ccf567d-17cc-82bf-bc13-817fa4369a8d)
  [IMAGE] attachment:a02cfca4-47d0-4edb-af84-4063692df229:Screenshot_2026-10-06_at_1.54.13_PM.png  id=3f1f567d-17cc-80a0-9bbe-c83496683e9d
  Best Model Improvement With NVIDIA NeMo Gym
  [IMAGE] attachment:d4e17b25-61b3-4f2c-bdb0-b98a71f122d8:Screenshot_2026-10-15_at_12.29.42_PM.png  id=3faf567d-17cc-8040-a316-cf90661e45fb
  Best Use of Red Hat vLLM
  [IMAGE] attachment:0299404c-eb57-46cf-98f8-1bd2903561dd:Screenshot_2026-10-06_at_1.55.11_PM.png  id=3f1f567d-17cc-80e1-a8fc-dd19b93d2e42
  NVIDIA Developer Champions Choice Award
  [IMAGE] attachment:52626426-97e0-4b89-97eb-8d7e0f27a0ce:Screenshot_2026-10-06_at_1.55.30_PM.png  id=3f1f567d-17cc-807b-ad98-c0f023c1e5c2

  ### Redeeming Brev Credits
  NVIDIA Brev Getting Started Overview
  [BOOKMARK]   id=3f2f567d-17cc-80ba-bcae-ec9c7d3b9830
  Adding Users to the Instance — Steps For Team Captains
  Team captains will be in charge of inviting their teammates to their Brev Org after redeeming the coupon code.
  Step 1: Please go to [http://brev.nvidia.com](https://nam11.safelinks.protection.outlook.com/?url=http%3A%2F%2Fbrev.nvidia.com%2F&data=05%7C02%7Cksteele%40nvidia.com%7C4c716c68f4544ec47e0908df232ed105%7C43083d15727340c1b7db39efd9ccc17a%7C0%7C0%7C639268356191004965%7CUnknown%7CTWFpbGZsb3d8eyJFbXB0eU1hcGkiOnRydWUsIlYiOiIwLjAuMDAwMCIsIlAiOiJXaW4zMiIsIkFOIjoiTWFpbCIsIldUIjoyfQ%3D%3D%7C0%7C%7C%7C&sdata=JiRFETHk3HIsVjUHFRL%2FZWAqHVnH8FA9D7G7KspEtxI%3D&reserved=0) and input your email to create an account.
  Step 2: Once you have signed up, please go to the 'Billing' tab located at the top of the Brev console (as shown in the screenshot below).
  [IMAGE] attachment:518cc046-023c-4b25-9223-727113b05ead:image.png  id=3f2f567d-17cc-80cd-a364-e5263d6a3c78
  Step 3: Once you have navigated to the ‘Billing’ tab, scroll down and click 'Redeem Code'. Then, enter the code you were provided in the 'Enter Code' field and click 'Redeem.'
  [IMAGE] attachment:335339ac-7791-4b01-b38f-b2dec1c51be5:image.png  id=3f2f567d-17cc-8009-a425-d3de462c94c0
  Step 4: From the “Team” tab of the Brev Console please click  “Generate Invite Link” and share with your Team. (These invite link expire after 7 days, but the team leader can generate new invite links as needed in case a user forgets to click with 7 days)
  [IMAGE] attachment:e649d6ae-d5ee-4306-abb9-25bfa49d4681:image.png  id=3f2f567d-17cc-80dd-99da-ea5cf823dee1
  5) Steps to add your teammates to your GPU Instance and give them SSH access + access to the Jupyter Notebook:
  Users first need to be added to the Org to get access to the instance. To add a user to your Brev org - you need to navigate to the 'Team' tab and click 'Generate Invite link”.
  The user who created the instance, will need navigate to the "GPU” tab, then click on the instance you want to share, scroll all the way down and need to the “Share SSH Access” section of the instance and add them. (*Instance will need to be running to share SSH access)
  If your teammate also needs access to the jupyter notebook, please make sure to add their email or username  to the “Using secure links” section by clicking the edit access button -> add username or email -> click “share”. (*Container will need to be full built before sharing SSH Access).
  [IMAGE] attachment:3b500729-e882-4949-8507-8b6aef53dea8:image.png  id=3f2f567d-17cc-808e-b61b-c5f9d4450c17
  [IMAGE] attachment:cde11ac7-c2f7-454b-b54a-d8511fae8656:image.png  id=3f2f567d-17cc-8012-9ef5-f37b955f3d71
  ‼️ Still Need Help? Please reach out to [brev-support@nvidia.com](mailto:brev-support@nvidia.com) with any issues

  ### Judging

  ### Philosophy
  We are judging Systems Engineering. A winning project isn't just a slide deck or a simple API wrapper; it's a working, end-to-end system that meaningfully uses small models to process information, take action, or solve a real-world problem.    
  1. Technical Execution & Completeness
  Did they actually build a working, complex system?
  - Completeness: Does the solution successfully execute its intended workflow end-to-end without major failures? Does it meaningfully leverage open data?
  - Technical Depth: Is there significant engineering "under the hood"? Did they implement meaningful model adaptation, multi-agent orchestration, robust tool-calling, or custom logic rather than just a basic API wrapper?
    - Fine-Tuned & Specialized: Did they successfully adapt a small model for a specific task? Can they demonstrate measurable improvement over a baseline using evaluation data?
    - Multi-Agent Systems: Do multiple small models meaningfully collaborate, divide responsibilities, and exchange information to accomplish a task beyond what a single model could easily achieve?
    - Tool-Calling: Can a single small model reliably select and execute tools, handle errors, and recover from failures rather than simply follow a hardcoded sequence of calls?
  2. NVIDIA & Red Hat Ecosystem Utility
  How effectively and meaningfully does the project leverage NVIDIA and Red Hat technologies?
  - Meaningful Technology Use: Does the project meaningfully integrate NVIDIA and/or Red Hat technologies as part of the working system—not simply include them for eligibility? Consider whether the technology plays an important role in enabling the solution.
  - Technical Advantage: Can the team clearly explain why they chose these technologies and what they enable—such as better performance, local inference, privacy, scalability, optimization, deployment, or capabilities that would otherwise be difficult to achieve?
  - Depth of Integration: How well are the technologies integrated into the overall architecture? 
  3. Value & Impact
  Is the solution actually useful?
  - Problem Fit: Does the project address a real, clearly defined problem—and does the solution meaningfully move the needle on it? Obvious or superficial framing scores low; specific, well-scoped problems score high.
  - Usability: Could a real end user—whether that's a city planner, a clinician, a logistics manager, or an everyday person—actually use this tool to make a decision or get something done tomorrow?
  4. Innovation & Execution
  Did they push the boundaries?
  - Creativity:  Did they combine data, models, or modalities in a novel way?
  - Performance: Did they optimize the system for speed or scale?
    - E.g., "We optimized the simulation to run at 50x real-time speed".

  ### Weekend Agenda
  [IMAGE] attachment:71609ce8-8585-4118-970a-7b488b1b0bfa:Screenshot_2026-10-06_at_1.50.07_PM.png  id=3f1f567d-17cc-804a-b689-deeb77b6ff4f


======== SUBPAGE 087f567d-17cc-8239-839b-011a10c5c0d3
Demo Video Instructions
Your demo video is one of the most important and powerful ways to show what your team built, and why it matters. Your demo video should be 3-5 minutes showcasing the core loop of what you built.
Use a screen recorder (Loom’s got a great Free Tier) with the camera on to show your team and give a live walkthrough of your Hackathon submission. 
Here is an example video that does a great job showcasing how to structure your demo
[BOOKMARK]   id=d6ef567d-17cc-824c-8ff2-81ca4509d59b
Here’s the flow we recommend:

### 1. Introduce Your Team
Briefly mention your team name and what you worked on. 
Ideal Time: 20 - 30 seconds.

### 2. Give a High-Level Elevator Pitch
This is your hook. Treat it like a product trailer.
- What did you end up building?
- How did you approach it?
- Why is it exciting?
Ideal Time: 30-40 seconds.

### 3. Go Into a Live Demo
Now jump straight into showing the product in action. Try to minimize editing or cuts except when impossible (if it takes a while to run, etc.)
What to demonstrate:
- The core loop of your product (input → processing → output)
- The most impressive or differentiating behavior
- Any real-time interaction, inference, or system response
Ideal Time: 45-60 seconds.

### 4. Narrate How You Built It 
This is where you show engineering depth.
While continuing the demo (or briefly switching to diagrams/slides if needed), explain:
Architecture & stack
- Frameworks, libraries, or SDKs used
- Model(s) involved and why you chose them
- Any agents, environments, pipelines, or evaluators
System design
- How hardware capabilities influenced your design
Challenges & solutions
- Key bottlenecks you hit (performance, memory, orchestration, etc.)
- Tradeoffs you made and why
- Any optimizations or creative workarounds
Ideal Time: 60 - 90 seconds.

### 5. Speak to the Why and answer “So What?”
Close by emphasizing why your project is exciting and deserves to win. Emphasize how your solution pushed the hardware to it’s limits, was complex and creative, and adds real value. Answer “So what?”.
Ideal Time: 20 - 30 seconds.


======== SUBPAGE 9e5f567d-17cc-83c0-9dc7-0160ca887731
Submission Checklist

## Due: October 18 @ 11 AM ET
One submission per team.

### Required
- Team Name
- Project Description
- Challenge selected 
- 3–5 min demo video (Unlisted YouTube/Vimeo). Show the core loop live.
  ‣ 
- Repo link (public or invite judges). Must include a README with:
  - Quick start (commands to run)
  - Tech stack & architecture diagram (simple is fine)
  - How to reproduce the demo (env vars, API keys, sample .env)
  - Any datasets/synthetic data used + provenance
  - Known limitations & next steps
- Deployed URL (if any) or short screen capture of the working app
- Team roster (names, roles, contacts)


======== SUBPAGE 3ccf567d-17cc-82bf-bc13-817fa4369a8d
Best Use of [NVIDIA Nemotron](https://developer.nvidia.com/nemotron?ncid=pa-srch-goog-405472&_bt=785763502016&_bk=nvidia%20nemotron&_bm=p&_bn=g&_bg=194843200048&gad_source=1&gad_campaignid=23296574832&gbraid=0AAAAAD4XAoEzf465_17K9U0coJodVtji2&gclid=Cj0KCQiAsNPKBhCqARIsACm01fTPNZhLSPaZsibUxai4o936xFXgMWpSNyzfLqxfxi2Fm1LwrgKxxDkaAvnGEALw_wcB) Lightning
  Beyond the main track, we are offering a dedicated bounty for the team that best integrates NVIDIA Nemotron Lightning into their local solution.
  [BOOKMARK]   id=3f1f567d-17cc-8013-897f-efa680df7c93

  ## Judging Criteria

  ### Philosophy

  ### 1. Core Model Usage
  Nemotron Lightning is central to the project’s value, not just a thin chatbot layer. The team clearly explains what Nemotron Lightning does and why it matters.

  ### 2. Technical Execution
  The demo works reliably. The team shows strong implementation choices around architecture, API use, data flow, retrieval, tool use, latency, or error handling.

  ### 3. Quality of AI Output
  Nemotron Lightning produces useful, relevant, and trustworthy outputs. The team has improved output quality through prompt design, grounding, evaluation, testing, or feedback loops.

  ### 4. Impact and Usefulness
  The project solves a real problem for a clear audience. The solution is practical, valuable, and has potential to continue beyond the hackathon.

  ### 5. Creativity and Differentiation
  The team uses Nemotron Lightning in a thoughtful or novel way. The project feels distinct from generic AI demos and shows original thinking.
