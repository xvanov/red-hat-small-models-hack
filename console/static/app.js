/* Rentus Operator console: Inbox, Assistant, Pipeline, Model. Plain JS, no build step. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null || isNaN(x) ? "–" : (x * 100).toFixed(d) + "%");
const fix = (x, d = 2) => (x == null || isNaN(x) ? "–" : Number(x).toFixed(d));
async function j(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
  return d;
}
function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}
const store = {
  get(k, d) { try { const v = localStorage.getItem("rentus." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("rentus." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
function parseTs(ts) {
  if (!ts) return null;
  const d = new Date(ts);
  return isNaN(d) ? null : d;
}
function ago(ts) {
  const d = parseTs(ts);
  if (!d) return "";
  const s = (Date.now() - d) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  if (s < 7 * 86400) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}
function clock(ts) {
  const d = parseTs(ts);
  return d ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "";
}
function day(ts) {
  const d = parseTs(ts);
  if (!d) return "";
  const today = new Date();
  if (d.toDateString() === today.toDateString()) return "Today";
  return d.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
}

// ------------------------------------------------------------------ icons
const I = {
  messenger: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3C7 3 3 6.7 3 11.3c0 2.5 1.2 4.7 3.1 6.2V21l3.2-1.8c.9.3 1.8.4 2.7.4 5 0 9-3.7 9-8.3S17 3 12 3z"/><path d="m7.5 13 3-3 2.5 2 3.5-3"/></svg>',
  sms: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/></svg>',
  email: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
  listing: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 5 5 9-10"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  bot: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="7" width="16" height="12" rx="3"/><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6"/></svg>',
  inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  plug: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  activity: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>',
  wrench: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0 5 5L21 13l-8 8-4-4 8-8-1.3-1.3a4 4 0 0 0-5-5z" transform="translate(-3 0)"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
};
const LISTING_SITES = ["marketplace", "facebook", "roomies", "craigslist", "padsplit", "zillow", "furnished_finder"];
function chIcon(ch) {
  ch = (ch || "").toLowerCase();
  if (ch.includes("messenger") || ch === "facebook_page") return I.messenger;
  if (ch.includes("sms") || ch.includes("text") || ch.includes("phone")) return I.sms;
  if (ch.includes("mail")) return I.email;
  if (LISTING_SITES.some((x) => ch.includes(x))) return I.listing;
  return I.chat;
}
const CH_NAME = { messenger_personal: "Marketplace · Messenger", messenger: "Messenger", sms: "SMS", email: "Email", marketplace: "Marketplace", roomies: "Roomies", craigslist: "Craigslist", padsplit: "PadSplit", facebook: "Facebook" };
const chName = (c) => CH_NAME[(c || "").toLowerCase()] || (c ? c[0].toUpperCase() + c.slice(1) : "Unknown");

const GATE = [["lease", "Lease"], ["move_in", "Move-in"], ["phone", "Phone"], ["reason", "Reason"], ["people", "People"]];
function gateDots(g) {
  g = g || {};
  return `<span class="gate" title="${GATE.map(([k, l]) => `${l}: ${g[k] || "missing"}`).join(" · ")}">${GATE.map(([k]) => `<i class="${g[k] || "missing"}"></i>`).join("")}</span>`;
}
function gateFull(g) {
  g = g || {};
  const word = { exact: "", vague: " (vague)", missing: " (missing)" };
  return `<div class="gate-full">${GATE.map(([k, l]) => `<span class="${g[k] || "missing"}"><span class="gate"><i class="${g[k] || "missing"}"></i></span>${l}${word[g[k] || "missing"]}</span>`).join("")}</div>`;
}
const gateCount = (g) => GATE.filter(([k]) => (g || {})[k] === "exact").length;

const STAGES = [["inquiry", "Inquiry"], ["qualifying", "Qualifying"], ["qualified", "Qualified"], ["showing", "Showing"], ["application", "Application"]];
const STAGE_ALIAS = { new: "inquiry", escalated: "qualifying", showing_proposed: "showing", showing_confirmed: "showing", applied: "application", leased: "application" };
const stageKey = (s) => STAGE_ALIAS[s] || s || "inquiry";
function stageBar(s) {
  const k = stageKey(s);
  const i = STAGES.findIndex(([x]) => x === k);
  const label = i >= 0 ? STAGES[i][1] : esc(k);
  return `<span class="stage">${STAGES.map((_, n) => `<i class="${n <= i ? "on" : ""}"></i>`).join("")}<span>${label}</span></span>`;
}
function emptyState(icon, title, text, detail) {
  return `<div class="empty">${icon}<b>${esc(title)}</b><div>${esc(text)}</div>${detail ? `<div class="detail">${esc(detail)}</div>` : ""}</div>`;
}

// ------------------------------------------------------------------ global state + polling
const S = {
  tab: "inbox", threadId: null, status: null, live: null, threads: null, threadsErr: null, approvals: [], approvalsErr: null,
  thread: null, threadKey: "", filter: store.get("filter", "all"), activity: store.get("activity", true), actFilter: "all",
  editing: {}, run: null, runView: null, turns: [], es: null, results: null, trust: null, perf: null, pipeFilter: "all",
};

async function pollStatus() {
  try {
    S.status = await j("/api/status");
    const b = S.status.badge || {}, r = S.status.reader || {};
    setStat("#st-op", b.backend_up, b.backend_up ? "Operator · Lightning on vLLM" : "Operator · offline");
    setStat("#st-reader", r.live, r.live ? "Reader 0.6B" : "Reader · rules fallback", !r.live ? "warn" : null);
  } catch { setStat("#st-op", false, "Console offline"); }
  try {
    S.live = await j("/api/live/status");
    const el = $("#st-channels");
    if (!S.live.available) {
      el.innerHTML = `<span class="dot"></span>Channels not connected`;
      el.title = S.live.error || "";
    } else {
      el.title = `${S.live.send_enabled ? "Sending enabled" : "Drafts only, nothing is sent"} · allow-list ${S.live.allowlist_size}`;
      el.innerHTML = (S.live.channels || []).map((c) => `<span class="stat" title="${esc(c.line || "")} ${esc(c.detail || "")}"><span class="dot ${c.connected ? "on" : "off"}"></span>${esc(chName(c.channel))}</span>`).join("") || "No channels";
    }
  } catch { /* keep last */ }
}
function setStat(sel, on, label, cls) {
  const el = $(sel);
  el.innerHTML = `<span class="dot ${cls || (on ? "on" : "off")}"></span>${esc(label)}`;
}

async function pollLive() {
  try {
    const [t, a] = await Promise.all([j("/api/live/threads"), j("/api/live/approvals")]);
    S.threads = t.items;
    S.threadsErr = t.available ? null : t.error;
    S.approvals = a.items || [];
    S.approvalsErr = a.available ? null : a.error;
  } catch (e) {
    S.threadsErr = String(e.message || e);
  }
  const liveNeeds = (S.approvals || []).filter((x) => x.source === "live").length;
  const asstNeeds = (S.approvals || []).filter((x) => x.source === "assistant").length;
  badge("#nav-inbox", liveNeeds);
  badge("#nav-assistant", asstNeeds);
  if (S.tab === "inbox") renderThreadList();
  if (S.tab === "pipeline") renderPipeline();
  if (S.tab === "assistant") renderSide();
}
function badge(sel, n) {
  const el = $(sel);
  el.hidden = !n;
  el.textContent = n || "";
}

