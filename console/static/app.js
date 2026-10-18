// Rentus Operator console. Vanilla JS, no build step.
"use strict";

const CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"];
const LANE_NAMES = { marketplace: "Marketplace", roomies: "Roomies", craigslist: "Craigslist", padsplit: "PadSplit", sms: "SMS", email: "Email" };
const GATE = ["lease", "move_in", "phone", "reason", "occupants"];
const GATE_LABEL = { lease: "Lease", move_in: "Move-in", phone: "Phone", reason: "Reason", occupants: "People" };
const STATE_WORD = { ok: "answered exactly", vague: "vague, asked again", no: "no", none: "not asked yet" };
const STATUS_LABEL = { new: "New", qualifying: "Qualifying", qualified: "Qualified", showing_proposed: "Showing proposed",
  showing_confirmed: "Showing confirmed", applied: "Applied", leased: "Placed", not_now: "Parked", lost: "Closed", escalated: "Waiting on you" };
const STATUS_TONE = { qualified: "ok", showing_proposed: "accent", showing_confirmed: "ok", applied: "ok", leased: "ok", not_now: "warn", lost: "err", escalated: "warn" };
const FAULT_LABEL = { page_changed: "Page changed", malformed: "Malformed result", rate_limited: "Rate limited",
  login_required: "Login wall", timeout: "Timeout", upstream_error: "Upstream 502", not_found: "Not found" };

const S = { runId: null, es: null, seen: new Set(), status: null, badge: null, readerLabel: "rentus-reader 0.6B",
  viewTimer: null, lastView: null, seenMsgs: new Set(), editing: {}, qrUrl: null, calls: {}, group: null,
  groups: 0, reasoning: null, threadNames: {}, trust: null, cardSig: {} };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
const fix = (x, d = 3) => (x == null ? "–" : Number(x).toFixed(d));
const humanize = (s) => { s = String(s ?? ""); return /^[a-z]+(_[a-z]+)+$/.test(s) ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : s; };
const hms = (ts) => { if (!ts) return ""; const d = new Date(ts); return isNaN(d) ? String(ts).slice(11, 19) : d.toLocaleTimeString("en-GB", { hour12: false }); };
const short = (v, n = 90) => { let s = typeof v === "string" ? v : JSON.stringify(v); if (s === undefined) s = ""; return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const fmtDate = (s) => { if (!s) return ""; const d = new Date(String(s).length <= 10 ? s + "T12:00" : s); return isNaN(d) ? String(s) :
  d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + (String(s).length > 10 ? " " + d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }) : ""); };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}

// ================================================================ status, badges, demo bar
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    S.status = s; S.badge = s.badge; S.readerLabel = s.reader_label || S.readerLabel;
    setPill($("badge"), s.badge.live, s.badge.live ? "Nemotron 3.5 Lightning 30B · vLLM" : s.badge.label,
      s.badge.live ? `models: ${(s.badge.models || []).join(", ")} · config ${s.operator_config || ""} (best on the held-out Gym tasks)`
        : (s.badge.operator_import_error || "OPERATOR_BASE_URL not reachable"));
    if (s.reader) setPill($("readerBadge"), s.reader.live, s.reader.live ? "rentus-reader 0.6B" : s.reader.label.replace(/^reader: /, ""),
      s.reader.live ? "models: " + (s.reader.models || []).join(", ") : "READER_BASE_URL not reachable: read_reply uses the rule-based fallback");
    if (!S.faultsBuilt) buildFaultMenu(s.fault_kinds, s.default_fault_tool, s.fault_help || {});
    if (s.active_run && s.active_run !== S.runId) { resetUI(); attach(s.active_run); }
    if (!s.active_run && S.runId) { detach(); resetUI(); }
    const st = s.run_status || "";
    $("runinfo").innerHTML = S.runId ? `<i class="dot ${st === "running" ? "on" : "idle"}"></i>${esc(st === "running" ? "working" : st || "ready")}`
      : `<i class="dot"></i>no run`;
    $("runinfo").title = S.runId ? "run " + S.runId : "";
    renderDemo(s.demo && s.demo.run_id === S.runId ? s.demo : null, s.approve_url);
  } catch (e) { setPill($("badge"), false, "console offline", ""); }
}

function setPill(el, live, text, title) {
  el.className = "pill " + (live ? "live" : "stub");
  el.querySelector(".pv").textContent = text;
  el.title = title || "";
}

function buildFaultMenu(kinds, defaults, help) {
  S.faultsBuilt = true;
  const box = $("faultList");
  box.innerHTML = "";
  for (const k of ["page_changed", "malformed", "rate_limited", "login_required", "timeout", "upstream_error", "not_found"].filter((k) => kinds.includes(k))) {
    const b = document.createElement("button");
    b.innerHTML = `<span class="fl">${esc(FAULT_LABEL[k])}</span><span class="ft">next ${esc(defaults[k])}</span><span class="fh">${esc(help[k] || "")}</span>`;
    b.onclick = () => injectFault(k);
    box.appendChild(b);
  }
}

async function injectFault(kind) {
  $("breakMenu").classList.add("hidden");
  if (!S.runId) return sysChat("Start a run first, then break it.");
  try {
    const r = await api(`/api/runs/${S.runId}/faults`, { method: "POST", body: { kind, tool: $("faultTool").value || null } });
    sysChat(`Broke it: ${FAULT_LABEL[kind]} on the next ${r.fault.tool} call.`);
  } catch (e) { sysChat("Fault failed: " + e.message); }
}

