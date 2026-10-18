// Rentus Operator console. Vanilla JS, no build step.
"use strict";

const CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"];
const LANE_NAMES = { marketplace: "Marketplace", roomies: "Roomies", craigslist: "Craigslist", padsplit: "PadSplit", sms: "SMS", email: "Email" };
const GATE = ["lease", "move_in", "phone", "reason", "occupants"];
const TICK = { ok: "✓", vague: "~", no: "✗", none: "·" };
const FAULT_LABEL = {
  page_changed: "Page changed", malformed: "Malformed result", rate_limited: "Rate limited",
  login_required: "Login wall", timeout: "Timeout", upstream_error: "Upstream 502", not_found: "Not found",
};

const S = { runId: null, es: null, seen: new Set(), status: null, badge: null, readerLabel: "reader",
  viewTimer: null, lastView: null, seenMsgs: new Set(), demoStep: null, editing: {}, qrUrl: null };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "?" : (100 * x).toFixed(d) + "%");
const humanize = (s) => { s = String(s ?? ""); return /^[a-z]+(_[a-z]+)+$/.test(s) ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : s; };
const fix = (x, d = 3) => (x == null ? "?" : Number(x).toFixed(d));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText);
  return j;
}

// ---------------- status / badge ----------------
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    S.status = s; S.badge = s.badge; S.readerLabel = s.reader_label;
    const b = $("badge");
    b.textContent = s.badge.live ? "● live · Nemotron 3.5 Lightning 30B · vLLM" : s.badge.label;
    b.className = "badge " + (s.badge.live ? "live" : "stub");
    b.title = s.badge.live ? "models: " + (s.badge.models || []).join(", ")
      : (s.badge.operator_import_error || "OPERATOR_BASE_URL not reachable");
    if (s.reader) {
      const r = $("readerBadge");
      r.textContent = s.reader.live ? "● reader · rentus-reader 0.6B · vLLM" : s.reader.label;
      r.className = "badge " + (s.reader.live ? "live" : "stub");
      r.title = s.reader.live ? "models: " + (s.reader.models || []).join(", ") : "READER_BASE_URL not reachable";
    }
    $("cfgChip").textContent = s.mode === "stub" ? "" : "held-out best config";
    $("cfgChip").title = "operator config " + (s.operator_config || "") + ": the one that scored best on the 31 held-out Gym tasks (docs/results.md)";
    if (!S.faultsBuilt) buildFaultMenu(s.fault_kinds, s.default_fault_tool, s.fault_help || {});
    if (s.active_run && s.active_run !== S.runId) { resetUI(); attach(s.active_run); }
    if (!s.active_run && S.runId) { detach(); resetUI(); }
    $("runinfo").textContent = S.runId ? `${S.runId} · ${s.run_status || ""}` : "no run yet";
    renderDemo(s.demo && s.demo.run_id === S.runId ? s.demo : null, s.approve_url);
  } catch (e) { $("badge").textContent = "console offline"; }
}

