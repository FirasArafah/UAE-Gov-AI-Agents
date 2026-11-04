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
 * A finished answer without card chrome, for conversation views: language tabs,
 * prose with citation markers, verification warnings and the sources it relied on.
 */
export function renderAnswer(content, references = [], { sourcesLabel = "Sources" } = {}) {
  const parsed = parseAnswer(content || "");
  const el = h("div", { class: "answer" });
  const prose = h("div", { class: "prose" });
  const hasBoth = parsed.ar && parsed.en;
  let lang = hasBoth ? preferredLang : parsed.en ? "en" : "ar";
  let tabs = null;

  const show = () => {
    const text = (lang === "ar" ? parsed.ar : parsed.en) || content || "";
    prose.dir = lang === "ar" ? "rtl" : "ltr";
    prose.lang = lang;
    prose.innerHTML = formatProse(text || "(empty)");
    tabs?.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.lang === lang)));
  };
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
    el.append(h("div", { class: "answer-tools" }, tabs));
  }
  show();
  el.append(prose);

  if (parsed.warning.length) {
    el.append(
      h("div", { class: "notice warn answer-note" },
        h("div", {}, h("b", { text: "Citation check flagged this answer" }), h("ul", {}, parsed.warning.map((w) => h("li", { text: w })))),
      ),
    );
  }
  const items = references?.length
    ? references.map((r, i) => ({ n: i + 1, title: r.title, detail: [r.section, r.page ? `p. ${r.page}` : null].filter(Boolean).join(" · ") }))
    : parsed.sources;
  if (items.length) {
    el.append(
      h("details", { class: "answer-sources" },
        h("summary", { text: `${sourcesLabel} (${items.length})` }),
        h("ol", { class: "sources" }, items.map((s) => h("li", {}, h("span", { class: "n", text: `[${s.n}]` }), h("span", {}, s.title, s.detail ? h("small", { text: " — " + s.detail }) : null)))),
      ),
    );
  }
  return el;
}
