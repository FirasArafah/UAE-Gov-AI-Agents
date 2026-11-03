import { AGENTS, agentColor, agentInitials, agentName } from "./agents.js";

/** Create an element: h("div", { class: "x", text: "hi" }, child1, child2). */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k.startsWith("--")) el.style.setProperty(k, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const escapeHtml = (s) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const WARNING_MARK = "\n\n---\nتنبيه";
const SOURCES_MARK = "\n\n---\nالمصادر المسترجعة";
const NOT_COVERED = "Not explicitly covered in the official sources provided";

/**
 * Split an agent answer into its parts. Answers are bilingual
 * ("النسخة العربية:" ... "English version:" ...), may end with a retrieved-sources
 * footer and with a verification warning added by the backend.
 */
export function parseAnswer(content = "") {
  let body = content;
  let warning = [];
  let sources = [];

  const w = body.indexOf(WARNING_MARK);
  if (w >= 0) {
    warning = body
      .slice(w)
      .split("\n")
      .filter((l) => l.startsWith("- "))
      .map((l) => l.slice(2));
    body = body.slice(0, w);
  }
  const s = body.indexOf(SOURCES_MARK);
  if (s >= 0) {
    sources = body
      .slice(s)
      .split("\n")
      .filter((l) => /^\[\d+\]/.test(l))
      .map((l) => {
        const [head, ...rest] = l.split(" | ");
        const m = head.match(/^\[(\d+)\]\s*(.*)$/);
        return { n: m?.[1], title: m?.[2] || head, detail: rest.join(" · ") };
      });
    body = body.slice(0, s);
  }

  // English-only text before the Arabic heading is reasoning that escaped its tags.
  const arHeading = body.indexOf("النسخة العربية");
  if (arHeading > 0 && !/[؀-ۿ]/.test(body.slice(0, arHeading))) body = body.slice(arHeading);

  let ar = "";
  let en = body.trim();
  const split = body.split(/English version\s*:/i);
  if (split.length >= 2) {
    ar = split[0].replace(/النسخة العربية\s*:/, "").trim();
    en = split.slice(1).join("English version:").trim();
  } else if (/[؀-ۿ]/.test(body) && !/[a-z]{4,}/i.test(body.replace(/\[[^\]]*\]/g, ""))) {
    ar = body.replace(/النسخة العربية\s*:/, "").trim();
    en = "";
  }
  return { ar, en, sources, warning, notCovered: content.includes(NOT_COVERED) };
}

/** Light formatting: paragraphs, bullet lists, **bold** and [n] citation markers. */
export function formatProse(text) {
  const blocks = escapeHtml(text.trim()).split(/\n{2,}/);
  return blocks
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
        return "<ul>" + lines.map((l) => `<li>${inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>`).join("") + "</ul>";
      }
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    })
    .join("");
}

function inline(s) {
  return s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(\d+(?:\s*[,،]\s*\d+)*)\]/g, (_, n) => `<span class="cite" title="Retrieved source ${n}">${n}</span>`);
}

let preferredLang = "en";
try {
  preferredLang = localStorage.getItem("answerLang") || "en";
} catch {
  /* storage unavailable */
}

/**
 * Render one agent turn.
 * msg: { agent_slug, agent_name, role, content, thinking, references, is_synthesis,
 *        responding_to, error, meta }
 */