function renderDemo(d, approveUrl) {
  const bar = $("demoBar");
  const running = !!(d && !d.finished);
  $("demoBtn").disabled = running;
  $("demoBtn").textContent = running ? "Demo running…" : "▶ Demo run";
  if (!d) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const ids = d.steps.map((s) => s.id);
  const cur = ids.indexOf(d.step);
  $("demoSteps").innerHTML = d.steps.filter((s) => s.id !== "done").map((s, i) =>
    `<li class="${i < cur || d.step === "done" ? "done" : i === cur ? "now" : ""}"><span class="b">${i < cur || d.step === "done" ? "✓" : i + 1}</span>${esc(s.title)}</li>`).join("");
  const st = d.steps[cur] || { title: "Starting", say: "" };
  $("demoTitle").textContent = d.error ? "Demo stopped" : st.title;
  $("demoSay").textContent = d.error ? d.error : st.say;
  const sec = Math.round(d.elapsed || 0);
  $("demoClock").textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  const url = d.approve_url || approveUrl || "";
  $("phoneUrl").textContent = url.replace(/^https?:\/\//, "");
  $("phoneBox").classList.toggle("hot", d.step === "approve");
  if (url && url !== S.qrUrl && window.QRCode) {
    $("qr").innerHTML = "";
    try { new QRCode($("qr"), { text: url, width: 144, height: 144 }); S.qrUrl = url; } catch (e) { /* offline: the URL text is enough */ }
  }
}

async function startDemo() {
  try {
    $("demoBtn").disabled = true;
    const r = await api("/api/demo", { method: "POST", body: { speed: parseFloat($("speed").value) } });
    resetUI(); attach(r.run_id); refreshStatus();
  } catch (e) { sysChat("Demo failed: " + e.message); $("demoBtn").disabled = false; }
}

// ================================================================ evidence panels
function ciBar(est, ci, cls = "", digits = 3, asPct = false) {
  const lo = ci ? ci[0] : est, hi = ci ? ci[1] : est;
  const f = (x) => (asPct ? pct(x, 0) : fix(x, digits));
  return `<div class="ci ${cls}" title="95% CI ${f(lo)} to ${f(hi)}"><span class="lbl">${asPct ? pct(est, 1) : fix(est, digits)}</span>
    <span class="trk"><span class="rng" style="left:${(100 * lo).toFixed(1)}%;width:${Math.max(0.6, 100 * (hi - lo)).toFixed(1)}%"></span>
    <span class="pt" style="left:${(100 * est).toFixed(1)}%"></span></span><span class="cit">${f(lo)} to ${f(hi)}</span></div>`;
}

async function loadTrust() {
  const box = $("tab-trust");
  try {
    const [t, R2] = await Promise.all([api("/api/trust"), api("/api/results")]);
    S.trust = t;
    $("kpiParams").textContent = `${t.budget.used_b}B / ${t.budget.limit_b}B`;
    const cfg = Object.fromEntries((R2.configs || []).map((c) => [c.name, c]));
    const fin = cfg.final, base = cfg.baseline, R = t.reader;
    const cmp = (R2.compare || []).find((c) => c.a === (fin && fin.label) && c.b === (base && base.label));
    const opB = t.roles[0].params_b, rdB = t.roles[1].params_b || 0, lim = t.budget.limit_b;
    box.innerHTML = `
      ${fin && base ? `<div class="tiles">
        <div class="tile hl"><div class="k">Held-out reward, final</div><div class="v">${fix(fin.mean_reward)}<small>of 1</small></div>
          <div class="d">95% CI ${fix(fin.reward_ci[0])} to ${fix(fin.reward_ci[1])} · baseline ${fix(base.mean_reward)}</div></div>
        <div class="tile"><div class="k">Tasks fully passed</div><div class="v">${pct(fin.pass_rate, 0)}<small>vs ${pct(base.pass_rate, 0)}</small></div>
          <div class="d">95% CI ${pct(fin.pass_ci[0])} to ${pct(fin.pass_ci[1])}, ${fin.tasks} tasks × ${fin.runs} runs</div></div>
        ${cmp ? `<div class="tile"><div class="k">Better than baseline on</div><div class="v">${cmp.a_better}<small>of ${cmp.tasks} tasks</small></div>
          <div class="d">worse on ${cmp.b_better} · Holm p ${cmp.p_pass_holm < 0.001 ? "< 0.001" : fix(cmp.p_pass_holm, 3)}</div></div>` : ""}
        <div class="tile"><div class="k">Parameter budget</div><div class="v">${t.budget.used_b}B<small>of ${lim}B</small></div>
          <div class="d">no paid API in the loop</div></div>
      </div>` : ""}
      <div class="h3">Who does what</div>
      <div class="roles">
        ${t.roles.map((r, i) => `<div class="role ${["op", "rd2", "vf"][i]}"><div class="rh"><b>${esc(r.who)}</b><span class="p">${r.params_b ? r.params_b + "B" : "0B"}</span></div>
          <div class="rm">${r.link ? `<a href="${esc(r.link)}" target="_blank">${esc(r.model)} ↗</a>` : esc(r.model)}</div>
          <div class="rd">${esc(r.does)}. ${esc(r.served)}.</div></div>`).join("")}
      </div>
      <div class="budget"><div class="bar"><div class="op" style="width:${(100 * opB / lim).toFixed(1)}%" title="operator ${opB}B"></div>
        <div class="rd" style="width:${Math.max(0.8, 100 * rdB / lim).toFixed(1)}%" title="reader ${rdB}B"></div></div>
        <div class="lab"><span>operator ${opB}B + reader ${rdB}B = ${t.budget.used_b}B</span><span>limit ${lim}B</span></div></div>
      <div class="h3">Reader on the same ${R.sample_n || "?"} held-out messages <span class="muted">(exact match = every field right)</span></div>
      <table class="t"><tr><th></th><th>exact match</th><th class="r">latency p50</th><th class="r">cost / read</th></tr>
        <tr class="ours"><td>rentus-reader 0.6B, fine-tuned</td><td>${ciBar(R.sample.finetuned || 0, null, "", 3, true)}</td><td class="r">${fix(R.latency_p50_s, 2)} s</td><td class="r">$0</td></tr>
        <tr><td>Claude Opus 5.5, prompted</td><td>${ciBar(R.opus_exact_match || 0, null, "base", 3, true)}</td><td class="r">${fix(R.opus_latency_p50_s, 1)} s</td><td class="r">$${fix(R.opus_cost_per_read_usd, 3)}</td></tr>
        <tr><td>Lightning 30B, prompted</td><td>${ciBar(R.sample.lightning || 0, null, "base", 3, true)}</td><td></td><td></td></tr>
        <tr><td>Rule-based fallback</td><td>${ciBar(R.sample.fallback || 0, null, "base", 3, true)}</td><td></td><td></td></tr>
      </table>
      <div class="note">${fin ? `Reliability is the weak spot: <b>${pct(fin.pass_all_runs, 0)}</b> of tasks pass in all ${fin.runs} runs, ${pct(fin.pass_any_run, 0)} in at least one. ` : ""}
        Reader trained on ${R.train_rows?.toLocaleString() || "?"} open and synthetic EN/ES messages in ${R.train_minutes || "?"} min; full test set (${R.test_rows} rows) ${pct(R.exact_match_full, 1)}.
        Published at <a href="${esc(R.hf)}" target="_blank">${esc(R.hf.replace("https://", ""))}</a>. Read live from ${esc(R2.source)} and ${t.sources.slice(2).map(esc).join(", ")}.</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">trust panel error: ${esc(e.message)}</div>`; }
}

async function loadResults() {
  const box = $("tab-score");
  try {
    const [R2, v1] = await Promise.all([api("/api/results"), api("/api/scoreboard")]);
    const cs = R2.configs || [];
    const cats = R2.categories || {};
    const catNames = Object.keys(cats.final || cats.baseline || {});
    const sign = (x, d = 3) => (x >= 0 ? "+" : "−") + Math.abs(x).toFixed(d);
    const p = (x) => (x < 0.001 ? "< 0.001" : x.toFixed(3));
    box.innerHTML = (cs.length ? `
      <div class="h3">Held-out tasks, never used for tuning <span class="muted">(${cs[0].tasks} tasks, approved task set v2)</span></div>
      <table class="t"><tr><th>config</th><th class="r">runs</th><th>mean reward, 95% CI</th><th>pass rate, 95% CI</th><th class="r">pass in every run</th><th class="r">time / task p50</th></tr>
        ${cs.map((c) => `<tr class="${c.kind === "final" ? "ours" : ""}" title="${esc(c.config_label || "")}"><td>${esc(c.label)}${c.via === "nemo" ? ' <span class="chip">NeMo Gym</span>' : ""}</td>
          <td class="r">${c.runs}</td><td>${ciBar(c.mean_reward, c.reward_ci, c.kind === "final" ? "" : "base")}</td>
          <td>${ciBar(c.pass_rate, c.pass_ci, c.kind === "final" ? "" : "base", 3, true)}</td>
          <td class="r">${c.pass_all_runs == null ? "–" : pct(c.pass_all_runs, 0)}</td><td class="r">${c.task_seconds_p50 == null ? "–" : Math.round(c.task_seconds_p50) + " s"}</td></tr>`).join("")}
      </table>
      <div class="h3">Paired tests on the same tasks <span class="muted">(Holm-corrected)</span></div>
      <table class="t"><tr><th>A vs B</th><th>Δ reward, 95% CI</th><th class="r">p</th><th class="r">Δ pass</th><th class="r">tasks A / B better</th></tr>
        ${(R2.compare || []).map((c) => { const sig = c.p_reward_holm < 0.05; const cls = !sig ? "flat" : c.d_reward > 0 ? "pos" : "neg";
          return `<tr><td>${esc(c.a)} vs ${esc(c.b)}</td><td><span class="delta ${cls}">${sign(c.d_reward)}</span> <span class="muted">(${sign(c.d_reward_ci[0])} to ${sign(c.d_reward_ci[1])})</span></td>
          <td class="r">${p(c.p_reward_holm)}</td><td class="r">${sign(100 * c.d_pass, 1)} pts</td><td class="r">${c.a_better} / ${c.b_better}</td></tr>`; }).join("")}
      </table>
      ${catNames.length ? `<div class="h3">By category, baseline → final <span class="muted">(mean reward)</span></div>
      <table class="t"><tr><th>category</th><th class="r">tasks</th><th>baseline</th><th>final</th></tr>
        ${catNames.map((k) => `<tr><td>${esc(k)}</td><td class="r">${(cats.final || cats.baseline)[k].tasks}</td>
          <td>${cats.baseline && cats.baseline[k] ? ciBar(cats.baseline[k].mean_reward, cats.baseline[k].reward_ci, "base") : "–"}</td>
          <td>${cats.final && cats.final[k] ? ciBar(cats.final[k].mean_reward, cats.final[k].reward_ci) : "–"}</td></tr>`).join("")}
      </table>` : ""}
      <div class="note">Same Lightning weights in every row; only the harness, prompt, verifier and reader change. Pass rate = every check on a task passed (Wilson interval over tasks); reward = share of checks passed (bootstrap over tasks). Computed live by gym/stats.py from ${esc(R2.source.split(" via")[0])}; write-up in ${esc(R2.doc)}.</div>`
      : `<div class="empty">No v2 held-out results yet (gym/results/v2-heldout-*).</div>`) +
      (v1.length ? `<details class="v1"><summary>Earlier v1 ablation ladder and Opus reference (superseded task set, not comparable)</summary><div class="ladder">` +
        v1.map((r) => `<div class="sb k-${esc(r.kind)}"><div class="top"><span>${esc(r.label)} <span class="muted small">${r.runner === "nemo" ? "NeMo Gym" : "our loop"} · ${r.runs} run${r.runs > 1 ? "s" : ""}</span></span>
          <span class="num">${fix(r.passed, r.passed % 1 ? 1 : 0)}/${r.tasks} · <b>${fix(r.mean_reward)}</b></span></div><div class="bar"><div style="width:${(100 * r.mean_reward).toFixed(1)}%"></div></div></div>`).join("") +
        `</div></details>` : "");
  } catch (e) { box.innerHTML = `<div class="empty">results error: ${esc(e.message)}</div>`; }
}

async function loadPerf() {
  const box = $("tab-perf");
  try {
    const P = await api("/api/performance");
    if (!P.sweep.length) { box.innerHTML = `<div class="empty">No serving benchmarks yet (${esc(P.source)}).</div>`; return; }
    const best = P.prefix.length ? P.prefix[P.prefix.length - 1] : null;
    const peak = Math.max(...P.sweep.map((r) => r.tok_s), ...(P.prefix.map((x) => x.on.tok_s)));
    const ron = P.reasoning.find((r) => r.reasoning === "on"), roff = P.reasoning.find((r) => r.reasoning === "off");
    const readerP95 = Math.max(...P.sweep.filter((r) => r.n > 1).map((r) => r.reader_p95_ms || 0));
    const maxSweep = Math.max(...P.sweep.map((r) => r.tok_s));
    const maxPre = best ? Math.max(...P.prefix.map((x) => x.on.tok_s)) : 1;
    box.innerHTML = `
      <div class="tiles">
        <div class="tile hl"><div class="k">Peak throughput</div><div class="v">${Math.round(peak).toLocaleString()}<small>tok/s</small></div><div class="d">one ${esc(P.hardware?.gpu || "GPU")}${P.hardware ? ", " + esc(P.hardware.price) : ""}</div></div>
        ${best ? `<div class="tile"><div class="k">Prefix caching</div><div class="v">+${Math.round(100 * (best.on.tok_s / best.off.tok_s - 1))}%<small>at N=${best.n}</small></div><div class="d">time to first token ${(best.on.ttft_p50_ms / 1000).toFixed(1)} s vs ${(best.off.ttft_p50_ms / 1000).toFixed(1)} s</div></div>` : ""}
        ${ron && roff ? `<div class="tile"><div class="k">Reasoning off, tool turns</div><div class="v">${roff.req_s}<small>vs ${ron.req_s} turns/s</small></div><div class="d">p95 ${roff.lat_p95_s.toFixed(1)} s vs ${ron.lat_p95_s.toFixed(1)} s, all turns still tool calls</div></div>` : ""}
        <div class="tile"><div class="k">Reader under load</div><div class="v">≤ ${readerP95}<small>ms p95</small></div><div class="d">0.6B on the same GPU at every operator load</div></div>
        <div class="tile"><div class="k">Benchmark requests</div><div class="v">${P.totals.requests.toLocaleString()}<small>${P.totals.errors} errors</small></div><div class="d">real ${P.totals.prompt_tokens?.toLocaleString()}-token prompt, ${P.totals.tools} tool schemas</div></div>
      </div>
      <div class="twocol">
        <div><div class="h3">Output tokens/s by concurrent requests</div>
          <div class="chart">${P.sweep.map((r) => `<div class="col2"><div class="bars"><div class="b" style="height:${(100 * r.tok_s / maxSweep).toFixed(1)}%" title="N=${r.n}: ${Math.round(r.tok_s)} tok/s, latency p50 ${r.lat_p50_s}s, TTFT p50 ${r.ttft_p50_ms} ms, ${r.errors} errors"><span>${Math.round(r.tok_s)}</span></div></div></div>`).join("")}</div>
          <div class="chart-x">${P.sweep.map((r) => `<span>N=${r.n}</span>`).join("")}</div></div>
        ${best ? `<div><div class="h3">Prefix caching on vs off <span class="muted">(paired runs)</span></div>
          <div class="chart-legend"><span><i></i>caching on</span><span><i class="off"></i>off</span></div>
          <div class="chart" style="height:116px">${P.prefix.map((x) => `<div class="col2"><div class="bars">
            <div class="b" style="height:${(100 * x.on.tok_s / maxPre).toFixed(1)}%" title="N=${x.n}, caching on: ${Math.round(x.on.tok_s)} tok/s"><span>${Math.round(x.on.tok_s)}</span></div>
            <div class="b off" style="height:${(100 * x.off.tok_s / maxPre).toFixed(1)}%" title="N=${x.n}, caching off: ${Math.round(x.off.tok_s)} tok/s"></div></div></div>`).join("")}</div>
          <div class="chart-x">${P.prefix.map((x) => `<span>N=${x.n}</span>`).join("")}</div></div>` : ""}
      </div>
      <div class="note">vLLM serves the 30B operator (NVFP4) and the 0.6B reader from two processes on one card. Measured with the operator's real system prompt and tools; rows from ${esc(P.source)}, method and caveats in ${esc(P.doc)}.</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">performance error: ${esc(e.message)}</div>`; }
}

async function loadReal() {
  const box = $("tab-real");
  try {
    const r = await api("/api/realworld");
    const p = r.post, st = r.stats || {};
    const lines = p && p.text ? p.text.split(" / ") : [];
    const ctr = (k, label) => `<div class="ctr"><b>${st[k] ?? "–"}</b><span>${label}</span></div>`;
    box.innerHTML = p ? `
      <div class="rw-post">${r.thumb ? `<a href="${esc(p.permalink)}" target="_blank"><img src="/api/file?path=${encodeURIComponent(r.thumb)}" alt="Appling Way room photo"></a>` : ""}
        <div><div class="livebadge"><i class="dot"></i>Live on Facebook${p.posted ? " since " + esc(p.posted) : ""}</div>
          <div class="pt">${esc(lines[0] || "Live listing")}</div><div class="pb">${esc(lines.slice(1).join(" "))}</div>
          <div class="small muted">Written by the operator (Lightning), compliance-checked, posted unedited on the Rentus Homes Facebook Page${p.photos ? ` with ${p.photos} photos` : ""}.</div>
          <div style="margin-top:8px"><a class="btn" href="${esc(p.permalink)}" target="_blank">Open the live post ↗</a></div></div></div>
      <div class="h3">Pilot inbox, shadow mode <span class="muted">(counts only)</span></div>
      <div class="counters">${ctr("inquiries", "inquiries")}${ctr("conversations", "conversations")}${ctr("drafts", "drafts written")}
        ${ctr("gate_items_captured", "gate items captured")}${ctr("escalations", "escalations")}${ctr("errors", "errors")}</div>
      <div class="note">The operator reads real replies to this post and drafts answers; it never sends. The owner replies himself, and renter text never enters the repo. Updated ${esc(st.updated_at || "–")}.</div>`
      : `<div class="empty">No pilot post recorded (docs/DECISIONS.md D20).</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">real-world panel error: ${esc(e.message)}</div>`; }
}

// ================================================================ scenarios + runs
async function loadScenarios() {
  try {
    const list = await api("/api/scenarios");
    const sel = $("scenario"), cur = sel.value;
    sel.innerHTML = '<option value="">(pick a Gym task)</option>' + list.map((s) => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join("");
    sel.value = cur;
  } catch (e) { /* gym not built */ }
}

async function startRun(goal, scenarioId) {
  const body = { goal: goal || "", speed: parseFloat($("speed").value) };
  if (scenarioId) body.scenario_id = scenarioId;
  const r = await api("/api/runs", { method: "POST", body });
  resetUI(); attach(r.run_id); refreshStatus();
}

function resetUI() {
  S.seen = new Set(); S.seenMsgs = new Set(); S.editing = {}; S.calls = {}; S.group = null; S.groups = 0; S.reasoning = null; S.cardSig = {};
  $("trace").innerHTML = ""; $("chatLog").innerHTML = "";
  renderView({ lanes: {}, register: [], escalations: [], jobs: [], quotes: [], spend: {}, calendar: [], clusters: [], rooms: {} });
}

function detach() { if (S.es) S.es.close(); S.es = null; S.runId = null; }

function attach(runId) {
  if (S.es) S.es.close();
  S.runId = runId;
  S.es = new EventSource(`/api/runs/${runId}/events`);
  S.es.onmessage = (m) => {
    let ev; try { ev = JSON.parse(m.data); } catch { return; }
    if (S.seen.has(ev._k)) return;
    S.seen.add(ev._k);
    onEvent(ev);
  };
  scheduleView(0);
}

function onEvent(ev) {
  addTrace(ev);
  const d = ev.data || {};
  if (ev.type === "owner_message" && ev.actor !== "owner" && d.summary) { /* the turn's final text follows in turn_done */ }
  else if (ev.type === "owner_message" && d.text && d.text.startsWith("Owner decision on escalation")) sysChat(d.text);
  else if (ev.type === "owner_message" && d.text) chatBubble("owner", "You", d.text);
  else if (ev.type === "model_message" && S.status?.mode === "stub" && d.text && !(d.tool_calls || []).length) chatBubble("op", opLabel(d), d.text);
  else if (ev.type === "turn_done" && d.final_text) chatBubble("op", `${opLabel(d)}${d.who ? " · about " + d.who : ""} · ${d.tool_calls} tool calls in ${d.seconds}s`, cleanReport(d.final_text));
  else if (ev.type === "escalation") sysChat("Needs you: " + humanize(d.reason || ""));
  else if (ev.type === "demo_step") sysChat(d.title, "step");
  else if (ev.type === "owner_decision") sysChat(`You ${d.decision === "approve" ? "approved" : "denied"} ${d.esc_id}${d.via ? " from the " + d.via : ""}${d.edited ? " with an edit" : ""}.`);
  if (["tool_result", "renter_message", "escalation", "owner_message", "model_message", "owner_decision"].includes(ev.type)) scheduleView(150);
}

function cleanReport(t) {
  return String(t).replace(/\*\*/g, "").replace(/^\s*Summary( for (the )?owner)?:\s*/i, "").replace(/ /g, " ").replace(/\n{2,}/g, "\n").trim();
}

function scheduleView(ms) { clearTimeout(S.viewTimer); S.viewTimer = setTimeout(refreshView, ms); }
async function refreshView() { if (!S.runId) return; try { renderView(await api(`/api/runs/${S.runId}/view`)); } catch (e) { /* run gone */ } }

// ================================================================ owner chat
function chatBubble(cls, who, text) {
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.innerHTML = `<div class="who">${esc(who)}</div><div class="body">${esc(text)}</div>`;
  $("chatLog").appendChild(div);
  const body = div.querySelector(".body");
  if (cls === "op" && body.scrollHeight > body.clientHeight + 4) {
    const m = document.createElement("div"); m.className = "more"; m.textContent = "Show all";
    m.onclick = () => { div.classList.toggle("open"); m.textContent = div.classList.contains("open") ? "Show less" : "Show all"; };
    div.appendChild(m);
  }
  $("chatLog").scrollTop = 1e9;
}
function sysChat(text, cls = "") {
  const div = document.createElement("div");
  div.className = "bubble sys " + cls;
  div.textContent = text;
  $("chatLog").appendChild(div);
  $("chatLog").scrollTop = 1e9;
}

async function sendChat(text) {
  text = text.trim();
  if (!text) return;
  $("chatInput").value = "";
  const live = S.runId && S.status && S.status.active_run === S.runId && !["stopped", "error"].includes(S.status.run_status);
  try {
    if (live) await api(`/api/runs/${S.runId}/owner`, { method: "POST", body: { text } });
    else await startRun(text, null);
  } catch (e) { sysChat("Send failed: " + e.message); }
}

// ================================================================ trace (grouped per turn)
function opLabel(d) {
  const m = (d && d.model) || "";
  if (m === "stub" || (!S.badge?.live && !m)) return "operator · stub";
  return "operator · Lightning 30B";
}

function actorOf(ev) {
  const a = ev.actor || "system", d = ev.data || {};
  if ((ev.type === "tool_call" || ev.type === "tool_result") && d.tool === "read_reply") return ["reader · 0.6B", "reader"];
  if (a === "router" || (ev.type === "verifier" && d.stage === "router")) return ["router", "router"];
  if (ev.type === "tool_result" && a === "system") return ["tools · sandbox", "tools"];
  if (a === "operator") return [opLabel(d).replace("operator · ", "operator · "), "operator"];
  if (a === "verifier") return ["verifier · code", "verifier"];
  if (a === "harness") return ["harness · code", "verifier"];
  if (a.startsWith("renter:") || a.startsWith("tenant:")) return [a.split(":")[0] + " (script)", "renter"];
  if (a.startsWith("vendor:")) return ["vendor (script)", "vendor"];
  if (a === "owner") return ["owner", "owner"];
  if (ev._src === "console") return [ev.type.startsWith("demo") || ev.type.startsWith("approve") ? "demo director" : "console", "system"];
  return [a, "system"];
}

function threadOf(ev) {
  const d = ev.data || {};
  const args = d.args || d.arguments || {};
  let t = d.thread_id || (typeof args === "object" && args ? args.thread_id : null);
  if (!t && d.call_id && S.calls[d.call_id]) t = S.calls[d.call_id].thread;
  if (!t && (ev.actor || "").includes(":")) t = "who:" + ev.actor.split(":")[1];
  return t;
}
function whoName(t) {
  if (!t) return "";
  if (S.threadNames[t]) return S.threadNames[t];
  if (t.startsWith("who:")) return t.slice(4).replace(/^./, (c) => c.toUpperCase());
  return t.replace(/^t_(tenant_)?/, "").replace(/^./, (c) => c.toUpperCase());
}

function fmtArgs(tool, a) {
  if (!a || typeof a !== "object") return short(a, 90);
  if (tool === "send_message") return `${a.thread_id ? "" : ""}“${short(a.text || "", 110)}”`;
  if (tool === "publish_listing") return `${a.channel || ""}${a.listing_id ? " · " + a.listing_id : ""}`;
  if (tool === "read_reply") return a.text || a.message ? `“${short(a.text || a.message, 90)}”` : `asking for ${a.pending_item || "the next item"}`;
  const keys = Object.keys(a).filter((k) => k !== "thread_id");
  return keys.map((k) => `${k}=${short(typeof a[k] === "string" ? a[k] : JSON.stringify(a[k]), 40)}`).join(", ");
}
function fmtResult(tool, res) {
  const d = (res && res.data) || {};
  if (tool === "publish_listing") return d.status || "ok";
  if (tool === "read_reply") {
    const f = d.fields || d;
    const items = Object.entries(f).filter(([k, v]) => k !== "backend" && v && typeof v === "object" && v.status && v.status !== "absent")
      .map(([k, v]) => `${GATE_LABEL[k] || k} ${v.status === "answered" ? "✓" : v.status}${v.date || (v.value != null && v.value !== true) ? " " + (v.date || v.value) : ""}`);
    const lang = f.language && f.language !== "en" ? ` · ${f.language}` : "";
    return short((items.join(" · ") || "nothing new") + lang, 90);
  }
  if (tool === "send_message") return d.status || "sent";
  if (tool === "upsert_renter") return d.gate_missing ? (d.gate_missing.length ? "missing " + d.gate_missing.join(", ") : "gate complete") : "saved";
  if (tool === "request_quote") return d.quote ? `$${d.quote.amount}` : "ok";
  if (tool === "book_vendor") return d.job?.status || "booked";
  if (d && typeof d === "object" && !Array.isArray(d)) {
    const parts = Object.entries(d).slice(0, 4).map(([k, v]) => Array.isArray(v) ? `${v.length} ${k}`
      : v && typeof v === "object" ? (v.status ? `${k} ${v.status}` : k) : `${k} ${short(String(v), 28)}`);
    return short(parts.join(" · "), 80);
  }
  return short(d, 60);
}

const TRIGGERS = new Set(["owner_message", "renter_message"]);  // console notes arrive from a second file, so they never open a group

function groupFor(ev) {
  const d = ev.data || {};
  const isTrigger = TRIGGERS.has(ev.type) && !(ev.type === "owner_message" && ev.actor !== "owner");
  if (isTrigger || !S.group) {
    let title = "Run", quote = "", kind = "sys";
    if (ev.type === "owner_message") { title = d.text?.startsWith("Owner decision") ? "Your decision" : "You"; quote = d.text || ""; kind = "owner"; }
    else if (ev.type === "renter_message") { title = `${d.name || whoName(threadOf(ev))} wrote${d.channel ? " on " + (LANE_NAMES[d.channel] || d.channel) : ""}`; quote = d.text || ""; kind = "renter"; }
    else if (ev.type === "demo_step") { title = "Demo step"; quote = d.title || ""; }
    else if (ev.type === "owner_decision") { title = "Your decision"; quote = `${d.decision} ${d.esc_id}${d.via ? " via " + d.via : ""}`; kind = "owner"; }
    else if (ev.type === "fault_injected") { title = "Broke it on purpose"; quote = `${FAULT_LABEL[d.kind] || d.kind} on the next ${d.tool}`; kind = "fault"; }
    else if (ev.type === "scenario") { title = "Gym scenario"; quote = d.scenario_id || ""; }
    const g = document.createElement("div");
    g.className = "tg k-" + kind;
    g.innerHTML = `<div class="tg-h"><span class="car">▾</span><span class="ts">${esc(hms(ev.ts))}</span><span class="tt">${esc(title)}</span>
      <span class="tq">${quote ? "“" + esc(short(quote, 140)) + "”" : ""}</span><span class="tc"></span></div><div class="tg-b"></div>`;
    g.querySelector(".tg-h").onclick = () => g.classList.toggle("folded");
    g._n = 0; g._rec = 0;
    g.dataset.ts = ev.ts || "";
    $("trace").appendChild(g);
    S.group = g; S.groups++;
    foldOld();
    if (isTrigger) return { g, header: true };
  }
  if (ev.ts && S.group.dataset.ts && ev.ts < S.group.dataset.ts) {  // a late console note: file it under the turn it happened in
    const gs = [...$("trace").children];
    const home = gs.filter((x) => x.dataset.ts && x.dataset.ts <= ev.ts).pop() || gs[0];
    return { g: home, header: false };
  }
  return { g: S.group, header: false };
}

function foldOld() {  // keep the newest groups open; older groups fold unless they hold a recovery
  const gs = [...$("trace").children];
  gs.slice(0, Math.max(0, gs.length - 4)).forEach((g) => { if (!g._rec && !g._pinned) g.classList.add("folded"); });
  while ($("trace").childElementCount > 200) $("trace").removeChild($("trace").firstChild);
}

function bump(g, rec) {
  g._n++;
  if (rec) markRec(g); else drawCount(g);
}
function markRec(g) { g._rec++; g.classList.add("has-rec"); g.classList.remove("folded"); drawCount(g); }
function drawCount(g) {
  g.querySelector(".tc").innerHTML = `${g._n} step${g._n === 1 ? "" : "s"}${g._rec ? ` · <span class="rc-n">${g._rec} recover${g._rec === 1 ? "y" : "ies"}</span>` : ""}`;
}

function addRow(g, ev, cls, html, title) {
  const [label, acls] = actorOf(ev);
  const t = threadOf(ev);
  const row = document.createElement("div");
  row.className = "row " + cls;
  row.innerHTML = `<span class="ts">${esc(hms(ev.ts))}</span><span class="actor a-${acls}">${esc(label)}</span>
    <span class="who">${esc(whoName(t))}</span><span class="s">${html}</span>`;
  row.title = title || row.querySelector(".s").textContent;
  row.dataset.ts = ev.ts || "";
  const body = g.querySelector(".tg-b");
  let before = null;  // console notes come from a second file: keep rows in time order
  if (ev.ts && body.lastElementChild && body.lastElementChild.dataset.ts > ev.ts) before = [...body.children].find((el) => el.dataset.ts > ev.ts) || null;
  body.insertBefore(row, before);
  bump(g, /\b(err|retry|vfail|fb|fault)\b/.test(cls));
  return row;
}

function addTrace(ev) {
  const d = ev.data || {};
  if (ev.type === "renter_message" && d.thread_id && d.name) S.threadNames[d.thread_id] = d.name;
  const { g, header } = groupFor(ev);
  if (header) { followTrace(); return; }
  let row = null;
  switch (ev.type) {
    case "model_message": {
      if ((d.tool_calls || []).length && !d.text) { S.reasoning = d.reasoning || null; return; }  // folded into the tool row below
      if (!d.text) return;
      row = addRow(g, ev, "msg", `says: ${esc(short(d.text.replace(/\*\*/g, ""), 220))}`, d.text);
      break;
    }
    case "tool_call": {
      const tool = d.tool || d.name;
      const args = d.args ?? d.arguments ?? {};
      row = addRow(g, ev, "tool pending", `<span class="tool">${esc(tool)}</span> <span class="res">${esc(fmtArgs(tool, args))}</span> <span class="res">…</span>`,
        (S.reasoning ? "Why: " + short(S.reasoning, 600) + "\n\n" : "") + tool + " " + JSON.stringify(args));
      S.reasoning = null;
      if (d.call_id) S.calls[d.call_id] = { row, tool, args, thread: typeof args === "object" && args ? args.thread_id : null };
      break;
    }
    case "tool_result": {
      const res = d.result || {};
      const ok = d.ok ?? res.ok;
      const err = d.error || res.error;
      const fault = d.fault ? (typeof d.fault === "string" ? d.fault : d.fault.kind || "fault") : null;
      const call = d.call_id && S.calls[d.call_id];
      const tool = d.tool || call?.tool || "";
      const outcome = ok === false ? `<span class="errm">✗ ${esc(err?.code || "error")}${err?.message ? ": " + esc(short(err.message, 90)) : ""}</span>`
        : `<span class="okm">✓</span> <span class="res">${esc(fmtResult(tool, res))}</span>`;
      const fx = fault ? ` <span class="errm">[injected ${esc(fault)}]</span>` : "";
      if (call && call.row && call.row.parentElement) {
        const r = call.row;
        r.classList.remove("pending");
        if (ok === false || fault) { r.classList.add("err"); markRec(r.closest(".tg")); }
        r.querySelector(".s").innerHTML = `<span class="tool">${esc(tool)}</span> <span class="res">${esc(fmtArgs(tool, call.args))}</span> → ${outcome}${fx}`;
        if (tool === "read_reply") { const be = res.data?.backend; r.querySelector(".actor").textContent = be === "fallback" ? "reader · rules" : "reader · 0.6B"; }
        r.title += "\n→ " + JSON.stringify(res).slice(0, 800);
        followTrace();
        return;
      }
      row = addRow(g, ev, ok === false || fault ? "err" : "ok", `<span class="tool">${esc(tool)}</span> → ${outcome}${fx}`);
      break;
    }
    case "verifier": {
      if (d.stage === "router") { row = addRow(g, ev, "msg", `routed: ${esc(d.decision || d.route || d.action || "")}${d.reason ? " · " + esc(d.reason) : ""}`); break; }
      if (d.stage === "policy") {
        const cls = d.action === "retry" ? "retry" : d.action === "fallback" ? "fb" : "vfail";
        row = addRow(g, ev, cls, `policy: ${esc(d.tool || "")} ${esc(d.code || "")} → ${esc(d.action || "")}${d.note ? " (" + esc(d.note) + ")" : ""}`); break;
      }
      const what = d.check || d.stage || "";
      const extra = d.detail || [].concat(d.problems || [], d.repaired || [], d.errors || []).join("; ");
      if (d.ok !== false && S.hidePasses) return;
      row = addRow(g, ev, d.ok === false ? "vfail" : "vok", `${d.ok === false ? "✗ caught" : "✓ pass"} ${esc(what)}${d.tool ? " on " + esc(d.tool) : ""}${extra ? ": " + esc(short(extra, 160)) : ""}`);
      break;
    }
    case "retry": row = addRow(g, ev, "retry", `↻ retry ${esc(d.tool || "")} (attempt ${esc(d.attempt ?? "?")}) after ${esc(d.code || d.reason || d.error || "")}${d.delay_s ? `, waited ${esc(d.delay_s)}s` : ""}`); break;
    case "fallback": row = addRow(g, ev, "fb", `⤳ fallback ${esc(d.tool ? d.tool + ": " : "")}${esc(d.code ? d.code + " · " : "")}${esc(d.from ? d.from + " → " : "")}${esc(d.to || d.note || "")}${d.suggestion ? " → " + esc(d.suggestion) : ""}${d.reason ? " (" + esc(short(d.reason, 100)) + ")" : ""}`); break;
    case "escalation": row = addRow(g, ev, "esc", `⚑ asks you: ${esc(humanize(d.reason || ""))}${d.draft ? " · draft “" + esc(short(d.draft, 90)) + "”" : ""}`); break;
    case "fault_injected": row = addRow(g, ev, "fault", `⚡ next ${esc(d.tool)} will fail: ${esc(FAULT_LABEL[d.kind] || d.kind)}${d.match ? " " + esc(JSON.stringify(d.match)) : ""}`); break;
    case "demo_step": row = addRow(g, ev, "step-row", `▶ demo step: ${esc(d.title || "")}`); break;
    case "owner_decision": row = addRow(g, ev, "esc", `you ${d.decision === "approve" ? "approved" : "denied"} ${esc(d.esc_id)}${d.via ? " from the " + esc(d.via) : ""}${d.edited ? " with your own wording" : ""}`); break;
    case "scenario": row = addRow(g, ev, "msg", `Gym scenario ${esc(d.scenario_id)}: ${esc(d.counterparts)} scripted counterparts, ${(d.faults || []).length} scripted faults`); break;
    case "approve_wait": row = addRow(g, ev, "esc", d.open ? `waiting for you: ${esc(d.open)} decision(s) on the phone` : `owner approval: ${esc(d.detail || "nothing open")}`); break;
    case "demo_nudge": row = addRow(g, ev, "msg", `nothing was waiting for you, so Devon writes again: “${esc(d.text)}”`); break;
    case "approve_done": row = addRow(g, ev, "msg", `you decided after ${esc(d.waited_s)}s`); break;
    case "turn_done": row = addRow(g, ev, "done-row", `turn done${d.who ? " for " + esc(d.who) : ""}: ${esc(d.status)}, ${esc(d.tool_calls)} tool calls in ${esc(d.seconds)}s`); break;
    case "owner_message": row = addRow(g, ev, "msg", `report to you: ${esc(short(d.summary || d.text || "", 200))}`); break;
    case "score": row = addRow(g, ev, "ok", `score ${esc(short(d, 160))}`); break;
    default: row = addRow(g, ev, "msg", `${esc(ev.type)}: ${esc(short(d, 160))}`);
  }
  followTrace();
}

function followTrace() { if ($("followTrace").checked) $("traceScroll").scrollTop = 1e9; }

// ================================================================ view
function imgSrc(shot) {
  if (!shot) return null;
  if (shot.startsWith("data:") || shot.startsWith("http")) return shot;
  return "/api/file?path=" + encodeURIComponent(shot);
}

function renderChannels(v) {
  const lanes = v.lanes || {};
  const names = [...CHANNELS, ...Object.keys(lanes).filter((c) => !CHANNELS.includes(c))];
  const lst = (v.listings || []).slice(-1)[0];
  let html = lst ? `<div class="listing"><div><div class="t">${esc(lst.title || "Listing")}</div><div class="s">$${esc(lst.price)} · ${esc(lst.room_id || "")} · ${esc(lst.status || "")}</div></div></div>`
    : `<div class="listing"><div><div class="t muted">No listing yet</div><div class="s">tell the operator which room is free</div></div></div>`;
  for (const ch of names) {
    const L = lanes[ch] || { posts: [], threads: [] };
    const p = L.posts.slice(-1)[0];
    const st = p ? (p.status || "draft") : null;
    const cls = !st ? "idle" : st === "live" ? "live" : /fail|error|broken|blocked/.test(st) ? "failed" : "ready";
    const src = p && imgSrc(p.screenshot);
    const threads = L.threads.length;
    html += `<div class="chan ${cls}" title="${esc(p ? p.url || st : "not posted")}"><div class="cn"><i class="dot"></i>${esc(LANE_NAMES[ch] || ch)}</div>
      <div class="cs">${st ? esc(humanize(st)) : "not posted"}${threads ? ` · ${threads} thread${threads === 1 ? "" : "s"}` : ""}</div>
      ${src ? `<a href="${esc(src)}" target="_blank"><img src="${esc(src)}" alt="${esc(ch)} screenshot"></a>` : ""}</div>`;
  }
  $("channels").innerHTML = html;
}

function convoHtml(msgs, n = 2) {
  return msgs.slice(-n).map((m) => {
    const key = `${m._t}:${m._i}`;
    const fresh = !S.seenMsgs.has(key); S.seenMsgs.add(key);
    return `<div class="m ${m.from === "operator" ? "operator" : "renter"}${fresh ? " new" : ""}">${esc(m.text)}</div>`;
  }).join("");
}

function renderPipeline(v) {
  const threads = {};
  for (const [ch, L] of Object.entries(v.lanes || {})) for (const t of L.threads) {
    threads[t.thread_id] = { ...t, channel: ch, messages: t.messages.map((m, i) => ({ ...m, _t: t.thread_id, _i: i })) };
    if (t.renter_name) S.threadNames[t.thread_id] = t.renter_name.replace(/\s*\(tenant\)/, "");
  }
  const cards = { inquiry: [], qualified: [], showing: [], application: [] };
  const used = new Set();
  const cal = Object.fromEntries((v.calendar || []).filter((e) => ["proposed", "confirmed"].includes(e.status)).map((e) => [e.renter_id, e]));
  for (const r of v.register || []) {
    const stage = r.stage || "inquiry";
    if (!cards[stage]) continue;
    const ts = (r.thread_ids || []).map((id) => threads[id]).filter(Boolean);
    ts.forEach((t) => used.add(t.thread_id));
    const t = ts[0];
    const g = r.gate || {};
    const done = GATE.filter((k) => (g[k] || {}).state === "ok").length;
    const facts = [g.move_in?.state === "ok" ? "in " + fmtDate(g.move_in.value) : null, g.occupants?.state === "ok" ? `${g.occupants.value} ${g.occupants.value == 1 ? "person" : "people"}` : null,
      g.reason?.state === "ok" ? g.reason.value : null].filter(Boolean).join(" · ");
    const show = cal[r.renter_id];
    cards[stage].push({ id: r.renter_id, sig: JSON.stringify([r.status, g, t && t.messages.length, show]), html: `
      <div class="h"><span class="nm">${esc(r.name)}</span>${t ? `<span class="chip">${esc(LANE_NAMES[t.channel] || t.channel)}</span>` : ""}${(r.language || t?.language) && (r.language || t?.language) !== "en" ? `<span class="chip accent">${esc(r.language || t.language)}</span>` : ""}</div>
      <div class="meta">${esc(STATUS_LABEL[r.status] || humanize(r.status || "new"))} · ${done}/5 gate${facts ? " · " + esc(facts) : ""}</div>
      <div class="gate">${GATE.map((k) => `<span class="g ${(g[k] || {}).state || "none"}" title="${GATE_LABEL[k]}: ${STATE_WORD[(g[k] || {}).state || "none"]}${g[k]?.value != null ? " (" + esc(g[k].value) + ")" : ""}"></span>`).join("")}</div>
      <div class="gate-l">${GATE.map((k) => `<span class="${(g[k] || {}).state || "none"}">${GATE_LABEL[k]}</span>`).join("")}</div>
      ${show ? `<div class="show"><b>Showing ${esc(show.status)}</b> ${esc(fmtDate(show.start))}</div>` : ""}
      ${t ? `<div class="convo">${convoHtml(t.messages)}</div>` : ""}` });
  }
  for (const t of Object.values(threads)) {
    if (used.has(t.thread_id) || t.kind === "tenant") continue;
    cards.inquiry.push({ id: t.thread_id, sig: JSON.stringify([t.messages.length]), html: `
      <div class="h"><span class="nm">${esc(t.renter_name || t.thread_id)}</span><span class="chip">${esc(LANE_NAMES[t.channel] || t.channel)}</span>${t.language && t.language !== "en" ? `<span class="chip accent">${esc(t.language)}</span>` : ""}</div>
      <div class="meta">New inquiry · not in the register yet</div>
      <div class="gate">${GATE.map(() => `<span class="g none"></span>`).join("")}</div>
      <div class="convo">${convoHtml(t.messages)}</div>` });
  }
  for (const col of document.querySelectorAll(".stage")) {
    const list = cards[col.dataset.stage] || [];
    col.querySelector(".n").textContent = list.length;
    const body = col.querySelector(".stage-b");
    const sig = list.map((c) => c.id + c.sig).join("|");
    if (body.dataset.sig === sig) continue;
    body.dataset.sig = sig;
    body.innerHTML = list.length ? list.map((c) => {
      const changed = S.cardSig[c.id] !== undefined && S.cardSig[c.id] !== c.sig;
      S.cardSig[c.id] = c.sig;
      return `<div class="rc${changed ? " flash" : ""}" data-id="${esc(c.id)}">${c.html}</div>`;
    }).join("") : `<div class="empty">${{ inquiry: "Renters show up here as they write in", qualified: "All five gate items answered exactly", showing: "Proposed, waiting on your confirmation", application: "Applications and placements" }[col.dataset.stage]}</div>`;
  }
  return threads;
}

function renderRegister(v) {
  const reg = v.register || [];
  $("regCount").textContent = reg.length ? `${reg.length} ${reg.length === 1 ? "person" : "people"} · never deleted` : "";
  $("register").innerHTML = reg.length ? reg.map((r) => {
    const w = r.wants || {}, g = r.gate || {};
    const area = [].concat((w.areas && (w.areas.resolved || w.areas.raw)) || w.area || []).join(", ");
    const parts = [area && `<span class="k">area</span> ${esc(area)}`, w.type && esc(w.type), w.budget_max_usd && `<span class="k">≤</span> $${esc(w.budget_max_usd)}`,
      (g.move_in?.value || w.move_in) && `<span class="k">move-in</span> ${esc(fmtDate(g.move_in?.value || w.move_in))}`,
      g.occupants?.value && `${esc(g.occupants.value)} ${g.occupants.value == 1 ? "person" : "people"}`,
      r.reconnect_at && `<span class="k">reconnect</span> ${esc(fmtDate(r.reconnect_at))}`,
      r.listing_of_interest && `<span class="k">asked about</span> ${esc(r.listing_of_interest)}`].filter(Boolean);
    return `<div class="rr"><span class="nm">${esc(r.name)}<span class="src">${esc(r.channel || "")}${r.language ? " · " + esc(r.language) : ""}</span></span>
      <span class="chip ${STATUS_TONE[r.status] || ""}">${esc(STATUS_LABEL[r.status] || humanize(r.status || "new"))}</span>
      <span class="w">${parts.join(" · ") || '<span class="k">criteria not stated yet</span>'}</span></div>`;
  }).join("") : `<div class="empty">Every inquiry lands here, whether or not a room fits today.</div>`;
}

function renderClusters(v) {
  const cl = v.clusters || [], sig = v.supply_signals || [], rooms = v.rooms || {};
  let html = rooms.total ? `<div class="inv">${rooms.total} rooms in inventory · ${rooms.listed || 0} listed now</div>` : "";
  html += sig.map((s) => `<div class="cl"><div class="h"><b>${esc(s.title || s.key || "Supply signal")}</b><span class="chip ok">SIGNAL</span></div>
    <div class="s">${esc(s.summary || s.note || JSON.stringify(s).slice(0, 160))}</div></div>`).join("");
  html += cl.map((c) => `<div class="cl"><div class="h"><b>${esc(c.area)} · ${esc(c.type)}</b>
      <span class="chip ${c.level === "signal" ? "ok" : c.level === "watch" ? "warn" : ""}">${c.level === "signal" ? "SUPPLY SIGNAL" : c.level === "watch" ? "WATCH" : "forming"}</span></div>
    <div class="bar">${[0, 1, 2, 3, 4].map((i) => `<i class="${i < c.qualified ? "q" : i < c.people ? "p" : ""}"></i>`).join("")}</div>
    <div class="s">$${c.band[0]} to $${c.band[1]} · ${c.people} active, ${c.qualified} qualified of 5 needed${c.inferred ? " · from the room they asked about" : ""} · ${esc(c.names.join(", "))}</div></div>`).join("");
  if (!cl.length && !sig.length) html += `<div class="empty">No demand yet.</div>`;
  html += `<div class="explain">People who want the same area, type and $150 budget band form a cluster. 3 active is WATCH; 5 qualified is a supply signal: the tenants are already waiting, so it is time to find a matching house.</div>`;
  $("clusters").innerHTML = html;
}

function renderEscalations(v, threads) {
  const list = v.escalations || [];
  const open = list.filter((e) => !e.status || e.status === "open");
  const shows = (v.calendar || []).filter((e) => e.status === "proposed");
  const names = Object.fromEntries((v.register || []).map((r) => [r.renter_id, r.name]));
  $("escCount").textContent = (open.length + shows.length) || "";
  if (Object.values(S.editing).some(Boolean)) return;  // never wipe a reply the owner is typing
  const escHtml = list.slice().reverse().map((e) => {
    const isOpen = !e.status || e.status === "open";
    const t = threads[e.thread_id || e.ref_id] || null;
    const last = t ? [...t.messages].reverse().find((m) => m.from === "renter") : null;
    const job = (v.jobs || []).find((j) => j.job_id === (e.job_id || e.ref_id));
    const who = t ? t.renter_name : job ? job.property : e.ref_id || "Decision";
    return `<div class="esc ${isOpen ? "" : "done"}" data-esc="${esc(e.esc_id)}">
      <div class="top"><b>${esc(who)}</b>${t ? `<span class="chip">${esc(LANE_NAMES[t.channel] || t.channel)}</span>` : ""}
        ${isOpen ? '<span class="chip accent">decide</span>' : `<span class="chip ${e.status === "approved" ? "ok" : "err"}">${esc(e.status)}</span>`}${e.decided_via ? `<span class="via">via ${esc(e.decided_via)}</span>` : ""}</div>
      ${last ? `<div class="q">“${esc(short(last.text, 160))}”</div>` : ""}
      <div class="r">${esc(humanize(e.reason))}</div>
      ${e.draft || e.owner_text ? `<div class="d"><span class="lbl">${e.owner_text ? "Your reply" : "Drafted reply"}</span>${esc(e.owner_text || e.draft)}</div>` : ""}
      ${isOpen ? `<div class="btns"><button class="approve" data-esc="${esc(e.esc_id)}" data-d="approve">Approve</button>
        ${e.draft ? `<button class="edit" data-esc="${esc(e.esc_id)}" data-d="edit">Edit</button>` : ""}
        <button class="deny" data-esc="${esc(e.esc_id)}" data-d="deny">Deny</button></div>` : ""}</div>`;
  }).join("");
  const showHtml = shows.map((e) => `<div class="todo"><span class="chip accent">confirm</span><span><b>Showing with ${esc(names[e.renter_id] || e.renter_id)}</b> ${esc(fmtDate(e.start))}, proposed to the renter as pending your confirmation</span></div>`).join("");
  $("escalations").innerHTML = escHtml + showHtml || `<div class="empty">Nothing needs you. Money, exceptions and anything the records don't answer come here with a drafted reply.</div>`;
}

function renderOps(v, threads) {
  const jobs = v.jobs || [];
  const tenants = Object.values(threads).filter((t) => t.kind === "tenant");
  $("opsCard").classList.toggle("hidden", !jobs.length && !tenants.length);
  const sp = v.spend || {}, lim = sp.limit;
  const p = lim ? Math.min(100, (100 * (sp.spent || 0)) / lim) : 0;
  $("spend").innerHTML = lim != null ? `<span>Spent <b>$${(sp.spent || 0).toFixed(0)}</b> of your $${esc(lim)} limit</span><div class="spendbar ${sp.spent > lim ? "over" : ""}"><div style="width:${p}%"></div></div>` : "";
  $("kpiSpend").textContent = lim != null && jobs.length ? `$${(sp.spent || 0).toFixed(0)} / $${lim}` : "–";
  const vn = v.vendors || {};
  const used = new Set();
  let html = jobs.map((j) => {
    const qs = (v.quotes || []).filter((q) => q.job_id === j.job_id);
    const t = tenants.find((x) => x.room_id && x.room_id === j.room_id) || tenants[0];
    if (t) used.add(t.thread_id);
    return `<div class="job"><div class="h"><b>${esc(j.issue || "Job")}</b><span class="chip ${j.status === "booked" ? "ok" : ""}">${esc(j.status)}</span></div>
      <div class="meta muted small">${esc(j.property || "")}${j.vendor_id ? ` · booked ${esc(vn[j.vendor_id] || j.vendor_id)} for $${esc(j.cost)}` : ""}</div>
      ${qs.length ? `<div class="quotes">${qs.map((q) => `<span class="quote ${q.status === "accepted" || q.vendor_id === j.vendor_id ? "win" : ""}">${esc(vn[q.vendor_id] || q.vendor_id)} $${esc(q.amount)}</span>`).join("")}</div>` : ""}
      ${t ? `<div class="convo">${convoHtml(t.messages)}</div>` : ""}</div>`;
  }).join("");
  html += tenants.filter((t) => !used.has(t.thread_id)).map((t) => `<div class="job"><div class="h"><b>${esc(t.renter_name)}</b><span class="chip">${esc(LANE_NAMES[t.channel] || t.channel)}</span></div>
    <div class="convo">${convoHtml(t.messages)}</div></div>`).join("");
  $("jobs").innerHTML = html;
}

function renderView(v) {
  S.lastView = v;
  renderChannels(v);
  const threads = renderPipeline(v);
  renderRegister(v);
  renderClusters(v);
  renderEscalations(v, threads);
  renderOps(v, threads);
}

async function decide(escId, decision, text) {
  try { await api(`/api/runs/${S.runId}/escalations/${escId}`, { method: "POST", body: { decision, text: text || null, source: "console" } }); }
  catch (err) { sysChat("Decision failed: " + err.message); }
  S.editing[escId] = false;
  scheduleView(200);
}

// ================================================================ wiring
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("rentus-theme", t); } catch (e) { /* storage blocked */ }
}
$("themeBtn").onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  setTheme(cur === "dark" ? "light" : "dark");
};
$("chatForm").onsubmit = (e) => { e.preventDefault(); sendChat($("chatInput").value); };
$("chatInput").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat($("chatInput").value); } };
document.querySelectorAll(".hint").forEach((b) => (b.onclick = () => sendChat(b.dataset.text)));
$("runScenario").onclick = async () => {
  const sid = $("scenario").value;
  $("gymMenu").classList.add("hidden");
  if (!sid) return sysChat("Pick a scenario first (gym/tasks/*.jsonl).");
  try { await startRun("", sid); } catch (e) { sysChat("Scenario failed: " + e.message); }
};
$("demoBtn").onclick = startDemo;
$("resetBtn").onclick = async () => { try { await api("/api/reset", { method: "POST" }); } catch (e) { /* */ } detach(); resetUI(); refreshStatus(); };
$("speed").onchange = async () => {
  if (S.runId) try { await api(`/api/runs/${S.runId}/speed`, { method: "POST", body: { speed: parseFloat($("speed").value) } }); } catch (e) { /* finished run */ }
};
$("breakBtn").onclick = () => { $("breakMenu").classList.toggle("hidden"); $("gymMenu").classList.add("hidden"); };
$("gymBtn").onclick = () => { $("gymMenu").classList.toggle("hidden"); $("breakMenu").classList.add("hidden"); };
document.addEventListener("click", (e) => { if (!e.target.closest(".menuwrap")) { $("breakMenu").classList.add("hidden"); $("gymMenu").classList.add("hidden"); } });
$("escalations").onclick = async (e) => {
  const b = e.target.closest("button[data-esc]");
  if (!b) return;
  const id = b.dataset.esc, card = b.closest(".esc");
  if (b.dataset.d === "edit") {
    const cur = (S.lastView.escalations || []).find((x) => x.esc_id === id) || {};
    S.editing[id] = true;
    card.querySelector(".d")?.remove();
    card.querySelector(".btns").insertAdjacentHTML("beforebegin", `<textarea rows="3">${esc(cur.draft || "")}</textarea>`);
    card.querySelector(".btns").innerHTML = `<button class="approve" data-esc="${esc(id)}" data-d="send">Send my reply</button><button data-esc="${esc(id)}" data-d="cancel">Cancel</button>`;
    card.querySelector("textarea").focus();
    return;
  }
  if (b.dataset.d === "cancel") { S.editing[id] = false; scheduleView(0); return; }
  b.disabled = true;
  if (b.dataset.d === "send") return decide(id, "approve", card.querySelector("textarea").value);
  decide(id, b.dataset.d);
};
$("followTrace").onchange = followTrace;
$("recoveryOnly").onchange = (e) => $("trace").classList.toggle("recovery-only", e.target.checked);
$("dockBtn").onclick = () => $("dock").classList.toggle("collapsed");
function setExpanded(on) { document.querySelector(".evidence").classList.toggle("expanded", on); $("scrim").classList.toggle("hidden", !on); $("expandBtn").textContent = on ? "✕" : "⤢"; }
$("expandBtn").onclick = () => setExpanded(!document.querySelector(".evidence").classList.contains("expanded"));
$("scrim").onclick = () => setExpanded(false);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") setExpanded(false); });
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
  $("dock").classList.remove("collapsed");
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabbody").forEach((x) => x.classList.toggle("hidden", x.id !== "tab-" + t.dataset.tab));
}));
$("stages").onclick = (e) => { const c = e.target.closest(".rc"); if (c) c.classList.toggle("expanded"); };

resetUI();
refreshStatus(); loadScenarios(); loadTrust(); loadResults(); loadPerf(); loadReal();
setInterval(refreshStatus, 1500);
setInterval(() => scheduleView(0), 2000);
setInterval(loadReal, 30000);
setInterval(loadScenarios, 60000);
