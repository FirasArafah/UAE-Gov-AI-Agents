import { api } from "../js/api.js";
import { h } from "../js/render.js";

const DOMAINS = ["government_services", "data_protection", "ai_governance", "cross_domain"];
const label = (s) => s.replace(/_/g, " ");

export async function renderKnowledgeBase(container) {
  const stats = h("div", { class: "stats" });
  const rows = h("tbody");
  const docsStatus = h("p", { class: "muted", text: "Loading…" });
  const query = h("input", { class: "input grow", type: "search", dir: "auto", placeholder: "e.g. right to object to automated processing", "aria-label": "Retrieval query" });
  const domain = h("select", { class: "select", "aria-label": "Domain" }, h("option", { value: "", text: "All domains" }), DOMAINS.map((d) => h("option", { value: d, text: label(d) })));
  const searchBtn = h("button", { class: "btn primary", type: "submit", text: "Retrieve" });
  const hits = h("div", { class: "hits" });

  container.append(
    h("div", { class: "page-head" },
      h("div", {},
        h("div", { class: "eyebrow", text: "Knowledge base" }),
        h("h1", { text: "National and international policy corpus" }),
        h("p", { text: "UAE legislation, strategies and charters alongside the international references the agents map gaps to. Documents are chunked by article where possible and embedded with a multilingual model, so Arabic and English queries reach both editions." }),
      ),
    ),
    stats,
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("h2", { text: "Retrieval probe" }), h("span", { class: "muted", text: "Runs the same vector search the agents use." })),
      h("form", { class: "toolbar", onsubmit: search }, query, domain, searchBtn),
      hits,
    ),
    h("section", { class: "section" },
      h("h2", { text: "Documents" }),
      docsStatus,
      h("div", { class: "table-wrap" },
        h("table", { class: "data" },
          h("thead", {}, h("tr", {}, ["Document", "Origin", "Lang", "Domain", "Type", "Pages", "Chunks"].map((t, i) => h("th", { text: t, style: i > 4 ? { textAlign: "end" } : undefined })))),
          rows,
        ),
      ),
    ),
  );

  try {
    const docs = await api("/documents");
    docsStatus.remove();
    const chunks = docs.reduce((n, d) => n + d.chunk_count, 0);
    const uae = docs.filter((d) => d.country_code === "AE").length;
    const arabic = docs.filter((d) => d.language === "ar").length;
    stats.append(
      h("div", { class: "stat" }, h("b", { text: docs.length }), h("span", { text: "documents" })),
      h("div", { class: "stat" }, h("b", { text: chunks.toLocaleString() }), h("span", { text: "indexed chunks" })),
      h("div", { class: "stat" }, h("b", { text: `${uae} · ${docs.length - uae}` }), h("span", { text: "UAE · international" })),
      h("div", { class: "stat" }, h("b", { text: arabic }), h("span", { text: "Arabic editions" })),
    );
    for (const d of docs) {
      rows.append(
        h("tr", {},
          h("td", { dir: "auto", style: { fontWeight: 500 } }, d.title),
          h("td", {}, h("span", { class: "tag" + (d.country_code === "AE" ? " accent" : ""), text: d.country_code === "AE" ? "UAE" : d.country_code })),
          h("td", { class: "mono", text: d.language.toUpperCase() }),
          h("td", { text: label(d.domain) }),
          h("td", { text: d.doc_type }),
          h("td", { class: "num", text: d.page_count ?? "—" }),
          h("td", { class: "num", text: d.chunk_count }),
        ),
      );
    }
  } catch (err) {
    docsStatus.className = "error";
    docsStatus.textContent = "Could not load documents: " + err.message;
  }

  async function search(e) {
    e.preventDefault();
    const q = query.value.trim();
    if (!q) return;
    searchBtn.disabled = true;
    hits.innerHTML = "";
    hits.append(h("div", { class: "hit" }, h("div", { class: "skeleton", style: { width: "40%" } }), h("div", { class: "skeleton", style: { marginTop: "10px" } })));
    try {
      const params = new URLSearchParams({ q, top_k: "6" });
      if (domain.value) params.set("domain", domain.value);
      const results = await api(`/kb/search?${params}`);
      hits.innerHTML = "";
      if (!results.length) hits.append(h("div", { class: "empty", text: "No matching excerpts." }));
      for (const r of results) {
        hits.append(
          h("article", { class: "hit" },
            h("header", {},
              h("b", { dir: "auto", text: r.title }),
              r.section ? h("span", { class: "tag", text: r.section }) : null,
              r.page ? h("span", { class: "tag", text: `p. ${r.page}` }) : null,
              h("span", { style: { flex: 1 } }),
              h("span", { class: "score", "--w": `${Math.round(Math.max(0, Math.min(1, r.score)) * 100)}%` }, h("i"), r.score.toFixed(3)),
            ),
            h("p", { dir: "auto", text: r.content }),
          ),
        );
      }
    } catch (err) {
      hits.innerHTML = "";
      hits.append(h("div", { class: "notice danger", text: "Retrieval failed: " + err.message }));
    }
    searchBtn.disabled = false;
  }
}