export function renderMessage(msg) {
  const slug = msg.agent_slug;
  const name = agentName(slug, msg.agent_name);
  const color = agentColor(slug);
  const el = h("article", { class: "msg" + (msg.is_synthesis ? " synthesis" : ""), "--agent": color });

  if (msg.is_synthesis) {
    const from = (msg.responding_to || []).map((s) => agentName(s)).join(", ");
    el.append(
      h("div", { class: "synth-banner" },
        "Coordinator synthesis",
        from ? h("small", { text: `reconciles the assessments of ${from}` }) : null,
      ),
    );
  }

  if (msg.error) {
    el.append(
      h("div", { class: "msg-head" }, h("span", { class: "avatar", text: agentInitials(slug, name) }), h("div", { class: "who" }, h("b", { text: name }))),
      h("div", { class: "msg-body" }, h("div", { class: "notice danger", text: "This agent could not respond: " + msg.error })),
    );
    return el;
  }

  const parsed = parseAnswer(msg.content || "");
  const refs = msg.references?.length ? msg.references : null;
  const sourceCount = refs ? refs.length : parsed.sources.length;

  const subtitle = [];
  const mandate = AGENTS[slug]?.mandate || msg.role;
  if (mandate) subtitle.push(mandate);
  if (msg.responding_to?.length && !msg.is_synthesis) subtitle.push("responding to " + msg.responding_to.map((s) => agentName(s)).join(", "));
  if (msg.meta) subtitle.push(msg.meta);

  const head = h("div", { class: "msg-head" },
    h("span", { class: "avatar", text: agentInitials(slug, name) }),
    h("div", { class: "who" }, h("b", { text: name }), subtitle.length ? h("small", { text: subtitle.join(" · ") }) : null),
  );
  const tags = h("div", { class: "tags" });
  if (sourceCount) tags.append(h("span", { class: "tag accent", text: `${sourceCount} sources` }));
  if (parsed.warning.length) tags.append(h("span", { class: "tag warn", text: "Verification flagged" }));
  if (parsed.notCovered) tags.append(h("span", { class: "tag", text: "Not covered by sources" }));
  head.append(tags);

  const body = h("div", { class: "msg-body" });
  const prose = h("div", { class: "prose" });
  const hasBoth = parsed.ar && parsed.en;
  let lang = hasBoth ? preferredLang : parsed.en ? "en" : "ar";

  function show() {
    const text = lang === "ar" ? parsed.ar : parsed.en;
    prose.dir = lang === "ar" ? "rtl" : "ltr";
    prose.lang = lang;
    prose.innerHTML = formatProse(text || "(empty)");
    tabs?.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.lang === lang)));
  }

  let tabs = null;
  if (hasBoth) {
    tabs = h("div", { class: "lang-tabs", role: "tablist", "aria-label": "Answer language" },
      h("button", { type: "button", role: "tab", "data-lang": "en", text: "English" }),
      h("button", { type: "button", role: "tab", "data-lang": "ar", text: "العربية", class: "ar" }),
    );
    tabs.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      lang = preferredLang = b.dataset.lang;
      try { localStorage.setItem("answerLang", lang); } catch { /* ignore */ }
      show();
    });
    head.append(tabs);
  }
  show();
  body.append(prose);
  el.append(head, body);

  const foot = h("div", { class: "msg-foot" });
  if (parsed.warning.length) {
    foot.append(
      h("div", { class: "verify notice warn", style: { marginTop: "12px" } },
        h("div", {},
          h("b", { text: "Automatic citation check flagged this answer" }),
          h("ul", {}, parsed.warning.map((w) => h("li", { text: w }))),
        ),
      ),
    );
  }
  if (sourceCount) {
    const list = h("ol", { class: "sources" });
    const items = refs
      ? refs.map((r, i) => ({ n: i + 1, title: r.title, detail: [r.section, r.page ? `p. ${r.page}` : null, r.language?.toUpperCase()].filter(Boolean).join(" · ") }))
      : parsed.sources;
    for (const s of items) {
      list.append(h("li", {}, h("span", { class: "n", text: `[${s.n}]` }), h("span", {}, s.title, s.detail ? h("small", { text: " — " + s.detail }) : null)));
    }
    foot.append(h("details", {}, h("summary", { text: `Retrieved sources (${sourceCount})` }), list));
  }
  if (msg.thinking) {
    foot.append(h("details", {}, h("summary", { text: "Reasoning trace" }), h("pre", { class: "trace", text: msg.thinking })));
  }
  if (foot.childNodes.length) el.append(foot);
  return el;
}

export function renderPending(slug, label) {
  const started = Date.now();
  const time = h("small", { text: "0s" });
  const el = h("div", { class: "pending", "--agent": agentColor(slug), role: "status" },
    h("span", { class: "pulse" }),
    h("div", { class: "grow" },
      h("b", { text: label || `${agentName(slug)} is assessing…` }),
      h("div", { class: "skeleton", style: { width: "70%" } }),
    ),
    time,
  );
  const timer = setInterval(() => {
    if (!el.isConnected) return clearInterval(timer);
    const s = Math.round((Date.now() - started) / 1000);
    time.textContent = s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
  }, 1000);
  return el;
}

const GAP_TYPE_LABEL = {
  policy: "Policy", legal: "Legislative", standards: "Standards",
  implementation: "Implementation", coordination: "Coordination",
};

export function renderGap(gap, index) {
  const [titlePart, ...rest] = gap.description.split(/:\s(.+)/s);
  const hasTitle = rest.length > 0 && titlePart.length < 120;
  const title = hasTitle ? titlePart : `Gap ${index + 1}`;
  let description = hasTitle ? rest.join("") : gap.description;
  let evidence = "";
  const ev = description.split(/\nEvidence:\s*/);
  if (ev.length > 1) [description, evidence] = ev;

  return h("article", { class: "gap", "data-sev": gap.severity },
    h("div", { class: "tags" },
      h("span", { class: "sev", text: gap.severity }),
      h("span", { class: "tag", text: GAP_TYPE_LABEL[gap.gap_type] || gap.gap_type }),
      h("span", { class: "tag", text: gap.affected_domain.replace(/_/g, " ") }),
    ),
    h("h3", { text: title }),
    h("p", { class: "prose", text: description }),
    evidence ? h("small", { class: "muted", text: "Surfaced by: " + evidence }) : null,
    gap.global_best_practice
      ? h("div", { class: "bp" }, h("b", { text: "Global best practice" }), gap.global_best_practice)
      : null,
    gap.global_references?.length
      ? h("div", { class: "refs" },
          gap.global_references.map((r) =>
            h("span", { text: "↳ " + [r.title, r.section, r.page ? `p. ${r.page}` : null].filter(Boolean).join(" · ") }),
          ),
        )
      : null,
  );
}

export function timeAgo(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
