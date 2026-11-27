/* Runs axe-core, IBM Equal Access and HTML_CodeSniffer on the SAME DOM in the SAME page and returns
 * raw findings with one shared element identity (xpath + css + snippet), so findings from different
 * engines can be matched exactly. Bundles are injected beforehand by the scanner (pinned, hashed).
 * Each engine runs in its own try/catch: one engine failing never loses the others' results. */
(() => {
  const MAX_HTML = 300;

  const xpathOf = (el) => {
    const parts = [];
    for (; el && el.nodeType === 1; el = el.parentElement) {
      let i = 1;
      for (let s = el.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === el.tagName) i++;
      parts.unshift(`${el.tagName.toLowerCase()}[${i}]`);
    }
    return "/" + parts.join("/");
  };
  const cssOf = (el) => {
    const parts = [];
    for (; el && el.nodeType === 1 && el !== document.documentElement; el = el.parentElement) {
      if (el.id && /^[A-Za-z][\w-]*$/.test(el.id) && document.querySelectorAll(`#${el.id}`).length === 1) {
        parts.unshift(`#${el.id}`);
        return parts.join(" > ");
      }
      let n = 1;
      for (let s = el.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === el.tagName) n++;
      parts.unshift(`${el.tagName.toLowerCase()}:nth-of-type(${n})`);
    }
    return ["html", ...parts].join(" > ");
  };
  const identity = (el) => {
    if (!el || el.nodeType !== 1) el = document.documentElement;
    const r = el.getBoundingClientRect();
    let html = "";
    try { html = el.cloneNode(false).outerHTML; } catch (_) { html = `<${el.tagName.toLowerCase()}>`; }
    return {
      xpath: xpathOf(el), css: cssOf(el), tag: el.tagName.toLowerCase(), html: html.slice(0, MAX_HTML),
      rect: { x: Math.round(r.x + scrollX), y: Math.round(r.y + scrollY), w: Math.round(r.width), h: Math.round(r.height) },
    };
  };
  const byXpath = (xp) => {
    try { return document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue; } catch (_) { return null; }
  };
  const scOfAxeTags = (tags) =>
    tags.filter((t) => /^wcag\d{3,}$/.test(t)).map((t) => `${t[4]}.${t[5]}.${t.slice(6)}`);

  const runAxe = async () => {
    const r = await axe.run(document, { resultTypes: ["violations", "incomplete"], elementRef: true });
    const out = [];
    const push = (kind) => (rule) =>
      rule.nodes.forEach((n) =>
        out.push({
          engine: "axe", rule_id: rule.id, kind, impact: n.impact || rule.impact, sc: scOfAxeTags(rule.tags),
          best_practice: rule.tags.includes("best-practice"), message: (n.failureSummary || rule.help || "").slice(0, 500),
          help: rule.help, help_url: rule.helpUrl, element: identity(n.element),
        }),
      );
    r.violations.forEach(push("violation"));
    r.incomplete.forEach(push("needs_review"));
    return out;
  };

  const runIbm = async () => {
    const checker = new ace.Checker();
    const eng = checker.engine;
    const scCache = {};
    const scOf = (id) => {
      if (!(id in scCache)) {
        let nums = [];
        try {
          const rule = eng.getRule(id);
          (rule.rulesets || []).filter((s) => [].concat(s.id).includes("IBM_Accessibility")).forEach((s) => (nums = nums.concat(s.num)));
        } catch (_) { /* unknown rule */ }
        scCache[id] = [...new Set(nums.filter((n) => /^\d\.\d\.\d+$/.test(n)))];
      }
      return scCache[id];
    };
    const report = await checker.check(document, ["IBM_Accessibility"]);
    const out = [];
    for (const r of report.results) {
      const [level, outcome] = r.value;
      let kind;
      if (outcome === "FAIL") kind = level === "VIOLATION" ? "violation" : "best_practice";
      else if (outcome === "POTENTIAL" || outcome === "MANUAL") kind = "needs_review";
      else continue; // PASS and INFORMATION are not findings
      const el = byXpath(r.path && r.path.dom);
      out.push({
        engine: "ibm", rule_id: r.ruleId, kind, impact: level === "VIOLATION" ? "serious" : "minor", sc: scOf(r.ruleId),
        best_practice: kind === "best_practice", message: (r.message || "").slice(0, 500), help: r.reasonId, help_url: null,
        element: el ? identity(el) : { ...identity(document.documentElement), xpath: (r.path && r.path.dom) || "/", html: (r.snippet || "").slice(0, MAX_HTML) },
      });
    }
    return out;
  };

  const runHtmlcs = () =>
    new Promise((resolve) => {
      HTMLCS.process("WCAG2AA", document, () => {
        const out = [];
        for (const m of HTMLCS.getMessages()) {
          if (m.type === 3) continue; // NOTICE: informational
          const code = m.code.split(".");
          const num = (code[3] || "").split("_"); // e.g. 1_1_1
          const sc = num.length === 3 ? [num.join(".")] : [];
          out.push({
            engine: "htmlcs", rule_id: code.slice(4).join("."), kind: m.type === 1 ? "violation" : "needs_review",
            impact: m.type === 1 ? "serious" : "moderate", sc, best_practice: false, message: (m.msg || "").slice(0, 500),
            help: m.code, help_url: null, element: identity(m.element),
          });
        }
        resolve(out);
      });
    });

  window.__a11yScan = async (enabled) => {
    const result = { findings: [], engines: {}, title: document.title, lang: document.documentElement.lang || null };
    const engines = { axe: runAxe, ibm: runIbm, htmlcs: runHtmlcs };
    for (const [id, fn] of Object.entries(engines)) {
      if (enabled && !enabled.includes(id)) continue;
      const t0 = performance.now();
      try {
        const f = await fn();
        result.findings.push(...f);
        result.engines[id] = { ok: true, count: f.length, ms: Math.round(performance.now() - t0) };
      } catch (e) {
        result.engines[id] = { ok: false, error: String(e && e.message ? e.message : e).slice(0, 200), ms: Math.round(performance.now() - t0) };
      }
    }
    return result;
  };
})();