// ------------------------------------------------------------------ router
function route() {
  const parts = (location.hash || "#/inbox").slice(2).split("/");
  const tab = ["inbox", "assistant", "pipeline", "model"].includes(parts[0]) ? parts[0] : "inbox";
  S.tab = tab;
  $$(".nav a[data-tab]").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  $$("main > .page").forEach((p) => (p.hidden = p.id !== "page-" + tab));
  if (tab === "inbox") {
    mountInbox();
    const id = parts[1] ? decodeURIComponent(parts.slice(1).join("/")) : null;
    if (id !== S.threadId) openThread(id);
  }
  if (tab === "assistant") mountAssistant();
  if (tab === "pipeline") renderPipeline();
  if (tab === "model") renderModel();
}
window.addEventListener("hashchange", route);

// ================================================================== INBOX
function mountInbox() {
  const root = $("#page-inbox");
  if (root.dataset.mounted) return;
  root.dataset.mounted = "1";
  root.innerHTML = `
    <div class="inbox">
      <div class="threads">
        <div class="threads-head">
          <div class="row"><h1>Inbox</h1><button class="btn sm" id="new-convo" style="margin-left:auto">${I.plus}New conversation</button></div>
          <div class="seg" id="thread-filter">
            <button data-f="all">All</button><button data-f="needs">Needs you</button><button data-f="unread">Unread</button>
          </div>
        </div>
        <div class="thread-list" id="thread-list"></div>
      </div>
      <div class="convo" id="convo"></div>
    </div>`;
  $("#thread-filter").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    S.filter = b.dataset.f;
    store.set("filter", S.filter);
    renderThreadList();
  });
  $("#thread-list").addEventListener("click", (e) => {
    const it = e.target.closest(".titem");
    if (it) location.hash = "#/inbox/" + encodeURIComponent(it.dataset.id);
  });
  $("#new-convo").addEventListener("click", newConversation);
  renderThreadList();
  renderConvo();
}

function needsYou(t) {
  return t.needs_owner || (S.approvals || []).some((a) => a.source === "live" && a.thread_id === t.thread_id);
}

function renderThreadList() {
  const el = $("#thread-list");
  if (!el) return;
  const counts = { all: 0, needs: 0, unread: 0 };
  const items = S.threads || [];
  items.forEach((t) => { counts.all++; if (needsYou(t)) counts.needs++; if (t.unread) counts.unread++; });
  $$("#thread-filter button").forEach((b) => {
    b.classList.toggle("on", b.dataset.f === S.filter);
    const c = counts[b.dataset.f];
    b.innerHTML = { all: "All", needs: "Needs you", unread: "Unread" }[b.dataset.f] + (c ? `<span class="c">${c}</span>` : "");
  });
  if (S.threads == null) { el.innerHTML = `<div class="empty"><span class="spinner"></span></div>`; return; }
  if (!items.length) {
    el.innerHTML = S.threadsErr
      ? emptyState(I.plug, "Channels aren't connected", "Conversations from Messenger, SMS and email will show up here once the live channels are running.", S.threadsErr)
      : emptyState(I.inbox, "No conversations yet", "New messages from renters on any channel will appear here.");
    return;
  }
  const shown = items.filter((t) => S.filter === "all" || (S.filter === "needs" ? needsYou(t) : t.unread));
  if (!shown.length) { el.innerHTML = emptyState(I.check, "All caught up", S.filter === "needs" ? "Nothing is waiting for you." : "No unread conversations."); return; }
  el.innerHTML = shown.map((t) => `
    <div class="titem ${t.unread ? "unread" : ""} ${t.thread_id === S.threadId ? "sel" : ""}" data-id="${esc(t.thread_id)}">
      <div class="ch" title="${esc(chName(t.channel))}">${chIcon(t.channel)}</div>
      <div class="name">${esc(t.renter_name || t.contact_display)}</div>
      <div class="time">${esc(ago(t.last_ts))}</div>
      <div class="last">${esc(t.last_text || "")}</div>
      <div class="meta">${needsYou(t) ? `<span class="chip warn">Needs you</span>` : gateDots(t.gate)}</div>
    </div>`).join("");
}

async function openThread(id) {
  S.threadId = id;
  S.thread = null;
  S.threadKey = "";
  S.editing = {};
  renderThreadList();
  renderConvo();
  if (id) await refreshThread();
}

async function refreshThread() {
  const id = S.threadId;
  if (!id || S.tab !== "inbox") return;
  try {
    const t = await j("/api/live/threads/" + encodeURIComponent(id));
    if (id !== S.threadId) return;
    const key = JSON.stringify([t, (S.approvals || []).filter((a) => a.thread_id === id)]);
    if (key === S.threadKey) return;
    S.threadKey = key;
    S.thread = t;
    S.threadErr = null;
    renderConvo();
  } catch (e) {
    S.threadErr = String(e.message || e);
    if (!S.thread) renderConvo();
  }
}

function renderConvo() {
  const root = $("#convo");
  if (!root) return;
  if (!S.threadId) {
    root.innerHTML = emptyState(I.messenger, "Select a conversation", "Pick a thread on the left to read it, approve drafts and see what the operator did.");
    return;
  }
  const t = S.thread;
  if (!t) {
    root.innerHTML = S.threadErr ? emptyState(I.alert, "Couldn't load this conversation", "", S.threadErr) : `<div class="empty"><span class="spinner"></span></div>`;
    return;
  }
  // keep composer text and scroll position across refreshes
  const prevText = $("#reply-text")?.value || "";
  const msgsEl = $("#msgs");
  const stick = !msgsEl || msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 40;
  const prevScroll = msgsEl?.scrollTop;
  const actScroll = $("#act-list")?.scrollTop;
  const sameThread = root.dataset.tid === t.thread_id;
  root.dataset.tid = t.thread_id;

  const pend = (S.approvals || []).filter((a) => a.thread_id === t.thread_id && a.source === "live");
  root.innerHTML = `
    <div class="convo-main">
      <div class="convo-head">
        <div>
          <div class="who">${esc(t.renter_name || t.contact_display)}</div>
          <div class="sub"><span class="chip">${chIcon(t.channel)}${esc(chName(t.channel))}</span>${t.renter_name && t.contact_display !== t.renter_name ? `<span>${esc(t.contact_display)}</span>` : ""}${stageBar(t.stage)}</div>
        </div>
        <div class="right">
          <button class="btn sm ${S.activity ? "" : "ghost"}" id="toggle-act">${I.activity}Activity${(t.trace || []).length ? ` <span class="muted">${t.trace.length}</span>` : ""}</button>
        </div>
      </div>
      <div class="qual">${gateFull(t.gate)}</div>
      <div class="msgs" id="msgs">${renderMessages((t.messages || []).filter((m) => !(["awaiting_approval", "draft"].includes(m.status) && pend.some((a) => (a.draft_text || "").trim() === (m.text || "").trim()))))}</div>
      ${pend.map(renderPending).join("")}
      <div class="composer">
        <textarea id="reply-text" rows="2" placeholder="Write a reply as yourself…"></textarea>
        <div class="bar"><span>Replies go out on ${esc(chName(t.channel))}${S.live && !S.live.send_enabled ? " as drafts (sending is off)" : ""}</span><button class="btn primary sm" id="reply-send">${I.send}Send</button></div>
      </div>
    </div>
    ${S.activity ? `<aside class="activity">${renderActivity(t.trace || [])}</aside>` : ""}`;
  const ta = $("#reply-text");
  ta.value = prevText;
  const m = $("#msgs");
  m.scrollTop = sameThread && !stick ? prevScroll : m.scrollHeight;
  if (sameThread && actScroll != null && $("#act-list")) $("#act-list").scrollTop = actScroll;
  $("#toggle-act").onclick = () => { S.activity = !S.activity; store.set("activity", S.activity); renderConvo(); };
  $("#reply-send").onclick = sendReply;
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) sendReply(); });
  bindPending(root);
  $$("#act-filter button").forEach((b) => (b.onclick = () => { S.actFilter = b.dataset.f; renderConvo(); }));
}

