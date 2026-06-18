/* The Forge — shared interactivity across all learning-module pages */
(function () {
  "use strict";
  var $ = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* whole-curriculum manifest — keep in sync with the per-page data-done keys */
  var MANIFEST = ["home", "theory", "practice", "labs", "quiz"];
  var KEY = "forge-done-v2";

  /* ---- top reading-progress bar ---- */
  var bar = $("#progress");
  if (bar) {
    var onScroll = function () {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max * 100) : 0) + "%";
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  /* ---- completion ring (shared across pages via localStorage) ---- */
  var done = {};
  try { done = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { done = {}; }
  var ring = $("#ring"), pct = $("#pct"), CIRC = 119.4;
  function paintRing() {
    var n = 0;
    MANIFEST.forEach(function (k) { if (done[k]) n++; });
    var frac = MANIFEST.length ? n / MANIFEST.length : 0;
    if (ring) ring.style.strokeDashoffset = (CIRC * (1 - frac)).toFixed(1);
    if (pct) pct.textContent = Math.round(frac * 100) + "%";
  }
  $$("input[data-done]").forEach(function (b) {
    if (done[b.getAttribute("data-done")]) b.checked = true;
    b.addEventListener("change", function () {
      done[b.getAttribute("data-done")] = b.checked;
      try { localStorage.setItem(KEY, JSON.stringify(done)); } catch (e) {}
      paintRing();
    });
  });
  paintRing();

  /* ---- in-page tabs ---- */
  $$("[data-tabs]").forEach(function (group) {
    var btns = $$(".tabbar button", group);
    btns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-tab");
        btns.forEach(function (b) { b.classList.toggle("active", b === btn); });
        $$(".tabpanel", group).forEach(function (p) { p.classList.toggle("active", p.id === id); });
      });
    });
  });

  /* ---- copy buttons ---- */
  $$(".code .copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var pre = $("pre", btn.closest(".code"));
      if (!pre) return;
      var txt = pre.textContent;
      var ok = function () { var o = btn.textContent; btn.textContent = "copied \u2713"; setTimeout(function () { btn.textContent = o; }, 1300); };
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(txt).then(ok, ok); }
      else { ok(); }
    });
  });

  /* ---- loop simulator (only if present) ---- */
  var sim = $("#sim");
  if (sim) {
    var events = [
      { turn: 1, node: 0, t: "perceive \u00b7 failing test \u2192 test_checkout: AssertionError total != 42" },
      { turn: 1, node: 1, t: "decide   \u00b7 hypothesis: tax not applied. plan: locate total(), patch it" },
      { turn: 1, node: 2, t: "act      \u00b7 grep_code(\"def total\") \u2192 cart.py:88" },
      { turn: 1, node: 3, t: "observe  \u00b7 read cart.py:80-100 \u2014 the tax line is missing" },
      { turn: 2, node: 1, t: "decide   \u00b7 fix: add tax to subtotal before return" },
      { turn: 2, node: 2, t: "act      \u00b7 edit_file(cart.py) \u2192 run_tests" },
      { turn: 2, node: 3, t: "observe  \u00b7 1 failed \u2192 0 failed \u2713  goal verified" },
      { turn: 2, node: -1, t: "\u2713 goal met in 2 turns \u2014 the agent stops. (no fixed script told it to.)" }
    ];
    var idx = 0;
    var nodes = $$("#sim .node"), logEl = $("#simlog"), turnEl = $("#simTurn");
    var stepBtn = $("#simStep"), resetBtn = $("#simReset");
    var clearNodes = function () { nodes.forEach(function (n) { n.classList.remove("on"); }); };
    var step = function () {
      if (idx >= events.length) return;
      if (idx === 0) logEl.innerHTML = "";
      var e = events[idx++];
      clearNodes();
      nodes.forEach(function (n) {
        var k = parseInt(n.getAttribute("data-node"), 10);
        if (e.node >= 0 && k === e.node) n.classList.add("on");
        if (e.node >= 0 && k < e.node) n.classList.add("done");
      });
      turnEl.textContent = e.turn;
      var ln = document.createElement("div");
      ln.className = "ln"; ln.textContent = e.t;
      logEl.appendChild(ln);
      logEl.scrollTop = logEl.scrollHeight;
      if (idx >= events.length) {
        stepBtn.disabled = true; stepBtn.textContent = "\u2713 complete";
        clearNodes(); nodes.forEach(function (n) { n.classList.add("done"); });
      }
    };
    var reset = function () {
      idx = 0; stepBtn.disabled = false; stepBtn.textContent = "\u25b6 Step the loop";
      turnEl.textContent = "0"; clearNodes(); nodes.forEach(function (n) { n.classList.remove("done"); });
      logEl.innerHTML = "// press \u201cStep the loop\u201d to watch an agent fix a failing test\u2026";
    };
    stepBtn.addEventListener("click", step);
    resetBtn.addEventListener("click", reset);
  }

  /* ---- quiz (only if present) ---- */
  var quizEl = $("#quiz");
  if (quizEl) {
    var Q = [
      { q: "What single property most separates an agent from a prompt chain?",
        o: ["It uses a larger model", "It chooses its next action from the current state, and adapts", "It always writes files", "It runs faster"],
        a: 1, e: "Goal-directed autonomy + feedback: an agent decides and re-plans; a chain runs fixed steps." },
      { q: "In AgentForge, why does run_tool_loop iterate over many turns instead of one call?",
        o: ["To bypass rate limits", "So a model can write \u2192 observe results \u2192 continue a large job across calls", "To save money", "Because Anthropic requires it"],
        a: 1, e: "The loop lets the model complete work it can't finish in a single response \u2014 the core of agency." },
      { q: "exec_tools (run_tests/run_lint) only ever runs\u2026",
        o: ["any shell command the model emits", "the profile-configured verify/lint command", "a hard-coded pytest call", "npm test"],
        a: 1, e: "Security stance: execution is fixed by the project profile, never an arbitrary model-supplied string." },
      { q: "What stops --adaptive re-planning from looping forever?",
        o: ["A timeout only", "A replan budget plus a hard phase cap", "The reviewer", "Nothing \u2014 it can loop"],
        a: 1, e: "Bounded autonomy: every adaptive move spends from a budget and is capped \u2014 the key to shipping it." },
      { q: "When the running tool-loop context exceeds the budget, _compact_messages\u2026",
        o: ["summarizes with another LLM call", "deletes the system prompt", "drops the oldest complete tool exchanges (a sliding window)", "crashes safely"],
        a: 2, e: "It preserves tool_use/tool_result adjacency and the seed brief while trimming oldest pairs \u2014 graceful degradation." },
      { q: "Why give the Reviewer a diff-only view during adaptive revisions?",
        o: ["To hide code from it", "Re-reading whole files is costly and dilutes focus on the actual change", "It can't read files", "To skip review"],
        a: 1, e: "core/diffs.unified_diff + Lead snapshots focus the Reviewer on what changed on each revision attempt." },
      { q: "Deterministic tests use faked LLM calls. What can they NOT catch \u2014 and what fixes it?",
        o: ["Nothing; they catch everything", "A silently degraded prompt \u2014 fixed by an LLM-as-a-Judge scoring artifacts against a rubric", "Syntax errors \u2014 fixed by a linter", "Slow tests \u2014 fixed by caching"],
        a: 1, e: "The evaluation disconnect: structurally valid output can still be worse. evals/judge.py rubric-scores quality with a small model (run_evals.py --judge)." }
    ];
    var scoreEl = $("#score"), answered = 0, correct = 0;
    Q.forEach(function (item, qi) {
      var card = document.createElement("div"); card.className = "q";
      var h = document.createElement("div"); h.className = "qt"; h.textContent = (qi + 1) + ". " + item.q; card.appendChild(h);
      item.o.forEach(function (opt, oi) {
        var b = document.createElement("button"); b.className = "opt"; b.textContent = opt;
        b.addEventListener("click", function () {
          if (card.getAttribute("data-done")) return;
          card.setAttribute("data-done", "1"); answered++;
          if (oi === item.a) { b.classList.add("correct"); correct++; }
          else { b.classList.add("wrong"); $$(".opt", card)[item.a].classList.add("correct"); }
          var exp = card.querySelector(".exp"); if (exp) exp.classList.add("show");
          if (answered === Q.length) {
            scoreEl.textContent = "Score: " + correct + " / " + Q.length +
              (correct === Q.length ? "  \u2014 forged. \ud83d\udd25" : "  \u2014 revisit the modules you missed.");
          }
        });
        card.appendChild(b);
      });
      var exp = document.createElement("div"); exp.className = "exp"; exp.textContent = item.e; card.appendChild(exp);
      quizEl.appendChild(card);
    });
  }
})();
