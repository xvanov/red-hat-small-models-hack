// Rentus Operator console. Vanilla JS, no build step.
"use strict";

const CHANNELS = ["marketplace", "roomies", "craigslist", "padsplit", "sms", "email"];
const LANE_NAMES = { marketplace: "Marketplace", roomies: "Roomies", craigslist: "Craigslist", padsplit: "PadSplit", sms: "SMS", email: "Email" };
const GATE = ["lease", "move_in", "phone", "reason", "occupants"];
const TICK = { ok: "✓", vague: "~", no: "✗", none: "·" };
const FAULT_LABEL = {
  timeout: "Timeout", page_changed: "Page changed", rate_limited: "Rate limited",
  malformed: "Malformed result", login_required: "Login required",
  upstream_error: "Upstream 502", not_found: "Not found",
};

const S = { runId: null, es: null, seen: new Set(), status: null, badge: null, readerLabel: "reader",
  viewTimer: null, lastView: null, seenMsgs: new Set(), chat: [] };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
    b.textContent = s.badge.label;
    b.className = "badge " + (s.badge.live ? "live" : "stub");
    b.title = s.badge.live ? "models: " + (s.badge.models || []).join(", ")
      : (s.badge.operator_import_error || "OPERATOR_BASE_URL not reachable");
    if (!S.faultsBuilt) buildFaultMenu(s.fault_kinds, s.default_fault_tool);
    if (s.active_run && !S.runId) attach(s.active_run);
    $("runinfo").textContent = S.runId ? `${S.runId} · ${s.run_mode || ""} · ${s.run_status || ""}` : "no run yet";
  } catch (e) { $("badge").textContent = "console offline"; }
}

function buildFaultMenu(kinds, defaults) {
  S.faultsBuilt = true;
  const box = $("faultList");
  box.innerHTML = "";
  for (const k of kinds.filter((k) => FAULT_LABEL[k])) {
    const b = document.createElement("button");
    b.innerHTML = `${esc(FAULT_LABEL[k])} <span class="muted small">→ ${esc(defaults[k])}</span>`;
    b.onclick = () => injectFault(k);
    box.appendChild(b);
  }
}

async function injectFault(kind) {
  $("breakMenu").classList.add("hidden");
  if (!S.runId) return sysChat("Start a run first, then break it.");
  try {
    const r = await api(`/api/runs/${S.runId}/faults`, { method: "POST", body: { kind, tool: $("faultTool").value || null } });
    sysChat(`Injected ${FAULT_LABEL[kind]} on the next ${r.fault.tool} call.`);
  } catch (e) { sysChat("Fault failed: " + e.message); }
}

// ---------------- scenarios / scoreboard ----------------
async function loadScenarios() {
  try {
    const list = await api("/api/scenarios");
    const sel = $("scenario");
    const cur = sel.value;
    sel.innerHTML = '<option value="">(free play)</option>' + list.map((s) =>
      `<option value="${esc(s.id)}">${esc(s.id)} · ${esc(s.category || "")} · ${esc(s.split || "")}</option>`).join("");
    sel.value = cur;
  } catch (e) { /* gym not built yet */ }
}