const STATUS_LABEL = { sent: "Sent", received: "", draft: "Draft", failed: "Failed", awaiting_approval: "Waiting for your approval", delivered: "Delivered", read: "Read" };
function renderMessages(ms) {
  if (!ms.length) return emptyState(I.messenger, "No messages yet", "");
  let lastDay = "";
  return ms.map((m) => {
    const d = day(m.ts);
    const sep = d && d !== lastDay ? `<div class="daysep">${esc(d)}</div>` : "";
    lastDay = d || lastDay;
    const st = m.status || (m.direction === "out" ? "sent" : "received");
    const lbl = STATUS_LABEL[st] ?? st;
    const ico = st === "sent" || st === "delivered" ? I.check : st === "failed" ? I.alert : st === "awaiting_approval" || st === "draft" ? I.clock : "";
    return `${sep}<div class="msg ${m.direction === "out" ? "out" : "in"} ${esc(st)}" data-id="${esc(m.id)}">
      <div class="b">${esc(m.text)}</div>
      <div class="m">${m.channel ? esc(chName(m.channel)) + " · " : ""}${esc(clock(m.ts))}${lbl ? ` · <span class="st-${esc(st)}">${ico}${esc(lbl)}</span>` : ""}</div>
    </div>`;
  }).join("");
}

