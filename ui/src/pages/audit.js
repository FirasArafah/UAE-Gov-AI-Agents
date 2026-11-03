import { api } from "../js/api.js";
import { agentColor } from "../js/agents.js";
import { h } from "../js/render.js";

const ACTIONS = {
  retrieval: "Retrieval",
  reasoning: "Reasoning",
  decision: "Decision",
  handoff: "Hand-off",
  policy_reference: "Gap report",
};

export async function renderAudit(container, { id }) {
  const stats = h("div", { class: "stats" });
  const fAction = h("select", { class: "select", "aria-label": "Filter by action" }, h("option", { value: "", text: "All actions" }), Object.entries(ACTIONS).map(([v, t]) => h("option", { value: v, text: t })));
  const fAgent = h("select", { class: "select", "aria-label": "Filter by agent" }, h("option", { value: "", text: "All agents" }));
  const search = h("input", { class: "input grow", type: "search", placeholder: "Search reasoning text…", "aria-label": "Search" });
  const rows = h("tbody");
  const table = h("div", { class: "table-wrap" },
    h("table", { class: "data" },
      h("thead", {}, h("tr", {}, ["Time", "Action", "Agent", "Summary", "Sources"].map((t) => h("th", { text: t })))),
      rows,
    ),
  );
  const status = h("p", { class: "muted", text: "Loading…" });

  container.append(
    h("div", { class: "page-head" },
      h("div", {},
        h("div", { class: "eyebrow", text: "Auditability" }),
        h("h1", { text: "Audit log" }),
        h("p", { text: "Every retrieval, reasoning trace, decision and inter-agent hand-off, with the exact policy sources each one relied on. Click a row for the full record." }),
      ),
      h("div", { class: "card-actions" },
        h("a", { class: "btn", href: `#/session/${id}`, text: "← Back to simulation" }),
        h("button", { class: "btn primary", type: "button", text: "Export JSON", onclick: exportJson }),
      ),
    ),
    stats,
    h("div", { class: "toolbar", style: { marginTop: "20px" } }, fAction, fAgent, search),
    status,
    table,
  );

  let logs = [];
  const agentsById = {};
  try {
    const [agents, data] = await Promise.all([api("/agents"), api(`/sessions/${id}/audit`)]);
    for (const a of agents) {
      agentsById[a.id] = a;
      fAgent.append(h("option", { value: a.slug, text: a.name }));
    }
    logs = data;
  } catch (err) {
    status.className = "error";
    status.textContent = "Could not load audit log: " + err.message;
    table.hidden = true;
    return;
  }

  const counts = logs.reduce((m, l) => ((m[l.action] = (m[l.action] || 0) + 1), m), {});
  const cited = new Set(logs.flatMap((l) => [...(l.policy_references || []), ...(l.source_attributions || [])]).map((r) => r.chunk_id).filter(Boolean));
  stats.append(
    h("div", { class: "stat" }, h("b", { text: logs.length }), h("span", { text: "audit records" })),
    h("div", { class: "stat" }, h("b", { text: counts.decision || 0 }), h("span", { text: "agent decisions" })),
    h("div", { class: "stat" }, h("b", { text: counts.handoff || 0 }), h("span", { text: "inter-agent hand-offs" })),
    h("div", { class: "stat" }, h("b", { text: cited.size }), h("span", { text: "distinct policy excerpts used" })),
  );

  function refsOf(l) {
    return l.source_attributions?.length ? l.source_attributions : l.policy_references || [];
  }

  function draw() {
    rows.innerHTML = "";
    const q = search.value.trim().toLowerCase();
    const shown = logs.filter((l) => {
      const slug = agentsById[l.agent_id]?.slug;
      return (!fAction.value || l.action === fAction.value) &&
        (!fAgent.value || slug === fAgent.value) &&
        (!q || (l.reasoning || "").toLowerCase().includes(q));
    });
    status.textContent = shown.length ? `${shown.length} of ${logs.length} records` : "No records match.";
    table.hidden = !shown.length;

    for (const l of shown) {
      const agent = agentsById[l.agent_id];
      const refs = refsOf(l);
      const detail = h("tr", { class: "detail", hidden: true },
        h("td", { colspan: 5 },
          h("pre", { class: "trace", dir: "auto", style: { margin: 0, maxHeight: "420px" }, text: l.reasoning || "(empty)" }),
          refs.length
            ? h("ol", { class: "sources", style: { padding: "12px 0 0" } },
                refs.map((r, i) => h("li", {}, h("span", { class: "n", text: `[${i + 1}]` }), h("span", {}, r.title || "Untitled", h("small", { text: " — " + [r.section, r.page ? `p. ${r.page}` : null, r.score != null ? `score ${Number(r.score).toFixed(2)}` : null].filter(Boolean).join(" · ") })))),
              )
            : null,
          Object.keys(l.audit_metadata || {}).length
            ? h("pre", { class: "trace", style: { margin: "12px 0 0" }, text: JSON.stringify(l.audit_metadata, null, 2) })
            : null,
        ),
      );
      const tr = h("tr", { class: "clickable", tabindex: 0, "aria-expanded": "false" },
        h("td", { class: "mono", text: new Date(l.created_at).toLocaleTimeString() }),
        h("td", {}, h("span", { class: "tag action-tag", "data-action": l.action }, h("i"), ACTIONS[l.action] || l.action)),
        h("td", { style: { color: agent ? agentColor(agent.slug) : undefined, fontWeight: 600 }, text: agent ? agent.name : "—" }),
        h("td", { dir: "auto", text: (l.reasoning || "").replace(/\s+/g, " ").slice(0, 120) + ((l.reasoning || "").length > 120 ? "…" : "") }),
        h("td", { class: "num", text: refs.length || "—" }),
      );
      const toggle = () => {
        detail.hidden = !detail.hidden;
        tr.setAttribute("aria-expanded", String(!detail.hidden));
      };
      tr.addEventListener("click", toggle);
      tr.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()));
      rows.append(tr, detail);
    }
  }

  function exportJson() {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `synora-audit-${id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  fAction.addEventListener("change", draw);
  fAgent.addEventListener("change", draw);
  search.addEventListener("input", draw);
  draw();
}
