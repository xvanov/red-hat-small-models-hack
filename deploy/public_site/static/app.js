"use strict";
// Public page script. Only reads /api/online, /api/results, /api/trust, /api/performance
// from this same origin. All data is rendered with textContent (never innerHTML).
(function () {
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function pct(x) { return Math.round(x * 100) + "%"; }
  function getJSON(path) {
    return fetch(path, { credentials: "omit" }).then(function (r) {
      if (!r.ok) throw new Error(path + " " + r.status);
      return r.json();
    });
  }

  function status() {
    var box = document.getElementById("status"), txt = document.getElementById("status-text");
    getJSON("/api/online").then(function (d) {
      box.dataset.state = d.online ? "up" : "down";
      txt.textContent = d.online ? "Assistant online" : "Assistant offline right now";
    }).catch(function () {
      box.dataset.state = "down";
      txt.textContent = "Assistant offline right now";
    });
  }

  function stat(v, k) {
    var s = el("div", "stat");
    s.appendChild(el("div", "v", v));
    s.appendChild(el("div", "k", k));
    return s;
  }

  function bar(label, value, cls, extra) {
    var row = el("div", "bar " + cls);
    row.appendChild(el("div", "lbl", label));
    var t = el("div", "track");
    var f = el("div", "fill");
    f.style.width = Math.max(1, Math.round(value * 100)) * 0.8 + "%";
    t.appendChild(f);
    t.appendChild(el("span", "val", pct(value) + (extra ? "  " + extra : "")));
    row.appendChild(t);
    return row;
  }

  function results() {
    Promise.all([
      getJSON("/api/results"),
      getJSON("/api/trust").catch(function () { return null; }),
      getJSON("/api/performance").catch(function () { return null; })
    ]).then(function (all) {
      var res = all[0], trust = all[1], perf = all[2];
      var cfgs = res.configs || [];
      var base = cfgs.find(function (c) { return c.kind === "baseline"; });
      var fin = cfgs.find(function (c) { return c.kind === "final"; });
      var ref = cfgs.find(function (c) { return c.kind === "reference"; });
      if (!base || !fin) return;

      var stats = document.getElementById("stats");
      stats.appendChild(stat(pct(fin.pass_rate), "conversations fully passed after tuning (was " + pct(base.pass_rate) + ")"));
      stats.appendChild(stat(fin.mean_reward.toFixed(2), "average score per conversation, 0 to 1 (was " + base.mean_reward.toFixed(2) + ")"));
      if (trust && trust.budget) {
        stats.appendChild(stat(trust.budget.used_b + "B", "model parameters in use, under the " + trust.budget.limit_b + "B limit"));
      }
      if (perf && perf.sweep && perf.sweep.length) {
        var top = perf.sweep.reduce(function (a, b) { return (b.tok_s > a.tok_s ? b : a); });
        var gpu = (perf.hardware && perf.hardware.gpu) || "one GPU";
        stats.appendChild(stat(Math.round(top.tok_s).toLocaleString("en-US") + " tok/s",
          "generated on one " + gpu + " with " + top.n + " conversations at once"));
      }

      var bars = document.getElementById("bars");
      bars.appendChild(bar("Lightning, starting setup", base.pass_rate, "base"));
      bars.appendChild(bar("Lightning, tuned (what runs this demo)", fin.pass_rate, "fin"));
      if (ref) bars.appendChild(bar("Claude Opus 5.5, same tools (reference only)", ref.pass_rate, "ref"));

      var note = "Starting setup: " + base.runs + " runs over " + base.tasks + " conversations. Tuned: "
        + fin.runs + " runs over " + fin.tasks + ". Tuning means a better prompt, code guards and the fine-tuned 0.6B reader; the big model itself is unchanged.";
      if (ref) note += " The Claude reference is a large cloud model, scored once on " + ref.tasks
        + " of the same conversations for comparison. It never runs in this system.";
      document.getElementById("bars-note").textContent = note;
      document.getElementById("results-src").textContent =
        "Numbers are read live from our evaluation results (protocol " + (res.version || "") + "). Full method in docs/results.md on GitHub.";
      document.getElementById("results").hidden = false;
    }).catch(function () { /* console down: keep the section hidden */ });
  }

  status();
  setInterval(status, 30000);
  results();
})();