function renderPending(a) {
  const editing = a.id in S.editing;
  return `<div class="pending" data-aid="${esc(a.id)}">
    <div class="why"><b>Draft reply waiting for your approval</b>${a.reason ? `<div>${esc(a.reason)}</div>` : ""}</div>
    ${editing ? `<textarea rows="3" class="edit-text">${esc(S.editing[a.id])}</textarea>` : a.draft_text ? `<div class="draft">${esc(a.draft_text)}</div>` : `<div class="muted small">No draft: write the reply yourself or approve the operator's plan.</div>`}
    <div class="acts">
      ${editing
        ? `<button class="btn ok" data-act="send-edit">${I.check}Send edited reply</button><button class="btn ghost" data-act="cancel">Cancel</button>`
        : `<button class="btn ok" data-act="approve">${I.check}Approve &amp; send</button><button class="btn" data-act="edit">Edit</button><button class="btn danger" data-act="deny">Deny</button>`}
    </div>
  </div>`;
}
function bindPending(root, after) {
  $$(".pending", root).forEach((el) => {
    const id = el.dataset.aid;
    el.addEventListener("input", (e) => { if (e.target.classList.contains("edit-text")) S.editing[id] = e.target.value; });
    el.addEventListener("click", async (e) => {
      const b = e.target.closest("button[data-act]");
      if (!b) return;
      const a = (S.approvals || []).find((x) => x.id === id) || {};
      const act = b.dataset.act;
      if (act === "edit") { S.editing[id] = a.draft_text || ""; return rerenderApprovals(after); }
      if (act === "cancel") { delete S.editing[id]; return rerenderApprovals(after); }
      const body = act === "send-edit" ? { decision: "edit", text: S.editing[id] } : { decision: act };
      $$("button", el).forEach((x) => (x.disabled = true));
      try {
        await post("/api/live/approvals/" + encodeURIComponent(id), body);
        delete S.editing[id];
        S.approvals = S.approvals.filter((x) => x.id !== id);
        toast(act === "deny" ? "Denied" : "Approved");
      } catch (err) {
        toast("Couldn't record the decision: " + err.message);
      }
      await pollLive();
      rerenderApprovals(after);
    });
  });
}
function rerenderApprovals(after) {
  if (after) return after();
  S.threadKey = "";
  renderConvo();
  refreshThread();
}

async function sendReply() {
  const ta = $("#reply-text");
  const text = ta.value.trim();
  if (!text || !S.threadId) return;
  $("#reply-send").disabled = true;
  try {
    await post(`/api/live/threads/${encodeURIComponent(S.threadId)}/reply`, { text });
    ta.value = "";
    S.threadKey = "";
    await refreshThread();
  } catch (e) {
    toast("Not sent: " + e.message);
  } finally {
    const b = $("#reply-send");
    if (b) b.disabled = false;
  }
}

const ACTOR = { operator: "Operator", reader: "Reader", verifier: "Verifier", tool: "Tool" };
function markRecoveries(trace) {
  // a failed step followed later by a successful one is a recovery; label the first success after it
  const out = trace.map((x) => ({ ...x }));
  for (let i = 0; i < out.length; i++) {
    if (out[i].ok !== false) continue;
    const k = out.findIndex((y, n) => n > i && y.ok !== false && !y._recovers);
    if (k > 0) { out[k]._recovers = out[i].name || "error"; out[i]._recovered = true; }
  }
  return out;
}
function renderTrace(trace, filter) {
  const marked = markRecoveries(trace);
  const rows = filter === "issues" ? marked.filter((x) => x.ok === false || x._recovers) : marked;
  if (!rows.length) return `<div class="empty small">${filter === "issues" ? "No errors or recoveries." : "Nothing recorded yet."}</div>`;
  return rows.map((x) => `
    <div class="ev ${x.ok === false ? "fail" : x._recovers ? "recovered" : ""}">
      <div class="ic"><i></i></div>
      <div class="t"><span class="who ${esc(x.actor)}">${esc(ACTOR[x.actor] || x.actor || "")}</span><span class="nm">${esc(x.name || "")}</span><span class="ts">${esc(clock(x.ts))}</span></div>
      ${x.summary ? `<div class="s">${esc(x.summary)}</div>` : ""}
      ${x._recovers ? `<div class="rec">Recovered from ${esc(x._recovers)}</div>` : ""}
    </div>`).join("");
}
function renderActivity(trace) {
  const n = (a) => trace.filter((x) => x.actor === a).length;
  const fails = trace.filter((x) => x.ok === false).length;
  const rec = markRecoveries(trace).filter((x) => x._recovers).length;
  return `
    <div class="activity-head">Activity<div class="right"><div class="seg" id="act-filter"><button data-f="all" class="${S.actFilter === "all" ? "on" : ""}">All</button><button data-f="issues" class="${S.actFilter === "issues" ? "on" : ""}">Errors &amp; recoveries</button></div></div></div>
    <div class="act-sum">
      <span class="chip">${n("tool") + n("operator")} tool calls</span>
      <span class="chip">${n("reader")} reader parses</span>
      <span class="chip ${fails ? "err" : ""}">${fails} caught</span>
      <span class="chip ${rec ? "ok" : ""}">${rec} recovered</span>
    </div>
    <div class="act-list" id="act-list">${renderTrace(trace, S.actFilter)}</div>`;
}

function newConversation() {
  const chans = (S.live?.channels || []).map((c) => c.channel);
  const opts = (chans.length ? chans : ["messenger", "sms", "email"]).map((c) => `<option value="${esc(c)}">${esc(chName(c))}</option>`).join("");
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal" role="dialog">
    <h3>New conversation</h3>
    <div class="mb">
      <label>Channel<select id="nc-ch">${opts}</select></label>
      <label>To<input type="text" id="nc-to" placeholder="Phone, email or Messenger id"></label>
      <label>Message<textarea id="nc-text" rows="3" placeholder="Hi, this is Rentus about the room on…"></textarea></label>
      <div class="muted small">${S.live?.send_enabled ? `Sends only to the ${S.live.allowlist_size} allow-listed contacts.` : "Sending is off: the message is kept as a draft."}</div>
    </div>
    <div class="mf"><button class="btn ghost" data-x>Cancel</button><button class="btn primary" id="nc-go">Start</button></div>
  </div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  bg.addEventListener("click", (e) => { if (e.target === bg || e.target.closest("[data-x]")) close(); });
  $("#nc-to", bg).focus();
  $("#nc-go", bg).onclick = async () => {
    try {
      const r = await post("/api/live/conversations", { channel: $("#nc-ch", bg).value, to: $("#nc-to", bg).value, text: $("#nc-text", bg).value });
      close();
      await pollLive();
      const tid = r.result?.thread_id;
      if (tid) location.hash = "#/inbox/" + encodeURIComponent(tid);
    } catch (e) { toast(e.message); }
  };
}

// ================================================================== ASSISTANT
function mountAssistant() {
  const root = $("#page-assistant");
  if (!root.dataset.mounted) {
    root.dataset.mounted = "1";
    root.innerHTML = `
      <div class="assist">
        <div class="chat">
          <div class="page-head" style="padding-bottom:10px;border-bottom:1px solid var(--line)"><h1>Assistant</h1><span class="sub">Tell the operator what you need. It lists rooms, handles repairs and asks you before anything goes out.</span><div class="right"><button class="btn sm" id="new-chat">New chat</button></div></div>
          <div class="chat-scroll" id="chat-scroll"><div class="chat-inner" id="chat"></div></div>
          <div class="chat-compose"><div class="composer">
            <textarea id="ask" rows="2" placeholder="e.g. Appling Way room free Nov 1, $750, private bath"></textarea>
            <div class="bar"><span id="run-state"></span><button class="btn primary sm" id="ask-send">${I.send}Send</button></div>
          </div></div>
        </div>
        <aside class="side" id="side"></aside>
      </div>`;
    $("#ask-send").onclick = ask;
    $("#ask").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } });
    $("#new-chat").onclick = async () => {
      await post("/api/reset").catch(() => {});
      attachRun(null);
    };
    $("#chat").addEventListener("click", (e) => {
      const b = e.target.closest(".steps-toggle");
      if (b) { const t = S.turns[+b.dataset.i]; t.open = !t.open; renderChat(); return; }
      const s = e.target.closest(".suggest button");
      if (s) { $("#ask").value = s.textContent; ask(); }
    });
  }
  const active = S.status?.active_run;
  const live = active && !["stopped", "error"].includes(S.status?.run_status);
  if (live && active !== S.run) attachRun(active);
  else if (!live && !S.run) renderChat();
  renderSide();
}

function attachRun(id) {
  if (S.es) { S.es.close(); S.es = null; }
  S.run = id;
  S.turns = [];
  S.runView = null;
  S.calls = {};
  renderChat();
  renderSide();
  if (!id) return;
  S.es = new EventSource(`/api/runs/${id}/events`);
  let pending = false;
  S.es.onmessage = (m) => {
    try { onRunEvent(JSON.parse(m.data)); } catch { return; }
    if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; renderChat(); }); }
  };
}

function curTurn() { return S.turns[S.turns.length - 1]; }
function onRunEvent(e) {
  const d = e.data || {};
  if (e.type === "owner_message" && e.actor === "owner") {
    S.turns.push({ owner: d.text, steps: [], reply: null, done: false, open: false, ts: e.ts });
    return;
  }
  const t = curTurn();
  if (!t) return;
  if (e._src === "console" && e.type === "turn_done" && (d.kind === "owner" || !d.thread_id)) {
    if (d.kind !== "owner") return;
    t.done = true;
    t.reply = d.final_text || t.reply;
    t.stats = d;
    return;
  }
  if (e.type === "owner_message" && e.actor === "operator") { t.reply = t.reply || d.summary || d.text; return; }
  if (d.thread_id && e.type !== "escalation") return; // renter conversations are not part of the owner's chat
  if (e.type === "tool_call") {
    const s = { kind: "tool", actor: e.actor === "verifier" ? "verifier" : "operator", name: d.tool, args: d.args, ok: null, ts: e.ts };
    t.steps.push(s);
    if (d.call_id) S.calls[d.call_id] = s;
  } else if (e.type === "tool_result") {
    const s = S.calls[d.call_id];
    const r = d.result || {};
    if (s) { s.ok = r.ok !== false; s.err = r.error ? (r.error.code || "") + (r.error.message ? ": " + r.error.message : "") : null; s.result = r.data; }
  } else if (e.type === "verifier" && d.ok === false) {
    t.steps.push({ kind: "verifier", actor: "verifier", name: d.stage || "check", ok: false, err: (d.problems || []).join("; "), ts: e.ts });
  } else if (e.type === "retry") {
    t.steps.push({ kind: "retry", actor: "verifier", name: "retry " + (d.tool || ""), ok: true, err: `${d.code || ""} → retried (attempt ${d.attempt || 1})`, ts: e.ts, recovery: true });
  } else if (e.type === "fallback") {
    t.steps.push({ kind: "fallback", actor: "verifier", name: "fallback " + (d.tool || ""), ok: true, err: [d.code, d.suggestion || d.note].filter(Boolean).join(" → "), ts: e.ts, recovery: true });
  } else if (e.type === "reader" || (e.type === "tool_call" && d.tool === "read_reply")) {
    t.steps.push({ kind: "reader", actor: "reader", name: "read_reply", ok: true, ts: e.ts });
  }
}

function argSummary(a) {
  if (!a || typeof a !== "object") return "";
  const parts = Object.entries(a).filter(([, v]) => v != null && v !== "").slice(0, 3).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`);
  const s = parts.join(", ");
  return s.length > 110 ? s.slice(0, 107) + "…" : s;
}
function renderChat() {
  const el = $("#chat");
  if (!el) return;
  const st = S.status?.run_status;
  const busy = S.turns.length && !curTurn().done;
  $("#run-state").textContent = busy ? "Working…" : S.run ? "" : "Enter to send";
  if (!S.turns.length) {
    el.innerHTML = `<div class="empty" style="padding-top:80px">${I.bot}<b>What should the operator do?</b><div>Describe a room to list, a repair, or a question about your renters.</div>
      <div class="suggest">
        <button>Appling Way room free Nov 1, $750, private bath. Post it on Marketplace, Roomies and Craigslist.</button>
        <button>The tenant at Appling Way says the kitchen sink is leaking. Get quotes and book the cheapest plumber under $400.</button>
      </div></div>`;
    return;
  }
  const sc = $("#chat-scroll");
  const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 60;
  el.innerHTML = S.turns.map((t, i) => {
    const tools = t.steps.filter((s) => s.kind === "tool").length;
    const issues = t.steps.filter((s) => s.ok === false).length;
    const recov = t.steps.filter((s) => s.recovery).length;
    const trace = t.steps.map((s) => ({ ts: s.ts, actor: s.name === "read_reply" ? "reader" : s.actor, name: s.name, ok: s.ok === null ? undefined : s.ok,
      summary: s.err || argSummary(s.args) }));
    return `<div class="turn-owner">${esc(t.owner)}</div>
      <div class="turn-op"><div class="av">${I.bot}</div><div class="body">
        ${t.reply ? `<div class="text">${esc(t.reply)}</div>` : ""}
        ${!t.done ? `<div class="working"><span class="spinner"></span>${t.steps.length ? esc(lastStepLabel(t)) : "Thinking…"}</div>` : ""}
        ${t.steps.length ? `<button class="steps-toggle" data-i="${i}">${t.open ? "Hide" : "Show"} ${tools} tool call${tools === 1 ? "" : "s"}${t.stats?.seconds ? ` · ${Math.round(t.stats.seconds)}s` : ""}${issues ? ` <span class="chip err">${issues} caught</span>` : ""}${recov ? ` <span class="chip ok">${recov} recovered</span>` : ""}</button>` : ""}
        ${t.open ? `<div class="steps">${renderTrace(trace, "all")}</div>` : ""}
      </div></div>`;
  }).join("");
  if (stick) sc.scrollTop = sc.scrollHeight;
  void st;
}
function lastStepLabel(t) {
  const s = t.steps[t.steps.length - 1];
  return s.kind === "tool" ? `Calling ${s.name}…` : s.name;
}