async function loadScoreboard() {
  const box = $("scoreboard");
  try {
    const rows = await api("/api/scoreboard");
    if (!rows.length) { box.innerHTML = '<div class="empty">No results yet. Gym runs write results/&lt;name&gt;/summary.json.</div>'; return; }
    const base = rows.find((r) => r.kind === "baseline" && r.pass_rate != null);
    box.innerHTML = rows.map((r) => {
      if (r.error) return `<div class="sb"><b>${esc(r.name)}</b> <span class="muted">unreadable: ${esc(r.error)}</span></div>`;
      const pct = r.pass_rate == null ? null : (r.pass_rate > 1 ? r.pass_rate : r.pass_rate * 100);
      const delta = base && r !== base && pct != null ? pct - (base.pass_rate > 1 ? base.pass_rate : base.pass_rate * 100) : null;
      const checks = Object.entries(r.checks || {}).map(([k, v]) => `${esc(k)} ${Math.round(v > 1 ? v : v * 100)}%`).join(" · ");
      return `<div class="sb ${r.kind}"><div class="top"><span><span class="lbl">${esc(r.label)}</span><span class="kind">${esc(r.kind)}</span>
        <span class="muted small">${esc(r.split || "")} ${r.n_tasks ? "· " + r.n_tasks + " tasks" : ""} ${r.model ? "· " + esc(r.model) : ""}</span></span>
        <span><span class="pct">${pct == null ? "?" : pct.toFixed(1) + "%"}</span>
        ${delta != null ? `<span class="delta"> ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}</span>` : ""}</span></div>
        <div class="bar"><div style="width:${pct || 0}%"></div></div><div class="checks">${checks}</div></div>`;
    }).join("");
  } catch (e) { box.innerHTML = `<div class="empty">scoreboard error: ${esc(e.message)}</div>`; }
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
  S.seen = new Set(); S.seenMsgs = new Set(); S.chat = [];
  $("trace").innerHTML = ""; $("chatLog").innerHTML = "";
  renderView({ lanes: {}, register: [], escalations: [], jobs: [], quotes: [], spend: {} });
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
  if (ev.type === "owner_message" && !d.esc_id) chatBubble("owner", "Owner", d.text);
  else if (ev.type === "owner_message" && d.esc_id) sysChat(d.text);
  else if (ev.type === "model_message" && (d.to === "owner" || !d.thread_id)) chatBubble("op", opLabel(d), d.text);
  else if (ev.type === "fault_injected") { /* already confirmed in chat */ }
  else if (ev.type === "escalation") sysChat("Needs you: " + (d.reason || ""));
  if (["tool_result", "renter_message", "escalation", "owner_message", "model_message"].includes(ev.type)) scheduleView(150);
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
  return "operator · Nemotron 3.5 Lightning";
}
function actorLabel(ev) {
  const a = ev.actor || "system", d = ev.data || {};
  if (a === "operator") return [opLabel(d), "operator"];
  if (a === "reader") return [`reader · ${d.model || S.readerLabel}`, "reader"];
  if (a === "verifier") return ["verifier · code", "verifier"];
  if (a.startsWith("renter:")) return [a.replace("renter:", "renter · ") + " (script)", "renter"];
  if (a.startsWith("vendor:")) return [a.replace("vendor:", "vendor · ") + " (script)", "vendor"];
  if (a === "owner") return ["owner", "owner"];
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
    case "tool_call": return ["tool", `→ ${d.tool || d.name}(${short(d.args ?? d.arguments ?? "", 90)})`];
    case "tool_result": {
      const ok = d.ok ?? d.result?.ok;
      const err = d.error || d.result?.error;
      if (ok === false) return ["err", `✗ ${d.tool || ""} ${err?.code || ""}: ${err?.message || ""}`];
      return ["ok", `✓ ${d.tool || ""} ${short(d.data ?? d.result?.data ?? "", 90)}`];
    }
    case "verifier": return [d.ok === false ? "vfail" : "vok", `${d.ok === false ? "✗ caught" : "✓ pass"} ${d.check || ""}${d.tool ? " on " + d.tool : ""}${d.detail ? ": " + d.detail : ""}`];
    case "retry": return ["retry", `↻ retry ${d.tool || ""} attempt ${d.attempt ?? "?"} after ${d.reason || ""}${d.backoff_s ? ` (backoff ${d.backoff_s}s)` : ""}`];
    case "fallback": return ["fb", `⤳ fallback ${d.tool ? d.tool + ": " : ""}${d.from ? d.from + " → " : ""}${d.to || ""} ${d.reason ? "(" + d.reason + ")" : ""}`];
    case "escalation": return ["esc", `⚑ escalate: ${d.reason || ""}`];
    case "fault_injected": return ["fault", `💥 injected ${d.kind} on next ${d.tool} (x${d.times || 1})`];
    case "scenario": return ["msg", `scenario ${d.scenario_id} loaded: ${d.counterparts} renters, ${(d.faults || []).length} scripted faults`];
    case "renter_message": return ["msg", `${d.name || ""} [${d.channel || ""}]: “${d.text || ""}”`];
    case "owner_message": return ["msg", `owner: ${d.text || ""}`];
    case "model_message": return ["msg", `${d.thread_id ? "to " + d.thread_id : "to owner"}: ${d.text || ""}`];
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
  box.appendChild(row);
  while (box.childElementCount > 600) box.removeChild(box.firstChild);
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
      lane.innerHTML = `<div class="lane-h"><span>${esc(LANE_NAMES[ch] || ch)}</span><span class="n"></span></div><div class="lane-b"></div>`;
      box.appendChild(lane);
    }
    const L = lanes[ch] || { posts: [], threads: [] };
    lane.querySelector(".n").textContent = `${L.posts.length} post${L.posts.length === 1 ? "" : "s"} · ${L.threads.length} thread${L.threads.length === 1 ? "" : "s"}`;
    const body = lane.querySelector(".lane-b");
    const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    let html = "";
    for (const p of L.posts) {
      const src = imgSrc(p.screenshot);
      const st = p.status || "draft";
      html += `<div class="card">${src ? `<a href="${esc(src)}" target="_blank"><img src="${esc(src)}" alt="screenshot"></a>` : ""}
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
    body.innerHTML = html || `<div class="empty">nothing yet</div>`;
    if (nearBottom) body.scrollTop = 1e9;
  }
}

function renderRegister(reg) {
  $("register").querySelector("tbody").innerHTML = reg.length ? reg.map((r) => `<tr>
    <td><b>${esc(r.name)}</b>${r.channel ? `<span class="v">${esc(r.channel)}</span>` : ""}</td>
    ${GATE.map((g) => { const c = r.gate[g] || { state: "none" };
      return `<td title="${esc(c.value ?? "")}"><span class="tick ${c.state}">${TICK[c.state] || "·"}</span>${c.value != null && c.value !== "" ? `<span class="v">${esc(c.value)}</span>` : ""}</td>`; }).join("")}
    <td class="status">${esc(r.status || "")}</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">no renters yet</td></tr>`;
}

