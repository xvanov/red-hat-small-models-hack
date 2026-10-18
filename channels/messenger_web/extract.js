// Page-side extractors for facebook.com/messages. Read-only: nothing here clicks, types or changes the page.
// Called as page.evaluate(SOURCE, {fn: "threads"|"thread"|"wall", S: selectors})
({fn, S}) => {
  const first = (sels, root) => {
    for (const s of sels) { try { const el = (root || document).querySelector(s); if (el) return el; } catch (e) {} }
    return null;
  };
  const all = (sels, root) => {
    for (const s of sels) {
      try { const els = Array.from((root || document).querySelectorAll(s)); if (els.length) return els; } catch (e) {}
    }
    return [];
  };
  const idRe = new RegExp(S.thread_id_re);
  const clean = (t) => (t || "").replace(/ /g, " ").replace(/[ \t]+/g, " ").trim();
  const sysRes = (S.system_text_patterns || []).map((p) => new RegExp(p, "i"));
  const isSystem = (t) => sysRes.some((r) => r.test(t));
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };

  if (fn === "wall") {
    const url = location.href;
    for (const u of S.login_wall_url) if (url.includes(u)) return {wall: true, reason: "url:" + u};
    for (const s of S.login_wall_dom) {
      try { const el = document.querySelector(s); if (el && visible(el)) return {wall: true, reason: "dom:" + s}; } catch (e) {}
    }
    const body = (document.body && document.body.innerText || "").slice(0, 4000).toLowerCase();
    for (const t of S.login_wall_text) if (body.includes(t.toLowerCase())) {
      // "Log in" text also appears in footers of logged-in pages; only count it when no thread link exists
      if (!all(S.thread_link).length) return {wall: true, reason: "text:" + t};
    }
    return {wall: false};
  }

  if (fn === "threads") {
    const root = first(S.thread_list_root) || document.body;
    let links = all(S.thread_link, root);
    if (!links.length) links = all(S.thread_link);
    const out = [];
    const seen = new Set();
    for (const a of links) {
      const m = (a.getAttribute("href") || "").match(idRe);
      if (!m || seen.has(m[1])) continue;
      // skip links inside the open conversation (e.g. profile links), keep the list rows
      if (a.closest("[role='main']")) continue;
      seen.add(m[1]);
      const lines = (a.innerText || "").split("\n").map(clean).filter((x) => x && x !== "·");
      let name = lines[0] || clean(a.getAttribute("aria-label")) || "";
      let listing = null;
      // Marketplace rows read "Buyer Name · Listing title"
      const parts = name.split(" · ");
      if (parts.length >= 2) { name = parts[0]; listing = parts.slice(1).join(" · "); }
      // the last line is the age of the last activity ("46m", "13h", "2d", "1w")
      let age = null;
      for (let i = lines.length - 1; i >= 0; i--) { if (/^(\d+\s?(m|h|d|w|y)|now|just now)$/i.test(lines[i])) { age = lines[i].replace(" ", ""); lines.splice(i, 1); break; } }
      const rowText = lines.slice(1).filter((x) => x !== "\u00b7" && x.length > 1).join(" | ");
      const unread = !!a.querySelector("[aria-label*='unread' i], [aria-label*='Mark as read' i]") ||
        /unread/i.test(a.getAttribute("aria-label") || "");
      out.push({thread_id: m[1], name, listing_title: listing, marketplace: listing !== null || /marketplace/i.test(a.innerText),
                snippet: rowText.slice(0, 300), unread, age, href: (a.getAttribute("href") || "").split("?")[0], e2ee: /e2ee/.test(a.getAttribute("href") || "")});
    }
    return out;
  }

  if (fn === "thread") {
    const m = location.href.match(idRe);
    const root = first(S.conversation_root);
    if (!root) return {thread_id: m ? m[1] : null, messages: [], error: "no conversation root"};
    const rr = root.getBoundingClientRect();
    const mid = rr.left + rr.width / 2;
    const rows = all(S.message_row, root);
    const outMarkers = S.outgoing_markers || [];
    const msgs = [];
    for (const row of rows) {
      const rowText = row.innerText || "";
      let texts = all(S.message_text, row).filter((el) => !el.parentElement.closest("div[dir='auto']") || el.parentElement.closest("div[dir='auto']") === el);
      // drop nested duplicates: keep outermost dir=auto blocks only
      texts = texts.filter((el) => !texts.some((o) => o !== el && o.contains(el)));
      for (const el of texts) {
        if (!visible(el)) continue;
        const t = clean(el.innerText);
        if (!t || isSystem(t)) continue;
        const r = el.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        let dir = null;
        // 1) accessibility label in the row ("You sent")
        const hidden = Array.from(row.querySelectorAll("h4, h5, h6, span")).map((x) => clean(x.textContent));
        if (outMarkers.some((mk) => hidden.includes(mk))) dir = "out";
        // 2) geometry: own messages are right-aligned in the conversation pane
        if (!dir) dir = cx > mid ? "out" : "in";
        // a centered narrow line is a separator (date, notice), not a bubble
        if (Math.abs(cx - mid) < rr.width * 0.04 && r.width < rr.width * 0.5) continue;
        const msgId = row.getAttribute("data-message-id") ||
          (row.querySelector("[data-message-id]") || {getAttribute: () => null}).getAttribute("data-message-id") ||
          (row.closest("[data-message-id]") || {getAttribute: () => null}).getAttribute("data-message-id");
        msgs.push({dir, text: t, mid: msgId});
      }
    }
    const header = first(["[role='main'] h2", "[role='main'] h1"]);
    return {thread_id: m ? m[1] : null, header: header ? clean(header.innerText) : null, messages: msgs};
  }
  return null;
}