async function ask() {
  const ta = $("#ask");
  const text = ta.value.trim();
  if (!text) return;
  ta.value = "";
  const st = S.status?.run_status;
  try {
    if (!S.run || ["stopped", "error"].includes(st)) {
      const r = await post("/api/runs", { goal: text, seed_renters: false });
      attachRun(r.run_id);
      S.status = { ...(S.status || {}), active_run: r.run_id, run_status: "starting" };
    } else {
      await post(`/api/runs/${S.run}/owner`, { text });
    }
  } catch (e) {
    toast("Couldn't reach the operator: " + e.message);
    ta.value = text;
  }
}

async function pollRunView() {
  if (S.tab !== "assistant" || !S.run) return;
  try {
    S.runView = await j(`/api/runs/${S.run}/view`);
    renderSide();
  } catch { /* run gone */ }
}

const POST_STATUS = {
  live: ["ok", "Posted"], posted: ["ok", "Posted"], ready_to_submit: ["warn", "Needs your click"], draft: ["", "Draft"],
  failed: ["err", "Failed"], error: ["err", "Failed"], pending: ["", "Posting…"],
};
function renderSide() {
  const el = $("#side");
  if (!el || S.tab !== "assistant") return;
  const key = JSON.stringify([S.runView, (S.approvals || []).filter((a) => a.source === "assistant"), S.editing]);
  if (key === el.dataset.key) return;
  if ($(".edit-text", el) && document.activeElement?.classList.contains("edit-text")) return; // don't clobber typing
  el.dataset.key = key;
  const v = S.runView;
  const aps = (S.approvals || []).filter((a) => a.source === "assistant");
  const out = [];
  if (aps.length) out.push(`<h2>Needs your approval</h2>` + aps.map(renderPending).join(""));
  for (const l of v?.listings || []) {
    const chans = Object.entries(l.channels || {});
    out.push(`<h2>Listing</h2><div class="card listing-prev"><div class="card-body">
      <div style="display:flex;gap:8px;align-items:baseline"><div class="ttl">${esc(l.title || l.listing_id)}</div><div class="price" style="margin-left:auto">${l.price ? "$" + esc(l.price) + "/mo" : ""}</div></div>
      ${l.body ? `<div class="desc">${esc(l.body)}</div>` : ""}
    </div>${chans.length ? `<div class="card-body rows" style="border-top:1px solid var(--line)">${chans.map(([ch, p]) => {
      p = typeof p === "object" && p ? p : { status: String(p) };
      const [cls, label] = POST_STATUS[p.status] || ["", p.status || "–"];
      const link = p.url ? `<a class="btn sm" href="${esc(p.url)}" target="_blank" rel="noopener">${p.status === "ready_to_submit" ? "Publish" : "View"}</a>`
        : p.screenshot ? `<a class="btn sm" href="/api/file?path=${encodeURIComponent(p.screenshot)}" target="_blank">${p.status === "ready_to_submit" ? "Review &amp; publish" : "Screenshot"}</a>` : "";
      return `<div>${chIcon(ch)}${esc(chName(ch))}<span class="r"><span class="chip ${cls}">${esc(label)}</span>${link}</span></div>`;
    }).join("")}</div>` : ""}</div>`);
  }
  for (const jb of v?.jobs || []) {
    const qs = (v.quotes || []).filter((q) => q.job_id === jb.job_id);
    const vendor = (id) => v.vendors?.[id] || id;
    out.push(`<h2>Maintenance</h2><div class="card"><div class="card-body">
      <div style="display:flex;gap:8px"><b>${esc(jb.issue || jb.job_id)}</b><span class="chip ${jb.status === "booked" || jb.status === "done" ? "ok" : ""}" style="margin-left:auto">${esc(jb.status || "open")}</span></div>
      <div class="muted small">${esc(jb.address || jb.property || "")}${jb.scheduled_for ? " · scheduled " + esc(jb.scheduled_for) : ""}</div>
    </div>${qs.length ? `<div class="card-body rows" style="border-top:1px solid var(--line)">${qs.map((q) => `<div>${esc(q.vendor_name || vendor(q.vendor_id))}<span class="r"><span class="num">$${esc(q.amount)}</span><span class="chip ${q.status === "accepted" ? "ok" : q.status === "declined" ? "" : ""}">${esc(q.status || "quoted")}</span></span></div>`).join("")}</div>` : ""}
    ${v.spend?.limit ? `<div class="card-body small muted" style="border-top:1px solid var(--line)">Spent $${esc(v.spend.spent)} of your $${esc(v.spend.limit)} limit</div>` : ""}</div>`);
  }
  const cal = (v?.calendar || []).filter((c) => c.status !== "cancelled");
  if (cal.length) out.push(`<h2>Showings</h2><div class="card"><div class="card-body rows">${cal.map((c) => `<div>${I.cal}${esc(c.title)}<span class="r"><span class="muted small">${esc((c.start || "").replace("T", " "))}</span><span class="chip ${c.status === "confirmed" ? "ok" : "warn"}">${esc(c.status)}</span></span></div>`).join("")}</div></div>`);
  el.innerHTML = out.length ? out.join("") : emptyState(I.listing, "Nothing here yet", "Listings, posting status, repair quotes and showings the operator works on appear here.");
  bindPending(el, () => { delete el.dataset.key; renderSide(); });
}

