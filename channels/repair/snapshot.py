"""Capture a compact, model-readable picture of the page: the interactive elements and the
repeated data-carrying elements, each with a selector already computed to be unique among
visible elements, plus a truncated ARIA snapshot for context."""
from __future__ import annotations

SNAPSHOT_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) &&
                    getComputedStyle(el).visibility !== 'hidden';
  const q = s => { try { return Array.from(document.querySelectorAll(s)); } catch(e) { return []; } };
  const visCount = s => q(s).filter(vis).length;
  const attCount = s => q(s).length;
  const esc = v => v.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const labelOf = el => {
    if (el.labels && el.labels.length) return el.labels[0].innerText.trim();
    const l = el.closest('label'); if (l) return l.innerText.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) { const t = document.getElementById(by); if (t) return t.innerText.trim(); }
    const prev = el.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return prev.innerText.trim();
    return '';
  };
  const uniq = (el, isFile) => {
    const count = isFile ? attCount : visCount;
    const tag = el.tagName.toLowerCase();
    const cands = [];
    if (el.id) cands.push('#' + CSS.escape(el.id));
    const tid = el.getAttribute('data-testid'); if (tid) cands.push(`[data-testid="${esc(tid)}"]`);
    const nm = el.getAttribute('name');
    const val = el.getAttribute('value');
    if (nm && val && (el.type === 'radio' || tag === 'button')) cands.push(`${tag}[name="${esc(nm)}"][value="${esc(val)}"]`);
    if (nm) cands.push(`${tag}[name="${esc(nm)}"]`);
    const al = el.getAttribute('aria-label');
    if (al) { cands.push(`${tag}[aria-label="${esc(al)}"]`); cands.push(`[aria-label="${esc(al)}"]`); }
    if (isFile) cands.push('input[type=file]');
    const role = el.getAttribute('role') || (tag === 'button' ? 'button' : '');
    for (const c of cands) if (count(c) === 1) return c;
    const txt = (el.innerText || '').trim();
    if (role && txt && txt.length < 40) return `role=${role}[name="${esc(txt)}"]`;
    return null;
  };
  const out = [];
  const seen = new Set();
  const nodes = q('input, textarea, select, button, a[href], [role], [contenteditable=true], [data-testid]');
  for (const el of nodes) {
    if (seen.has(el)) continue; seen.add(el);
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (type === 'hidden') continue;
    const isFile = tag === 'input' && type === 'file';
    if (!isFile && !vis(el)) continue;
    const sel = uniq(el, isFile);
    if (!sel) continue;
    out.push({i: out.length, tag, type, id: el.id || '', name: el.getAttribute('name') || '',
      role: el.getAttribute('role') || '', aria: el.getAttribute('aria-label') || '',
      testid: el.getAttribute('data-testid') || '', placeholder: el.getAttribute('placeholder') || '',
      value: (tag === 'button' || type === 'radio') ? (el.getAttribute('value') || '') : '',
      label: labelOf(el).slice(0, 60), text: (el.innerText || '').trim().slice(0, 60), selector: sel});
  }
  // repeated elements carrying data-* attributes (inbox rows, chat messages), grouped by tag +
  // first data attribute; the selector keeps only the first class every member shares
  const groups = {};
  for (const el of q('body *')) {
    if (!vis(el)) continue;
    const data = Array.from(el.attributes).filter(a => a.name.startsWith('data-') && a.name !== 'data-testid');
    if (!data.length) continue;
    const key = el.tagName.toLowerCase() + '[' + data[0].name + ']';
    (groups[key] = groups[key] || []).push(el);
  }
  const rows = [];
  for (const [key, els] of Object.entries(groups)) {
    const tag = key.split('[')[0], attr = key.slice(tag.length);
    let common = Array.from(els[0].classList);
    for (const e of els) common = common.filter(c => e.classList.contains(c));
    common = common.slice(0, 1);  // base class only: modifiers like 'them'/'msg-in' vary per row
    const sel = tag + common.map(c => '.' + CSS.escape(c)).join('') + attr;
    const attrs = {};
    for (const a of els[0].attributes) if (a.name.startsWith('data-'))
      attrs[a.name] = Array.from(new Set(els.map(e => e.getAttribute(a.name)))).slice(0, 4);
    const classes = Array.from(new Set(els.flatMap(e => Array.from(e.classList)))).join(' ');
    rows.push({i: out.length + rows.length, selector: sel, count: els.length, classes,
               attrs, text: (els[0].innerText || '').trim().slice(0, 60)});
  }
  return {url: location.href, title: document.title, elements: out, repeated: rows};
}
"""


FINGERPRINT_JS = r"""
() => {
  const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const heads = Array.from(document.querySelectorAll('h1,h2,h3,legend,[role=heading]')).filter(vis).map(e => e.innerText.trim());
  const ctrls = Array.from(document.querySelectorAll('input,select,textarea,button,[role=button]')).filter(vis).length;
  return location.href + '|' + heads.join('/') + '|' + ctrls;
}
"""


def fingerprint(page) -> str:
    try:
        return page.evaluate(FINGERPRINT_JS)
    except Exception:
        return ""


def capture(page, aria_chars: int = 2500) -> dict:
    snap = page.evaluate(SNAPSHOT_JS)
    try:
        aria = page.locator("body").aria_snapshot()
    except Exception:
        aria = ""
    snap["aria"] = aria[:aria_chars]
    return snap


def render_for_prompt(snap: dict, rows: bool) -> str:
    lines = []
    if rows:
        for r in snap["repeated"]:
            lines.append(f"[{r['i']}] {r['selector']} x{r['count']} attrs={r['attrs']} text={r['text']!r}")
    else:
        for e in snap["elements"]:
            bits = [f"[{e['i']}] <{e['tag']}" + (f" type={e['type']}" if e['type'] else "") + ">"]
            for k in ("id", "name", "role", "aria", "testid", "placeholder", "value", "label", "text"):
                if e[k]:
                    bits.append(f"{k}={e[k]!r}")
            lines.append(" ".join(bits))
    return "\n".join(lines)
