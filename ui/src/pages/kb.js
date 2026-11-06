import { api } from "../js/api.js";
import { addStrings, num, t } from "../js/i18n.js";
import { h, textDir } from "../js/render.js";

const DOMAINS = ["government_services", "data_protection", "ai_governance", "telecom", "national_policy", "global_practice", "cross_domain"];
const TYPES = ["law", "regulation", "strategy", "guideline", "standard", "report", "use_case", "other"];

addStrings({
  en: {
    "kb.title": "Knowledge base",
    "kb.subtitle": "National legislation and strategies, with the international references used for comparison.",
    "kb.stat.documents": "Documents",
    "kb.stat.chunks": "Indexed passages",
    "kb.stat.national": "National",
    "kb.stat.international": "International",
    "kb.search.title": "Search the knowledge base",
    "kb.search.placeholder": "e.g. right to object to automated decisions",
    "kb.search.aria": "Search query",
    "kb.search.button": "Search",
    "kb.search.allDomains": "All domains",
    "kb.search.none": "No passage matches this search.",
    "kb.search.failed": "The search failed: {error}",
    "kb.search.relevance": "Relevance",
    "kb.docs.title": "Documents",
    "kb.docs.filter": "Filter documents",
    "kb.docs.all": "All",
    "kb.docs.none": "No document matches these filters.",
    "kb.docs.pages": "{n} pages",
    "kb.docs.passages": "{n} passages",
    "kb.docs.source": "Official source",
    "kb.group.national": "United Arab Emirates",
    "kb.group.international": "International references",
    "kb.lang.ar": "Arabic",
    "kb.lang.en": "English",
    "kb.page": "p. {n}",
    "domain.government_services": "Government services",
    "domain.data_protection": "Data protection",
    "domain.ai_governance": "AI governance",
    "domain.telecom": "Telecom and cybersecurity",
    "domain.national_policy": "National policy",
    "domain.global_practice": "Global practice",
    "domain.cross_domain": "Cross-domain",
    "type.law": "Law",
    "type.regulation": "Regulation",
    "type.strategy": "Strategy",
    "type.guideline": "Guideline",
    "type.standard": "Standard",
    "type.report": "Report",
    "type.use_case": "Use case",
    "type.other": "Other",
  },
  ar: {
    "kb.title": "قاعدة المعرفة",
    "kb.subtitle": "التشريعات والاستراتيجيات الوطنية، مع المراجع الدولية المستخدمة للمقارنة.",
    "kb.stat.documents": "الوثائق",
    "kb.stat.chunks": "المقاطع المفهرسة",
    "kb.stat.national": "وطنية",
    "kb.stat.international": "دولية",
    "kb.search.title": "البحث في قاعدة المعرفة",
    "kb.search.placeholder": "مثال: حق الاعتراض على القرارات الآلية",
    "kb.search.aria": "عبارة البحث",
    "kb.search.button": "بحث",
    "kb.search.allDomains": "جميع المجالات",
    "kb.search.none": "لا توجد مقاطع مطابقة لهذا البحث.",
    "kb.search.failed": "تعذّر البحث: {error}",
    "kb.search.relevance": "درجة الصلة",
    "kb.docs.title": "الوثائق",
    "kb.docs.filter": "تصفية الوثائق",
    "kb.docs.all": "الكل",
    "kb.docs.none": "لا توجد وثائق مطابقة لهذه المرشحات.",
    "kb.docs.pages": "{n} صفحة",
    "kb.docs.passages": "{n} مقطعاً",
    "kb.docs.source": "المصدر الرسمي",
    "kb.group.national": "دولة الإمارات العربية المتحدة",
    "kb.group.international": "المراجع الدولية",
    "kb.lang.ar": "العربية",
    "kb.lang.en": "الإنجليزية",
    "kb.page": "ص {n}",
    "domain.government_services": "الخدمات الحكومية",
    "domain.data_protection": "حماية البيانات",
    "domain.ai_governance": "حوكمة الذكاء الاصطناعي",
    "domain.telecom": "الاتصالات والأمن السيبراني",
    "domain.national_policy": "السياسات الوطنية",
    "domain.global_practice": "الممارسات العالمية",
    "domain.cross_domain": "متعدد المجالات",
    "type.law": "قانون",
    "type.regulation": "لائحة",
    "type.strategy": "استراتيجية",
    "type.guideline": "إرشادات",
    "type.standard": "معيار",
    "type.report": "تقرير",
    "type.use_case": "حالة استخدام",
    "type.other": "أخرى",
  },
});