// ================================================================== PIPELINE
function renderPipeline() {
  const root = $("#page-pipeline");
  if (S.tab !== "pipeline") return;
  const items = S.threads || [];
  const counts = {};
  items.forEach((t) => (counts[stageKey(t.stage)] = (counts[stageKey(t.stage)] || 0) + 1));
  const shown = items.filter((t) => S.pipeFilter === "all" || stageKey(t.stage) === S.pipeFilter)
    .sort((a, b) => STAGES.findIndex(([k]) => k === stageKey(b.stage)) - STAGES.findIndex(([k]) => k === stageKey(a.stage)) || String(b.last_ts).localeCompare(String(a.last_ts)));
  const key = JSON.stringify([shown, S.pipeFilter, counts]);
  if (root.dataset.key === key) return;
  root.dataset.key = key;
  root.innerHTML = `
    <div class="page-head"><h1>Pipeline</h1><span class="sub">${items.length} ${items.length === 1 ? "person" : "people"} across all channels</span></div>
    <div class="page-body">
      <div class="seg" id="pipe-filter" style="margin-bottom:14px">
        <button data-f="all" class="${S.pipeFilter === "all" ? "on" : ""}">All<span class="c">${items.length || ""}</span></button>
        ${STAGES.map(([k, l]) => `<button data-f="${k}" class="${S.pipeFilter === k ? "on" : ""}">${l}<span class="c">${counts[k] || ""}</span></button>`).join("")}
      </div>
      <div class="card">${!items.length
        ? emptyState(I.inbox, S.threadsErr ? "Channels aren't connected" : "No prospects yet", "Everyone who writes in on any channel shows up here with their stage and what we still need from them.", S.threadsErr)
        : !shown.length ? emptyState(I.check, "No one at this stage", "")
        : `<table class="t"><thead><tr><th>Name</th><th>Channel</th><th>Stage</th><th>Qualification</th><th>Last message</th><th class="r">Updated</th></tr></thead><tbody>
        ${shown.map((t) => `<tr class="click" data-id="${esc(t.thread_id)}">
          <td><b>${esc(t.renter_name || t.contact_display)}</b>${needsYou(t) ? ` <span class="chip warn">Needs you</span>` : ""}</td>
          <td><span class="chip">${chIcon(t.channel)}${esc(chName(t.channel))}</span></td>
          <td>${stageBar(t.stage)}</td>
          <td>${gateDots(t.gate)} <span class="muted small num">${gateCount(t.gate)}/5</span></td>
          <td><div class="ell">${esc(t.last_text || "")}</div></td>
          <td class="r muted num">${esc(ago(t.last_ts))}</td></tr>`).join("")}</tbody></table>`}
      </div>
    </div>`;
  $("#pipe-filter").onclick = (e) => { const b = e.target.closest("button"); if (b) { S.pipeFilter = b.dataset.f; renderPipeline(); } };
  $$("tr.click", root).forEach((r) => (r.onclick = () => (location.hash = "#/inbox/" + encodeURIComponent(r.dataset.id))));
}