function buildFaultMenu(kinds, defaults, help) {
  S.faultsBuilt = true;
  const box = $("faultList");
  box.innerHTML = "";
  const order = ["page_changed", "malformed", "rate_limited", "login_required", "timeout", "upstream_error", "not_found"];
  for (const k of order.filter((k) => kinds.includes(k))) {
    const b = document.createElement("button");
    b.innerHTML = `${esc(FAULT_LABEL[k])} <span class="muted small">→ next ${esc(defaults[k])}</span><span class="fh">${esc(help[k] || "")}</span>`;
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

// ---------------- demo ----------------
function renderDemo(d, approveUrl) {
  const bar = $("demoBar");
  $("demoBtn").disabled = !!(d && !d.finished);
  $("demoBtn").textContent = d && !d.finished ? "Demo running…" : "▶ Demo run";
  if (!d) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const ids = d.steps.map((s) => s.id);
  const cur = ids.indexOf(d.step);
  $("demoSteps").innerHTML = d.steps.filter((s) => s.id !== "done").map((s, i) =>
    `<span class="step ${i < cur || d.step === "done" ? "done" : i === cur ? "now" : ""}">${i + 1} ${esc(s.title)}</span>`).join("");
  const st = d.steps[cur] || { title: "Starting", say: "" };
  $("demoTitle").textContent = d.error ? "Demo stopped" : st.title;
  $("demoSay").textContent = d.error ? d.error : st.say;
  const sec = Math.round(d.elapsed || 0);
  $("demoClock").textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  const url = d.approve_url || approveUrl;
  $("phoneUrl").textContent = url.replace(/^https?:\/\//, "");
  $("phoneBox").classList.toggle("hot", d.step === "approve");
  if (url !== S.qrUrl && window.QRCode) {
    $("qr").innerHTML = "";
    try { new QRCode($("qr"), { text: url, width: 128, height: 128 }); S.qrUrl = url; } catch (e) { /* offline: URL text is enough */ }
  }
}

async function startDemo() {
  try {
    $("demoBtn").disabled = true;
    const r = await api("/api/demo", { method: "POST", body: { speed: parseFloat($("speed").value) } });
    resetUI(); attach(r.run_id); refreshStatus();
  } catch (e) { sysChat("Demo failed: " + e.message); $("demoBtn").disabled = false; }
}

// ---------------- evidence tabs ----------------
async function loadScoreboard() {
  const box = $("tab-score");
  try {
    const rows = await api("/api/scoreboard");
    if (!rows.length) { box.innerHTML = '<div class="empty">No Gym results yet (gym/results/*/summary.json).</div>'; return; }
    box.innerHTML = `<div class="note">31 held-out NeMo Gym tasks the changes were never tuned on. Same Lightning weights in every row; each step changes only the harness, prompt or verifier. Bar = mean reward.</div>
      <div class="ladder">` + rows.map((r) => {
      const runner = r.runner === "nemo" ? "NeMo Gym simple_agent" : "our loop";
      return `<div class="sb k-${esc(r.kind)}"><div class="top"><span><span class="lbl">${esc(r.label)}</span>
        <span class="muted small"> ${runner} · ${r.runs} run${r.runs > 1 ? "s" : ""}</span></span>
        <span><span class="pct">${fix(r.passed, r.passed % 1 ? 1 : 0)}/${r.tasks}</span> <span class="muted small">pass</span>
        <b>${fix(r.mean_reward)}</b>${r.delta_reward != null ? `<span class="delta"> ${r.delta_reward >= 0 ? "+" : ""}${fix(r.delta_reward, 2)}</span>` : ""}</span></div>
        <div class="bar"><div style="width:${(100 * r.mean_reward).toFixed(1)}%"></div></div></div>`;
    }).join("") + `</div><div class="note">Source: gym/results/*/summary.json, written by gym/ablate.py. Details: docs/results.md.</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">scoreboard error: ${esc(e.message)}</div>`; }
}

async function loadTrust() {
  const box = $("tab-trust");
  try {
    const t = await api("/api/trust");
    const H = t.heldout, o = H.ours, ref = H.reference, base = H.baseline, R = t.reader;
    const used = t.budget.used_b, lim = t.budget.limit_b;
    const opB = t.roles[0].params_b, rdB = t.roles[1].params_b || 0;
    const secs = (x) => (x == null ? "?" : Math.round(x) + " s");
    box.innerHTML = `
      <div class="h3 first">Operator on 31 held-out tasks (never used for tuning)</div>
      <table class="cmp"><tr><th></th><th>pass</th><th>reward</th><th>cost / task</th><th>time / task p50</th></tr>
        ${base ? `<tr><td>Lightning 30B, baseline harness</td><td>${fix(base.passed, base.passed % 1 ? 1 : 0)}/${base.tasks}</td><td>${fix(base.mean_reward)}</td><td>$0</td><td></td></tr>` : ""}
        ${o ? `<tr class="ours"><td>Lightning 30B + our harness</td><td>${fix(o.passed, o.passed % 1 ? 1 : 0)}/${o.tasks}</td><td>${fix(o.mean_reward)}</td><td>$0 (own GPU)</td><td>${secs(o.task_seconds_p50)}</td></tr>` : ""}
        ${ref ? `<tr><td>Claude Opus 5.5, same harness</td><td>${ref.passed}/${ref.tasks}</td><td>${fix(ref.mean_reward)}</td><td>$${fix(ref.cost_per_task_usd, 2)}</td><td>${secs(ref.task_seconds_p50)}</td></tr>` : ""}
      </table>
      <div class="note">Parity with a frontier model, not a win: the gap is inside run-to-run noise (about ±0.02 reward); Opus had one run and no tuning. Renter messages never leave our machine.</div>
      <div class="h3">Reader on the same ${R.sample_n || "?"} held-out messages (exact match = every field right)</div>
      <table class="cmp"><tr><th></th><th>exact match</th><th>latency p50</th><th>cost / read</th></tr>
        <tr class="ours"><td>rentus-reader 0.6B, fine-tuned</td><td>${pct(R.sample.finetuned, 1)}</td><td>${fix(R.latency_p50_s, 2)} s</td><td>$0</td></tr>
        <tr><td>Claude Opus 5.5, prompted</td><td>${pct(R.opus_exact_match, 1)}</td><td>${fix(R.opus_latency_p50_s, 1)} s</td><td>$${fix(R.opus_cost_per_read_usd, 3)}</td></tr>
        <tr><td>Lightning 30B, prompted</td><td>${pct(R.sample.lightning, 1)}</td><td></td><td></td></tr>
        <tr><td>Rule-based fallback</td><td>${pct(R.sample.fallback, 1)}</td><td></td><td></td></tr>
      </table>
      <div class="h3">Who does what · ${used}B of the ${lim}B limit</div>
      <div class="budget"><div class="bar"><div class="op" style="width:${(100 * opB / lim).toFixed(1)}%"></div><div class="rd" style="width:${Math.max(1, 100 * rdB / lim).toFixed(1)}%"></div></div></div>
      <table class="cmp roles-t">${t.roles.map((r) => `<tr><td><b>${esc(r.who)}</b></td><td>${r.link ? `<a href="${esc(r.link)}" target="_blank">${esc(r.model)} ↗</a>` : esc(r.model)}</td>
        <td class="num">${r.params_b ? r.params_b + "B" : "0"}</td><td class="muted">${esc(r.does)}</td></tr>`).join("")}</table>
      <div class="note">Reader: ${R.train_rows?.toLocaleString() || "?"} open + synthetic EN/ES messages, ${R.train_minutes || "?"} min on one GPU; full test set (${R.test_rows} rows) ${pct(R.exact_match_full, 1)}. Published at <a href="${esc(R.hf)}" target="_blank">${esc(R.hf.replace("https://", ""))}</a>. Numbers read live from ${t.sources.map(esc).join(", ")}.</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">trust panel error: ${esc(e.message)}</div>`; }
}

async function loadReal() {
  const box = $("tab-real");
  try {
    const r = await api("/api/realworld");
    const p = r.post;
    const st = r.stats || {};
    const lines = p && p.text ? p.text.split(" / ") : [];
    const ctr = (k, label) => `<div class="ctr"><b>${st[k] ?? "?"}</b><span>${label}</span></div>`;
    box.innerHTML = p ? `
      <div class="rw-post">${r.thumb ? `<a href="${esc(p.permalink)}" target="_blank"><img src="/api/file?path=${encodeURIComponent(r.thumb)}" alt="Appling Way room photo"></a>` : ""}
        <div><div class="pt">${esc(lines[0] || "Live listing")}</div><div class="pb">${esc(lines.slice(1).join(" "))}</div>
        <div class="small muted">Written by the operator (Lightning), compliance-checked, posted unedited on the Rentus Homes Facebook Page ${esc(p.posted || "")}${p.photos ? ` with ${p.photos} photos` : ""}.</div>
        <a href="${esc(p.permalink)}" target="_blank">Open the live post ↗</a></div></div>
      <div class="h3">Pilot inbox, shadow mode (counts only)</div>
      <div class="counters">${ctr("inquiries", "inquiries")}${ctr("conversations", "conversations")}${ctr("drafts", "drafts written")}
        ${ctr("gate_items_captured", "gate items captured")}${ctr("escalations", "escalations")}${ctr("errors", "errors")}</div>
      <div class="note">The operator reads real replies to this post and drafts answers; it never sends. The owner replies himself. Renter text stays off the repo. Updated ${esc(st.updated_at || "?")}.</div>`
      : `<div class="empty">No pilot post recorded (docs/DECISIONS.md D20).</div>`;
  } catch (e) { box.innerHTML = `<div class="empty">real-world panel error: ${esc(e.message)}</div>`; }
}

// ---------------- scenarios ----------------
async function loadScenarios() {
  try {
    const list = await api("/api/scenarios");
    const sel = $("scenario");
    const cur = sel.value;
    sel.innerHTML = '<option value="">(pick a Gym task)</option>' + list.map((s) =>
      `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join("");
    sel.value = cur;
  } catch (e) { /* gym not built yet */ }
}

// ---------------- runs ----------------
async function startRun(goal, scenarioId) {
  const body = { goal: goal || "", speed: parseFloat($("speed").value) };
  if (scenarioId) body.scenario_id = scenarioId;
  const r = await api("/api/runs", { method: "POST", body });
  resetUI();
  attach(r.run_id);
  refreshStatus();
}

function resetUI() {
  S.seen = new Set(); S.seenMsgs = new Set(); S.editing = {};
  $("trace").innerHTML = ""; $("chatLog").innerHTML = "";
  document.querySelectorAll(".lane").forEach((l) => l.remove());
  renderView({ lanes: {}, register: [], escalations: [], jobs: [], quotes: [], spend: {}, calendar: [] });
}

function detach() {
  if (S.es) S.es.close();
  S.es = null; S.runId = null;
}

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
  if (ev.type === "owner_message" && ev.actor !== "owner" && d.summary) chatBubble("op", opLabel(d) + " · report", d.summary);
  else if (ev.type === "owner_message" && d.text && d.text.startsWith("Owner decision on escalation")) sysChat(d.text);
  else if (ev.type === "owner_message" && d.text) chatBubble("owner", "Owner", d.text);
  else if (ev.type === "model_message" && S.status?.mode === "stub" && d.text && !(d.tool_calls || []).length) chatBubble("op", opLabel(d), d.text);
  else if (ev.type === "turn_done" && d.final_text) chatBubble("op", `${opLabel(d)}${d.who ? " · about " + d.who : ""} · ${d.tool_calls} tool calls, ${d.seconds}s`, d.final_text.replace(/\*\*/g, ""));
  else if (ev.type === "escalation") sysChat("Needs you: " + (d.reason || ""));
  else if (ev.type === "demo_step") sysChat(`Step: ${d.title}`);
  else if (ev.type === "owner_decision") sysChat(`Owner ${d.decision === "approve" ? "approved" : "denied"} ${d.esc_id}${d.via ? " from the " + d.via : ""}${d.edited ? " with an edit" : ""}.`);
  if (["tool_result", "renter_message", "escalation", "owner_message", "model_message", "owner_decision"].includes(ev.type)) scheduleView(150);
}

function scheduleView(ms) {
  clearTimeout(S.viewTimer);
  S.viewTimer = setTimeout(refreshView, ms);
}

async function refreshView() {
  if (!S.runId) return;
  try { renderView(await api(`/api/runs/${S.runId}/view`)); } catch (e) { /* run gone */ }
}

// ---------------- chat ----------------
function chatBubble(cls, who, text) {
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.innerHTML = `<div class="who">${esc(who)}</div>${esc(text)}`;
  $("chatLog").appendChild(div);
  $("chatLog").scrollTop = 1e9;
}
function sysChat(text) {
  const div = document.createElement("div");
  div.className = "bubble sys";
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

// ---------------- labels ----------------
function opLabel(d) {
  const m = (d && d.model) || "";
  if (m === "stub" || (!S.badge?.live && !m)) return "operator · stub";
  return "operator · Lightning 30B";
}
function actorLabel(ev) {
  const a = ev.actor || "system", d = ev.data || {};
  if ((ev.type === "tool_call" || ev.type === "tool_result") && (d.tool === "read_reply")) {
    const be = d.result?.data?.backend;
    if (ev.type === "tool_result" && be === "fallback") return ["reader · rules fallback", "reader"];
    return [`reader · ${S.readerLabel}`, "reader"];
  }
  if (ev.type === "tool_result" && a === "system") return ["tools · sandbox", "system"];
  if (a === "operator") return [opLabel(d), "operator"];
  if (a === "verifier") return ["verifier · code", "verifier"];
  if (a === "harness") return ["harness · code", "verifier"];
  if (a.startsWith("renter:")) return [a.replace("renter:", "renter · ") + " (script)", "renter"];
  if (a.startsWith("tenant:")) return [a.replace("tenant:", "tenant · ") + " (script)", "renter"];
  if (a.startsWith("vendor:")) return [a.replace("vendor:", "vendor · ") + " (script)", "vendor"];
  if (a === "owner") return ["owner", "owner"];
  if (ev._src === "console") return ["console", "system"];
  return [a, "system"];
}

function short(v, n = 70) {
  let s = typeof v === "string" ? v : JSON.stringify(v);
  if (s === undefined) s = "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function summarize(ev) {
  const d = ev.data || {};
  switch (ev.type) {
    case "tool_call": return ["tool", `→ ${d.tool || d.name}(${short(d.args ?? d.arguments ?? "", 110)})`];
    case "tool_result": {
      const ok = d.ok ?? d.result?.ok;
      const err = d.error || d.result?.error;
      const f = d.fault ? ` [injected ${typeof d.fault === "string" ? d.fault : d.fault.kind || "fault"}]` : "";
      if (ok === false) return ["err", `✗ ${d.tool || ""} ${err?.code || ""}: ${err?.message || ""}${f}`];
      return [f ? "err" : "ok", `✓ ${d.tool || ""}${f} ${short(d.data ?? d.result?.data ?? "", 110)}`];
    }
    case "verifier": {
      if (d.stage === "policy") {
        const cls = d.action === "retry" ? "retry" : d.action === "fallback" ? "fb" : "vfail";
        return [cls, `policy: ${d.tool || ""} ${d.code || ""} → ${d.action || ""}${d.note ? " (" + d.note + ")" : ""}`];
      }
      const what = d.check || d.stage || "";
      const extra = d.detail || [].concat(d.problems || [], d.repaired || [], d.errors || []).join("; ");
      return [d.ok === false ? "vfail" : "vok", `${d.ok === false ? "✗ caught" : "✓ pass"} ${what}${d.tool ? " on " + d.tool : ""}${extra ? ": " + extra : ""}`];
    }
    case "retry": return ["retry", `↻ retry ${d.tool || ""} attempt ${d.attempt ?? "?"} after ${d.code || d.reason || d.error || ""}${d.delay_s ? ` (wait ${d.delay_s}s)` : ""}`];
    case "fallback": return ["fb", `⤳ fallback ${d.tool ? d.tool + ": " : ""}${d.code ? d.code + " · " : ""}${d.from ? d.from + " → " : ""}${d.to || d.note || ""} ${d.suggestion ? "→ " + d.suggestion : ""}${d.reason ? " (" + d.reason + ")" : ""}`];
    case "escalation": return ["esc", `⚑ escalate: ${d.reason || ""}`];
    case "fault_injected": return ["fault", `💥 broke: ${d.kind} on next ${d.tool}${d.match ? " " + JSON.stringify(d.match) : ""}`];
    case "scenario": return ["msg", `scenario ${d.scenario_id} loaded: ${d.counterparts} counterparts, ${(d.faults || []).length} scripted faults`];
    case "demo_step": return ["esc", `▶ demo step: ${d.title}`];
    case "approve_wait": return ["esc", d.open ? `waiting for the owner: ${d.open} decision(s) at ${d.url}` : `owner approval: ${d.detail || "nothing open"}`];
    case "demo_nudge": return ["msg", `nothing was waiting for the owner, so Devon writes again: “${d.text}”`];
    case "approve_done": return ["msg", `owner decided after ${d.waited_s}s`];
    case "turn_done": return ["ok", `turn done (${d.kind}${d.who ? " " + d.who : ""}): ${d.status}, ${d.tool_calls} tool calls in ${d.seconds}s`];
    case "owner_decision": return ["esc", `owner ${d.decision}d ${d.esc_id} via ${d.via || "console"}${d.edited ? " (edited)" : ""}`];
    case "renter_message": return ["msg", `${d.name || ""} [${d.channel || ""}]: “${d.text || ""}”`];
    case "owner_message": return ["msg", d.summary ? `report to owner: ${d.summary}` : `owner: ${d.text || ""}`];
    case "model_message": {
      const calls = d.tool_calls || [];
      if (calls.length) return ["msg", `decides: ${calls.join(", ")}${d.text ? " · " + d.text : ""}`];
      return ["msg", `${d.thread_id ? "to " + d.thread_id : "says"}: ${d.text || ""}`];
    }
    case "score": return ["ok", `score ${short(d, 120)}`];
    default: return ["msg", `${ev.type}: ${short(d, 120)}`];
  }
}

function addTrace(ev) {
  const [cls, text] = summarize(ev);
  const [label, acls] = actorLabel(ev);
  const row = document.createElement("div");
  row.className = "row " + cls;
  const ts = (ev.ts || "").slice(11, 19);
  row.innerHTML = `<span class="ts">${esc(ts)}</span><span class="actor a-${acls}">${esc(label)}</span><span class="s" title="${esc(text)}">${esc(text)}</span>`;
  const box = $("trace");
  row.dataset.ts = ev.ts || "";
  let before = null;  // console notes come from a second file; keep the trace in time order on replay
  if (ev.ts && box.lastElementChild && box.lastElementChild.dataset.ts > ev.ts) {
    for (const el of box.children) { if (el.dataset.ts > ev.ts) { before = el; break; } }
  }
  box.insertBefore(row, before);
  while (box.childElementCount > 800) box.removeChild(box.firstChild);
  if ($("followTrace").checked) box.parentElement.scrollTop = 1e9;
}

// ---------------- view ----------------
function imgSrc(shot) {
  if (!shot) return null;
  if (shot.startsWith("data:") || shot.startsWith("http")) return shot;
  return "/api/file?path=" + encodeURIComponent(shot);
}

function renderLanes(lanes) {
  const box = $("lanes");
  const names = [...CHANNELS, ...Object.keys(lanes).filter((c) => !CHANNELS.includes(c))];
  for (const ch of names) {
    let lane = document.getElementById("lane-" + ch);
    if (!lane) {
      lane = document.createElement("div");
      lane.className = "lane"; lane.id = "lane-" + ch;
      lane.innerHTML = `<div class="lane-h"><span>${esc(LANE_NAMES[ch] || ch)}</span><span class="n"></span></div><div class="lane-posts"></div><div class="lane-b"></div>`;
      box.appendChild(lane);
    }
    const L = lanes[ch] || { posts: [], threads: [] };
    lane.querySelector(".n").textContent = `${L.posts.length} post${L.posts.length === 1 ? "" : "s"} · ${L.threads.length} thread${L.threads.length === 1 ? "" : "s"}`;
    const body = lane.querySelector(".lane-b");
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    let html = "", posts = "";
    for (const p of L.posts) {
      const src = imgSrc(p.screenshot);
      const st = p.status || "draft";
      posts += `<div class="card">${src ? `<a href="${esc(src)}" target="_blank"><img src="${esc(src)}" alt="screenshot"></a>` : ""}
        <div><div class="t">${esc(p.title)}</div><div class="small muted">$${esc(p.price)} <span class="chip ${st === "live" ? "live" : st.includes("ready") ? "ready" : ""}">${esc(st)}</span></div></div></div>`;
    }
    for (const t of L.threads) {
      html += `<div class="thread"><div class="name">${esc(t.renter_name)}${t.language ? `<span class="chip">${esc(t.language)}</span>` : ""}</div>`;
      t.messages.forEach((m, i) => {
        const key = `${t.thread_id}:${i}`;
        const fresh = !S.seenMsgs.has(key); S.seenMsgs.add(key);
        html += `<div class="msg ${m.from === "operator" ? "operator" : "renter"}${fresh ? " new" : ""}">${esc(m.text)}</div>`;
      });
      html += "</div>";
    }
    const pbox = lane.querySelector(".lane-posts");
    if (pbox.innerHTML !== posts) pbox.innerHTML = posts;
    body.innerHTML = html || `<div class="empty">${L.posts.length ? "no threads yet" : "nothing yet"}</div>`;
    if (nearBottom) body.scrollTop = 1e9;
  }
}

function renderRegister(reg, calendar) {
  $("register").querySelector("tbody").innerHTML = reg.length ? reg.map((r) => `<tr>
    <td><b>${esc(r.name)}</b>${r.channel ? `<span class="v">${esc(r.channel)}</span>` : ""}</td>
    ${GATE.map((g) => { const c = r.gate[g] || { state: "none" };
      return `<td title="${esc(c.value ?? "")}"><span class="tick ${c.state}">${TICK[c.state] || "·"}</span>${c.value != null && c.value !== "" ? `<span class="v">${esc(c.value)}</span>` : ""}</td>`; }).join("")}
    <td class="status">${esc((r.status || "").replace(/_/g, " "))}</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">no renters yet</td></tr>`;
  const names = Object.fromEntries(reg.map((r) => [r.renter_id, r.name]));
  $("showings").innerHTML = (calendar || []).filter((e) => e.status === "proposed" || e.status === "confirmed").map((e) =>
    `<div class="show">Showing ${esc(e.status)}: ${esc(names[e.renter_id] || e.renter_id)} · ${esc((e.start || "").replace("T", " ").slice(0, 16))}${e.status === "proposed" ? " (pending your confirmation)" : ""}</div>`).join("");
}

function renderEscalations(list) {
  const open = list.filter((e) => !e.status || e.status === "open");
  $("escCount").textContent = open.length || "";
  if (Object.values(S.editing).some(Boolean)) return;  // don't wipe a draft the owner is editing
  $("escalations").innerHTML = list.length ? list.slice().reverse().map((e) => {
    const isOpen = !e.status || e.status === "open";
    return `<div class="esc ${isOpen ? "" : "done"}" data-esc="${esc(e.esc_id)}"><div class="r">${esc(humanize(e.reason))}</div>
      ${e.draft ? `<div class="d">Draft: “${esc(e.owner_text || e.draft)}”</div>` : ""}
      ${isOpen ? `<div class="btns"><button class="approve" data-esc="${esc(e.esc_id)}" data-d="approve">Approve</button>
        ${e.draft ? `<button class="edit" data-esc="${esc(e.esc_id)}" data-d="edit">Edit</button>` : ""}
        <button class="deny" data-esc="${esc(e.esc_id)}" data-d="deny">Deny</button></div>`
        : `<span class="chip">${esc(e.status)}</span>${e.decided_via ? `<span class="via">via ${esc(e.decided_via)}</span>` : ""}`}</div>`;
  }).join("") : `<div class="empty">nothing needs you</div>`;
}

function renderOps(v) {
  const sp = v.spend || {};
  const lim = sp.limit;
  const p = lim ? Math.min(100, (100 * (sp.spent || 0)) / lim) : 0;
  $("spend").innerHTML = lim != null && (v.jobs || []).length ? `<div class="small">Spend <b>$${(sp.spent || 0).toFixed(0)}</b> of $${esc(lim)} limit</div>
    <div class="spendbar ${sp.spent > lim ? "over" : ""}"><div style="width:${p}%"></div></div>` : "";
  const vn = v.vendors || {};
  const jobs = (v.jobs || []).map((j) => {
    const qs = (v.quotes || []).filter((q) => q.job_id === j.job_id)
      .map((q) => `${esc(vn[q.vendor_id] || q.vendor_id)} $${esc(q.amount)}${q.status === "accepted" ? " ✓" : ""}`).join(" · ");
    return `<div class="job"><b>${esc(j.property)}</b>: ${esc(short(j.issue, 60))} <span class="chip ${j.status === "booked" ? "live" : ""}">${esc(j.status)}</span>
      ${j.vendor_id ? `<div class="small">→ ${esc(vn[j.vendor_id] || j.vendor_id)} $${esc(j.cost)}</div>` : ""}
      ${qs ? `<div class="small muted">quotes: ${qs}</div>` : ""}</div>`;
  }).join("");
  $("jobs").innerHTML = jobs || `<div class="empty">no jobs</div>`;
}

function renderView(v) {
  S.lastView = v;
  renderLanes(v.lanes || {});
  renderRegister(v.register || [], v.calendar || []);
  renderEscalations(v.escalations || []);
  renderOps(v);
}

async function decide(escId, decision, text) {
  try {
    await api(`/api/runs/${S.runId}/escalations/${escId}`, { method: "POST", body: { decision, text: text || null, source: "console" } });
  } catch (err) { sysChat("Decision failed: " + err.message); }
  S.editing[escId] = false;
  scheduleView(200);
}

// ---------------- wiring ----------------
$("chatForm").onsubmit = (e) => { e.preventDefault(); sendChat($("chatInput").value); };
$("chatInput").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat($("chatInput").value); } };
document.querySelectorAll(".hint").forEach((b) => (b.onclick = () => sendChat(b.dataset.text)));
$("runScenario").onclick = async () => {
  const sid = $("scenario").value;
  if (!sid) return sysChat("Pick a scenario first (gym/tasks/*.jsonl).");
  try { await startRun("", sid); } catch (e) { sysChat("Scenario failed: " + e.message); }
};
$("demoBtn").onclick = startDemo;
$("resetBtn").onclick = async () => { try { await api("/api/reset", { method: "POST" }); } catch (e) { /* */ } detach(); resetUI(); refreshStatus(); };
$("speed").onchange = async () => {
  if (S.runId) try { await api(`/api/runs/${S.runId}/speed`, { method: "POST", body: { speed: parseFloat($("speed").value) } }); } catch (e) { /* finished run */ }
};
$("breakBtn").onclick = () => $("breakMenu").classList.toggle("hidden");
document.addEventListener("click", (e) => { if (!e.target.closest(".break")) $("breakMenu").classList.add("hidden"); });
$("escalations").onclick = async (e) => {
  const b = e.target.closest("button[data-esc]");
  if (!b) return;
  const id = b.dataset.esc, card = b.closest(".esc");
  if (b.dataset.d === "edit") {
    const cur = (S.lastView.escalations || []).find((x) => x.esc_id === id) || {};
    S.editing[id] = true;
    card.querySelector(".d")?.remove();
    card.querySelector(".btns").insertAdjacentHTML("beforebegin", `<textarea rows="3">${esc(cur.draft || "")}</textarea>`);
    card.querySelector(".btns").innerHTML = `<button class="approve" data-esc="${esc(id)}" data-d="send">Approve edited</button><button class="ghost" data-esc="${esc(id)}" data-d="cancel">Cancel</button>`;
    return;
  }
  if (b.dataset.d === "cancel") { S.editing[id] = false; scheduleView(0); return; }
  b.disabled = true;
  if (b.dataset.d === "send") return decide(id, "approve", card.querySelector("textarea").value);
  decide(id, b.dataset.d);
};
$("expandBtn").onclick = () => document.querySelector(".evidence").classList.toggle("expanded");
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === t));
  document.querySelectorAll(".tabbody").forEach((x) => x.classList.toggle("hidden", x.id !== "tab-" + t.dataset.tab));
}));

renderView({ lanes: {}, register: [], escalations: [], jobs: [], quotes: [], spend: {}, calendar: [] });
refreshStatus(); loadScenarios(); loadScoreboard(); loadTrust(); loadReal();
setInterval(refreshStatus, 1500);
setInterval(() => scheduleView(0), 2000);
setInterval(loadReal, 30000);
setInterval(loadScenarios, 60000);