const domainLabel = (d) => (DOMAINS.includes(d) ? t(`domain.${d}`) : d);
const typeLabel = (d) => (TYPES.includes(d) ? t(`type.${d}`) : d);

function segmented(name, options, onChange) {
  const group = h("div", { class: "segmented", role: "radiogroup", "aria-label": name });
  let value = options[0].value;
  const draw = () => {
    for (const b of group.children) b.setAttribute("aria-checked", String(b.dataset.value === value));
  };
  for (const o of options) {
    group.append(
      h("button", {
        type: "button", role: "radio", "data-value": o.value, text: o.label,
        onclick: () => { value = o.value; draw(); onChange(); },
      }),
    );
  }
  draw();
  return { el: group, get value() { return value; } };
}

export async function renderKnowledgeBase(container) {
  const stats = h("div", { class: "stats" });
  const query = h("input", { class: "input search-input", type: "search", dir: "auto", placeholder: t("kb.search.placeholder"), "aria-label": t("kb.search.aria") });
  const domain = h("select", { class: "select", "aria-label": t("kb.search.allDomains") },
    h("option", { value: "", text: t("kb.search.allDomains") }),
    DOMAINS.map((d) => h("option", { value: d, text: domainLabel(d) })),
  );
  const searchBtn = h("button", { class: "btn primary", type: "submit", text: t("kb.search.button") });
  const hits = h("div", { class: "hits", "aria-live": "polite" });

  const docFilter = h("input", { class: "input", type: "search", dir: "auto", placeholder: t("kb.docs.filter"), "aria-label": t("kb.docs.filter") });
  const origin = segmented(t("kb.docs.filter"), [
    { value: "", label: t("kb.docs.all") },
    { value: "AE", label: t("kb.stat.national") },
    { value: "INT", label: t("kb.stat.international") },
  ], drawDocs);
  const lang = segmented(t("kb.docs.filter"), [
    { value: "", label: t("kb.docs.all") },
    { value: "ar", label: t("kb.lang.ar") },
    { value: "en", label: t("kb.lang.en") },
  ], drawDocs);
  const docList = h("div", { class: "doc-groups" }, h("div", { class: "skeleton", style: { height: "120px" } }));

  container.append(
    h("header", { class: "page-head" },
      h("div", {}, h("h1", { text: t("kb.title") }), h("p", { text: t("kb.subtitle") })),
    ),
    stats,
    h("section", { class: "section panel search-panel" },
      h("h2", { text: t("kb.search.title") }),
      h("form", { class: "search-row", onsubmit: search }, query, domain, searchBtn),
      hits,
    ),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("h2", { text: t("kb.docs.title") })),
      h("div", { class: "toolbar" }, docFilter, origin.el, lang.el),
      docList,
    ),
  );
  docFilter.addEventListener("input", drawDocs);

  let docs = [];
  try {
    docs = await api("/documents");
    const passages = docs.reduce((n, d) => n + d.chunk_count, 0);
    const national = docs.filter((d) => d.country_code === "AE").length;
    stats.append(
      stat(num(docs.length), t("kb.stat.documents")),
      stat(num(passages), t("kb.stat.chunks")),
      stat(num(national), t("kb.stat.national")),
      stat(num(docs.length - national), t("kb.stat.international")),
    );
    drawDocs();
  } catch (err) {
    docList.replaceChildren(h("p", { class: "error", text: t("common.loadFailed", { error: err.message }) }));
  }

  function drawDocs() {
    if (!docs.length) return;
    const q = docFilter.value.trim().toLowerCase();
    const shown = docs.filter((d) =>
      (!origin.value || (origin.value === "AE" ? d.country_code === "AE" : d.country_code !== "AE")) &&
      (!lang.value || d.language === lang.value) &&
      (!q || `${d.title} ${domainLabel(d.domain)} ${typeLabel(d.doc_type)}`.toLowerCase().includes(q)),
    );
    if (!shown.length) {
      docList.replaceChildren(h("div", { class: "empty", text: t("kb.docs.none") }));
      return;
    }
    const groups = [
      { key: "national", items: shown.filter((d) => d.country_code === "AE") },
      { key: "international", items: shown.filter((d) => d.country_code !== "AE") },
    ].filter((g) => g.items.length);
    docList.replaceChildren(
      ...groups.map((g) =>
        h("div", { class: "doc-group" },
          h("h3", { text: `${t(`kb.group.${g.key}`)} · ${num(g.items.length)}` }),
          h("div", { class: "doc-grid" }, g.items.map(docCard)),
        ),
      ),
    );
  }

  async function search(e) {
    e.preventDefault();
    const q = query.value.trim();
    if (!q) {
      query.focus();
      return;
    }
    searchBtn.disabled = true;
    hits.replaceChildren(...[0, 1].map(() => h("div", { class: "hit" }, h("div", { class: "skeleton", style: { width: "40%" } }), h("div", { class: "skeleton", style: { marginTop: "10px" } }))));
    try {
      const params = new URLSearchParams({ q, top_k: "6" });
      if (domain.value) params.set("domain", domain.value);
      const results = await api(`/kb/search?${params}`);
      hits.replaceChildren(
        ...(results.length ? results.map((r) => hitCard(r, q)) : [h("div", { class: "empty", text: t("kb.search.none") })]),
      );
    } catch (err) {
      hits.replaceChildren(h("div", { class: "notice danger", text: t("kb.search.failed", { error: err.message }) }));
    }
    searchBtn.disabled = false;
  }
}