// ================================================================== MODEL
function wilson(p, n, z = 1.96) {
  if (p == null || !n) return null;
  const d = 1 + (z * z) / n, c = (p + (z * z) / (2 * n)) / d, h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
function barChart(rows, { max = 1, fmt = (x) => pct(x), hl = () => false, labelW = 200 } = {}) {
  // horizontal bars with optional 95% CI whiskers: rows = [{label, value, ci:[lo,hi], sub}]
  const W = 640, rowH = 30, top = 6, bottom = 22, plotW = W - labelW - 60;
  const H = top + rows.length * rowH + bottom;
  const x = (v) => labelW + Math.max(0, Math.min(1, v / max)) * plotW;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
  ticks.forEach((tk) => { s += `<line class="grid" x1="${x(tk)}" x2="${x(tk)}" y1="${top}" y2="${H - bottom}"/><text x="${x(tk)}" y="${H - 6}" text-anchor="middle">${fmt(tk)}</text>`; });
  rows.forEach((r, i) => {
    const y = top + i * rowH, cy = y + rowH / 2;
    s += `<text class="lab" x="${labelW - 10}" y="${cy + 4}" text-anchor="end">${esc(r.label)}</text>`;
    if (r.value == null) { s += `<text x="${labelW + 4}" y="${cy + 4}">no data</text>`; return; }
    s += `<rect class="bar ${hl(r) ? "hl" : ""}" x="${labelW}" y="${y + 7}" width="${Math.max(1, x(r.value) - labelW)}" height="${rowH - 14}" rx="3"/>`;
    if (r.ci) s += `<line class="whisk" x1="${x(r.ci[0])}" x2="${x(r.ci[1])}" y1="${cy}" y2="${cy}"/><line class="whisk" x1="${x(r.ci[0])}" x2="${x(r.ci[0])}" y1="${cy - 5}" y2="${cy + 5}"/><line class="whisk" x1="${x(r.ci[1])}" x2="${x(r.ci[1])}" y1="${cy - 5}" y2="${cy + 5}"/>`;
    s += `<text class="val" x="${x(r.ci ? Math.max(r.ci[1], r.value) : r.value) + 8}" y="${cy + 4}">${fmt(r.value)}</text>`;
  });
  return s + "</svg>";
}
const ciTxt = (ci, f = pct) => (ci ? `<span class="ci">${f(ci[0])}–${f(ci[1])}</span>` : "");
const pTxt = (p) => (p == null ? "–" : p < 0.001 ? "<0.001" : p.toFixed(3));

async function renderModel(force) {
  const root = $("#page-model");
  if (!S.results || force) {
    if (!root.innerHTML) root.innerHTML = `<div class="empty"><span class="spinner"></span></div>`;
    const [r, t, p] = await Promise.allSettled([j("/api/results"), j("/api/trust"), j("/api/performance")]);
    S.results = r.value || null;
    S.trust = t.value || null;
    S.perf = p.value || null;
    S.modelAt = Date.now();
  }
  if (S.tab !== "model") return;
  const R = S.results || {}, T = S.trust || {}, P = S.perf || {};
  const cfgs = R.configs || [];
  const base = cfgs.find((c) => c.kind === "baseline"), fin = cfgs.find((c) => c.kind === "final");
  const rd = T.reader || {};
  const budget = T.budget || {};
  const kinds = { baseline: 0, final: 1, variant: 2, reference: 3 };
  const ordered = [...cfgs].sort((a, b) => (kinds[a.kind] ?? 2) - (kinds[b.kind] ?? 2));
  const tasks = fin?.tasks || base?.tasks;
  const short = (l) => String(l || "").replace(", same harness (reference)", " (reference)").replace(" simple_agent", "");

  const kpi = (l, v, d) => `<div class="card kpi"><div class="l">${l}</div><div class="v num">${v}</div><div class="d">${d}</div></div>`;
  const heldout = cfgs.length ? `
    <div class="section">
      <h2>Held-out evaluation${R.version ? ` <span class="chip">${esc(R.version)}</span>` : ""}</h2>
      <p class="lead">${tasks || "–"} held-out tasks the system never trained or tuned on, scored by code checks in a simulated landlord world. Bars show the mean over runs; whiskers are 95% confidence intervals.</p>
      <div class="grid2">
        <div class="card chart"><div class="ttl">Pass rate</div><div class="cap">Share of tasks where every check passed</div>${barChart(ordered.map((c) => ({ label: short(c.label), value: c.pass_rate, ci: c.pass_ci, kind: c.kind })), { hl: (r) => r.kind === "final" })}</div>
        <div class="card chart"><div class="ttl">Mean reward</div><div class="cap">Average share of checks passed per task</div>${barChart(ordered.map((c) => ({ label: short(c.label), value: c.mean_reward, ci: c.reward_ci, kind: c.kind })), { hl: (r) => r.kind === "final", fmt: (x) => fix(x, 2) })}</div>
      </div>
      <div class="card" style="margin-top:16px"><table class="t"><thead><tr><th>Configuration</th><th class="r">Runs</th><th class="r">Pass rate</th><th class="r">Mean reward</th><th class="r">Passes every run</th><th class="r">Median time / task</th><th class="r">Model calls / task</th></tr></thead><tbody>
        ${ordered.map((c) => `<tr class="${c.kind === "final" ? "hl" : ""}"><td><b>${esc(c.label)}</b><div class="muted small">${esc(c.model || "")}${c.config_label ? " · " + esc(c.config_label) : ""}</div></td>
          <td class="r num">${c.runs ?? "–"}</td><td class="r num">${pct(c.pass_rate, 1)}<br>${ciTxt(c.pass_ci, (x) => pct(x, 0))}</td>
          <td class="r num">${fix(c.mean_reward, 3)}<br>${ciTxt(c.reward_ci, (x) => fix(x, 2))}</td>
          <td class="r num">${c.pass_all_runs == null ? "–" : pct(c.pass_all_runs, 0)}</td><td class="r num">${c.task_seconds_p50 == null ? "–" : Math.round(c.task_seconds_p50) + " s"}</td>
          <td class="r num">${c.model_calls_mean == null ? "–" : fix(c.model_calls_mean, 1)}</td></tr>`).join("")}
      </tbody></table></div>
      ${(R.compare || []).length ? `<div class="card" style="margin-top:16px"><div class="card-head">Paired comparisons<span class="right muted small">same tasks, Holm-corrected p-values</span></div><table class="t"><thead><tr><th>Comparison</th><th class="r">Δ mean reward</th><th class="r">95% CI</th><th class="r">p (reward)</th><th class="r">Δ pass rate</th><th class="r">Tasks better / worse</th><th class="r">p (pass)</th></tr></thead><tbody>
        ${R.compare.map((c) => `<tr><td>${esc(c.a)} <span class="muted">vs</span> ${esc(c.b)}</td><td class="r num">${c.d_reward >= 0 ? "+" : ""}${fix(c.d_reward, 3)}</td><td class="r num ci">${fix(c.d_reward_ci?.[0], 3)} to ${fix(c.d_reward_ci?.[1], 3)}</td><td class="r num">${pTxt(c.p_reward_holm)}</td><td class="r num">${c.d_pass >= 0 ? "+" : ""}${pct(c.d_pass, 1)}</td><td class="r num">${c.a_better} / ${c.b_better}</td><td class="r num">${pTxt(c.p_pass_holm)}</td></tr>`).join("")}
      </tbody></table></div>` : ""}
      ${R.categories?.baseline && R.categories?.final ? `<div class="card" style="margin-top:16px"><div class="card-head">By category</div><table class="t"><thead><tr><th>Category</th><th class="r">Tasks</th><th class="r">Baseline pass</th><th class="r">Final pass</th><th class="r">Baseline reward</th><th class="r">Final reward</th></tr></thead><tbody>
        ${Object.keys(R.categories.final).map((k) => { const b = R.categories.baseline[k] || {}, f = R.categories.final[k] || {}; return `<tr><td>${esc(k)}</td><td class="r num">${f.tasks ?? b.tasks ?? "–"}</td><td class="r num">${pct(b.pass_rate, 0)}</td><td class="r num"><b>${pct(f.pass_rate, 0)}</b></td><td class="r num">${fix(b.mean_reward, 2)}</td><td class="r num"><b>${fix(f.mean_reward, 2)}</b></td></tr>`; }).join("")}
      </tbody></table></div>` : ""}
      <div class="src">Source: <code>${esc(R.source || "")}</code> · <code>${esc(R.doc || "")}</code></div>
    </div>` : `<div class="section"><h2>Held-out evaluation</h2><div class="card">${emptyState(I.activity, "No held-out results yet", "Results appear here as soon as the evaluation runs write their files.")}</div></div>`;

  const n = rd.sample_n;
  const readerRows = [
    { label: "rentus-reader 0.6B (ours)", value: rd.sample?.finetuned, hl: true },
    { label: "Claude Opus 5.5", value: rd.opus_exact_match },
    { label: "Rules fallback (code)", value: rd.sample?.fallback },
    { label: "Lightning 30B, prompted", value: rd.sample?.lightning },
    { label: "Qwen3-0.6B, not fine-tuned", value: rd.sample?.base },
  ].map((r) => ({ ...r, ci: wilson(r.value, n) }));
  const reader = rd.sample ? `
    <div class="section">
      <h2>Reader</h2>
      <p class="lead">The reader turns a renter's message into exact fields (lease length, move-in date, phone, reason, people). Exact match means every field is right. Same ${n} held-out messages for every model; whiskers are Wilson 95% intervals.</p>
      <div class="grid2">
        <div class="card chart"><div class="ttl">Exact match</div><div class="cap">${n} held-out messages</div>${barChart(readerRows, { hl: (r) => r.hl })}</div>
        <div class="card"><table class="t"><tbody>
          <tr><td class="muted">Base model</td><td>${esc(rd.base_model)} + supervised fine-tuning</td></tr>
          <tr><td class="muted">Training</td><td class="num">${esc(rd.train_rows?.toLocaleString())} rows, ${esc(rd.train_minutes)} min on one ${esc(rd.gpu)}</td></tr>
          <tr><td class="muted">Full test set</td><td class="num">${pct(rd.exact_match_full, 1)} exact match on ${esc(rd.test_rows?.toLocaleString())} rows</td></tr>
          <tr><td class="muted">Latency (p50)</td><td class="num">${rd.latency_p50_s != null ? Math.round(rd.latency_p50_s * 1000) + " ms" : "–"} <span class="muted">vs Opus ${rd.opus_latency_p50_s != null ? fix(rd.opus_latency_p50_s, 1) + " s" : "–"}</span></td></tr>
          <tr><td class="muted">Cost per read</td><td class="num">$0 on our GPU <span class="muted">vs Opus $${fix(rd.opus_cost_per_read_usd, 4)}</span></td></tr>
          <tr><td class="muted">Weights</td><td>${rd.hf ? `<a href="${esc(rd.hf)}" target="_blank" rel="noopener">${esc(rd.hf.replace("https://", ""))}</a>` : "–"}</td></tr>
        </tbody></table></div>
      </div>
    </div>` : "";

  const pre = P.prefix || [], rsn = P.reasoning || [], sweep = P.sweep || [];
  const ron = rsn.find((x) => x.reasoning === "on"), roff = rsn.find((x) => x.reasoning === "off");
  const serving = sweep.length || pre.length ? `
    <div class="section">
      <h2>Serving on vLLM</h2>
      <p class="lead">Both models run on one ${esc(P.hardware?.gpu || "GPU")}${P.hardware?.price ? ` (${esc(P.hardware.price)})` : ""} under vLLM. Replayed operator requests (about ${sweep[0]?.prompt_tok_mean?.toLocaleString() || "6,000"} prompt tokens, with tool calls) at increasing concurrency. ${P.totals ? `${P.totals.requests.toLocaleString()} requests, ${P.totals.errors} errors.` : ""}</p>
      <div class="grid2">
        ${pre.length ? `<div class="card"><div class="card-head">Prefix caching<span class="right muted small">time to first token, p50</span></div><table class="t"><thead><tr><th>Concurrent requests</th><th class="r">Caching on</th><th class="r">Caching off</th><th class="r">Cache hit rate</th><th class="r">Throughput on / off</th></tr></thead><tbody>
          ${pre.map((r) => `<tr><td class="num">${r.n}</td><td class="r num"><b>${r.on?.ttft_p50_ms ?? "–"} ms</b></td><td class="r num">${r.off?.ttft_p50_ms ?? "–"} ms</td><td class="r num">${pct(r.on?.hit, 0)}</td><td class="r num">${fix(r.on?.tok_s, 0)} / ${fix(r.off?.tok_s, 0)} tok/s</td></tr>`).join("")}
        </tbody></table></div>` : ""}
        ${ron && roff ? `<div class="card"><div class="card-head">Reasoning off for tool calls<span class="right muted small">${ron.n} concurrent</span></div><table class="t"><thead><tr><th></th><th class="r">Reasoning off</th><th class="r">Reasoning on</th></tr></thead><tbody>
          <tr><td>Requests / s</td><td class="r num"><b>${fix(roff.req_s, 1)}</b></td><td class="r num">${fix(ron.req_s, 1)}</td></tr>
          <tr><td>Latency p50</td><td class="r num"><b>${fix(roff.lat_p50_s, 2)} s</b></td><td class="r num">${fix(ron.lat_p50_s, 2)} s</td></tr>
          <tr><td>Latency p95</td><td class="r num"><b>${fix(roff.lat_p95_s, 2)} s</b></td><td class="r num">${fix(ron.lat_p95_s, 2)} s</td></tr>
          <tr><td>Output tokens / request</td><td class="r num"><b>${roff.out_tok_mean}</b></td><td class="r num">${ron.out_tok_mean}</td></tr>
          <tr><td>Requests ending in a tool call</td><td class="r num">${pct(roff.tool_call_share, 0)}</td><td class="r num">${pct(ron.tool_call_share, 0)}</td></tr>
        </tbody></table></div>` : ""}
      </div>
      ${sweep.length ? `<div class="card" style="margin-top:16px"><div class="card-head">Two models on one card<span class="right muted small">operator load vs reader latency on the same GPU</span></div><table class="t"><thead><tr><th>Concurrent operator requests</th><th class="r">Operator throughput</th><th class="r">Operator latency p50 / p95</th><th class="r">Time to first token p50</th><th class="r">Reader latency p50 / p95</th><th class="r">Errors</th></tr></thead><tbody>
        ${sweep.map((r) => `<tr><td class="num">${r.n}</td><td class="r num">${fix(r.tok_s, 0)} tok/s</td><td class="r num">${fix(r.lat_p50_s, 1)} / ${fix(r.lat_p95_s, 1)} s</td><td class="r num">${r.ttft_p50_ms} ms</td><td class="r num">${r.reader_p50_ms} / ${r.reader_p95_ms} ms</td><td class="r num">${r.errors}</td></tr>`).join("")}
      </tbody></table></div>` : ""}
      <div class="src">Source: <code>${esc(P.source || "")}</code> · method in <code>${esc(P.doc || "")}</code></div>
    </div>` : "";

  const roles = T.roles || [];
  const budgetSec = budget.limit_b ? `
    <div class="section">
      <h2>Parameter budget</h2>
      <p class="lead">Every generative model the running system loads, by total parameters. The limit is ${budget.limit_b}B.</p>
      <div class="card"><div class="card-body">
        <div style="display:flex;align-items:baseline;gap:8px"><span class="num" style="font-size:20px;font-weight:600">${fix(budget.used_b, 1)}B</span><span class="muted">of ${budget.limit_b}B used</span></div>
        <div class="budget">${roles.filter((r) => r.params_b).map((r, i) => `<i style="width:${(r.params_b / budget.limit_b) * 100}%;background:${i ? "#0e9aa7" : "var(--accent)"}" title="${esc(r.who)} ${r.params_b}B"></i>`).join("")}</div>
      </div><table class="t"><thead><tr><th>Role</th><th>Model</th><th class="r">Parameters</th><th>Served</th><th>Does</th></tr></thead><tbody>
        ${roles.map((r) => `<tr><td><b>${esc(r.who)}</b></td><td>${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">${esc(r.model)}</a>` : esc(r.model)}</td><td class="r num">${r.params_b ? r.params_b + "B" : "–"}</td><td class="muted">${esc(r.served)}</td><td class="muted">${esc(r.does)}</td></tr>`).join("")}
      </tbody></table>${budget.note ? `<div class="card-body src" style="margin:0">${esc(budget.note)}</div>` : ""}</div>
    </div>` : "";

  root.innerHTML = `
    <div class="page-head"><h1>Model</h1><span class="sub">How the system performs, measured on held-out data</span><div class="right"><span class="muted small" id="model-at">Updated ${new Date(S.modelAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span><button class="btn sm" id="model-refresh">Refresh</button></div></div>
    <div class="page-body">
      <div class="kpis">
        ${kpi("Held-out pass rate", fin ? pct(fin.pass_rate, 0) : "–", base ? `baseline ${pct(base.pass_rate, 0)}` : "")}
        ${kpi("Held-out mean reward", fin ? fix(fin.mean_reward, 2) : "–", base ? `baseline ${fix(base.mean_reward, 2)}` : "")}
        ${kpi("Reader exact match", rd.sample ? pct(rd.sample.finetuned, 0) : "–", rd.opus_exact_match != null ? `Claude Opus 5.5 ${pct(rd.opus_exact_match, 0)}` : "")}
        ${kpi("Parameters", budget.used_b != null ? fix(budget.used_b, 1) + "B" : "–", budget.limit_b ? `of ${budget.limit_b}B allowed` : "")}
      </div>
      ${heldout}${reader}${serving}${budgetSec}
    </div>`;
  $("#model-refresh").onclick = () => renderModel(true);
}

// ------------------------------------------------------------------ boot
async function tick() {
  await pollStatus();
  await pollLive();
  if (S.tab === "inbox") await refreshThread();
  if (S.tab === "assistant") {
    const active = S.status?.active_run;
    if (active && active !== S.run && !["stopped", "error"].includes(S.status?.run_status)) attachRun(active);
    await pollRunView();
    renderChat();
  }
  if (S.tab === "model" && S.modelAt && Date.now() - S.modelAt > 60000) renderModel(true);
}
(async function boot() {
  await pollStatus();
  route();
  await tick();
  setInterval(tick, 2500);
})();