function renderEscalations(list) {
  const open = list.filter((e) => !e.status || e.status === "open");
  $("escCount").textContent = open.length || "";
  $("escalations").innerHTML = list.length ? list.slice().reverse().map((e) => {
    const isOpen = !e.status || e.status === "open";
    return `<div class="esc ${isOpen ? "" : "done"}"><div class="r">${esc(e.reason)}</div>
      ${e.draft ? `<div class="d">“${esc(e.draft)}”</div>` : ""}
      ${isOpen ? `<div class="btns"><button class="approve" data-esc="${esc(e.esc_id)}" data-d="approve">Approve</button>
        <button class="deny" data-esc="${esc(e.esc_id)}" data-d="deny">Deny</button></div>`
        : `<span class="chip">${esc(e.status)}</span>`}</div>`;
  }).join("") : `<div class="empty">nothing needs you</div>`;
}

function renderOps(v) {
  const sp = v.spend || {};
  const lim = sp.limit;
  const pct = lim ? Math.min(100, (100 * (sp.spent || 0)) / lim) : 0;
  $("spend").innerHTML = lim != null ? `<div class="small">Spend <b>$${(sp.spent || 0).toFixed(0)}</b> of $${esc(lim)} limit</div>
    <div class="spendbar ${sp.spent > lim ? "over" : ""}"><div style="width:${pct}%"></div></div>` : "";
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
  renderRegister(v.register || []);
  renderEscalations(v.escalations || []);
  renderOps(v);
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
$("newRun").onclick = async () => { try { await startRun("", null); } catch (e) { sysChat(e.message); } };
$("speed").onchange = async () => {
  if (S.runId) try { await api(`/api/runs/${S.runId}/speed`, { method: "POST", body: { speed: parseFloat($("speed").value) } }); } catch (e) { /* finished run */ }
};
$("breakBtn").onclick = () => $("breakMenu").classList.toggle("hidden");
document.addEventListener("click", (e) => { if (!e.target.closest(".break")) $("breakMenu").classList.add("hidden"); });
$("escalations").onclick = async (e) => {
  const b = e.target.closest("button[data-esc]");
  if (!b) return;
  b.disabled = true;
  try { await api(`/api/runs/${S.runId}/escalations/${b.dataset.esc}`, { method: "POST", body: { decision: b.dataset.d } }); }
  catch (err) { sysChat("Decision failed: " + err.message); }
  scheduleView(200);
};

renderView({ lanes: {}, register: [], escalations: [], jobs: [], quotes: [], spend: {} });
refreshStatus(); loadScenarios(); loadScoreboard();
setInterval(refreshStatus, 3000);
setInterval(() => scheduleView(0), 2000);
setInterval(loadScoreboard, 15000);
setInterval(loadScenarios, 30000);