function stat(value, label) {
  return h("div", { class: "stat" }, h("b", { text: value }), h("span", { text: label }));
}

function docCard(d) {
  return h("article", { class: "doc-card" },
    h("div", { class: "doc-top" },
      h("span", { class: "doc-lang", text: d.language.toUpperCase() }),
      h("span", { class: "tag", text: typeLabel(d.doc_type) }),
    ),
    h("h4", { dir: textDir(d.title), text: d.title }),
    h("div", { class: "doc-meta" },
      h("span", { text: domainLabel(d.domain) }),
      d.page_count ? h("span", { text: t("kb.docs.pages", { n: num(d.page_count) }) }) : null,
      h("span", { text: t("kb.docs.passages", { n: num(d.chunk_count) }) }),
      d.source_url ? h("a", { href: d.source_url, target: "_blank", rel: "noopener", text: t("kb.docs.source") }) : null,
    ),
  );
}

/** A search result with the query's words highlighted in the passage. */
function hitCard(r, q) {
  const words = q.split(/\s+/).filter((w) => w.length > 2).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const passage = h("p", { dir: textDir(r.content) });
  if (words.length) {
    const re = new RegExp(`(${words.join("|")})`, "gi");
    for (const part of r.content.split(re)) {
      passage.append(re.test(part) ? h("mark", { text: part }) : part);
      re.lastIndex = 0;
    }
  } else {
    passage.textContent = r.content;
  }
  const score = Math.max(0, Math.min(1, r.score));
  return h("article", { class: "hit" },
    h("header", {},
      r.source_url
        ? h("a", { class: "hit-title", href: r.source_url, target: "_blank", rel: "noopener", dir: textDir(r.title), text: r.title })
        : h("b", { dir: textDir(r.title), text: r.title }),
      r.section ? h("span", { class: "tag", dir: "auto", text: r.section }) : null,
      r.page ? h("span", { class: "tag", text: t("kb.page", { n: r.page }) }) : null,
      h("span", { class: "spacer" }),
      h("span", { class: "score", title: t("kb.search.relevance"), "--w": `${Math.round(score * 100)}%` }, h("i"), score.toFixed(2)),
    ),
    passage,
  );
}
