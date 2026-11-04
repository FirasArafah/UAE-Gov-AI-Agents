import { api } from "../js/api.js";
import { agentColor, agentName } from "../js/agents.js";
import { addStrings, language, num, t } from "../js/i18n.js";
import { h, textDir } from "../js/render.js";

const ACTIONS = ["retrieval", "reasoning", "decision", "handoff", "policy_reference"];
const SOURCES_SPLIT = "\n\n---\n";

addStrings({
  en: {
    "audit.title": "Audit log",
    "audit.back": "Back to the simulation",
    "audit.export": "Export JSON",
    "audit.stat.records": "Records",
    "audit.stat.decisions": "Decisions",
    "audit.stat.handoffs": "Hand-offs",
    "audit.stat.sources": "Distinct passages cited",
    "audit.filter.all": "All",
    "audit.filter.agent": "All agents",
    "audit.filter.search": "Search the reasoning",
    "audit.none": "No record matches these filters.",
    "audit.shown": "{n} of {total} records",
    "audit.sources": "Sources ({n})",
    "audit.details": "Details",
    "audit.system": "System",
    "audit.query": "Query: {q}",
    "audit.fromAgents": "Received from {names}",
    "audit.page": "p. {n}",
    "action.retrieval": "Retrieval",
    "action.reasoning": "Reasoning",
    "action.decision": "Decision",
    "action.handoff": "Hand-off",
    "action.policy_reference": "Gap report",
  },
  ar: {
    "audit.title": "سجل التدقيق",
    "audit.back": "العودة إلى المحاكاة",
    "audit.export": "تصدير JSON",
    "audit.stat.records": "السجلات",
    "audit.stat.decisions": "القرارات",
    "audit.stat.handoffs": "عمليات التسليم",
    "audit.stat.sources": "المقاطع المستشهد بها",
    "audit.filter.all": "الكل",
    "audit.filter.agent": "جميع الوكلاء",
    "audit.filter.search": "البحث في التحليل",
    "audit.none": "لا توجد سجلات مطابقة لهذه المرشحات.",
    "audit.shown": "{n} من {total} سجلاً",
    "audit.sources": "المصادر ({n})",
    "audit.details": "التفاصيل",
    "audit.system": "النظام",
    "audit.query": "الاستعلام: {q}",
    "audit.fromAgents": "تسلّم من {names}",
    "audit.page": "ص {n}",
    "action.retrieval": "استرجاع",
    "action.reasoning": "تحليل",
    "action.decision": "قرار",
    "action.handoff": "تسليم",
    "action.policy_reference": "تقرير الفجوات",
  },
});

/** A record's main text: decisions carry the answer, whose sources footer is shown apart. */
function recordText(log) {
  if (log.action === "retrieval" && log.audit_metadata?.query) {
    return t("audit.query", { q: log.audit_metadata.query });
  }
  if (log.action === "handoff" && log.audit_metadata?.from_agents) {
    return t("audit.fromAgents", { names: log.audit_metadata.from_agents.map((s) => agentName(s)).join(", ") });
  }
  return (log.reasoning || "").split(SOURCES_SPLIT)[0].trim();
}

const sourcesOf = (log) => (log.source_attributions?.length ? log.source_attributions : log.policy_references || []);

export async function renderAudit(container, { id }) {
  const stats = h("div", { class: "stats" });
  let action = "";
  const actionTabs = h("div", { class: "segmented", role: "radiogroup", "aria-label": t("audit.title") });
  const agentFilter = h("select", { class: "select", "aria-label": t("audit.filter.agent") }, h("option", { value: "", text: t("audit.filter.agent") }));
  const search = h("input", { class: "input", type: "search", dir: "auto", placeholder: t("audit.filter.search"), "aria-label": t("audit.filter.search") });
  const count = h("p", { class: "muted count" });
  const list = h("ol", { class: "audit-list" });
  const exportBtn = h("button", { class: "btn", type: "button", text: t("audit.export") });

  container.append(
    h("a", { class: "back-link", href: `/simulation/${id}`, text: t("audit.back") }),
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: t("audit.title") })), exportBtn),
    stats,
    h("div", { class: "toolbar audit-toolbar" }, actionTabs, agentFilter, search),
    count,
    list,
  );

  let logs = [];
  const agentsById = {};
  try {
    const [agents, data] = await Promise.all([api("/agents"), api(`/sessions/${id}/audit`)]);
    for (const a of agents) {
      agentsById[a.id] = a;
      agentFilter.append(h("option", { value: a.slug, text: agentName(a.slug, a.name) }));
    }
    logs = data;
  } catch (err) {
    list.replaceChildren(h("p", { class: "error", text: t("common.loadFailed", { error: err.message }) }));
    return;
  }

  const byAction = logs.reduce((m, l) => ((m[l.action] = (m[l.action] || 0) + 1), m), {});
  const cited = new Set(logs.flatMap((l) => sourcesOf(l).map((r) => r.chunk_id)).filter(Boolean));
  stats.replaceChildren(
    ...[
      [logs.length, "audit.stat.records"],
      [byAction.decision || 0, "audit.stat.decisions"],
      [byAction.handoff || 0, "audit.stat.handoffs"],
      [cited.size, "audit.stat.sources"],
    ].map(([value, key]) => h("div", { class: "stat" }, h("b", { text: num(value) }), h("span", { text: t(key) }))),
  );

  for (const [value, label] of [["", t("audit.filter.all")], ...ACTIONS.filter((a) => byAction[a]).map((a) => [a, t(`action.${a}`)])]) {
    actionTabs.append(
      h("button", {
        type: "button", role: "radio", "data-value": value, "aria-checked": String(value === action),
        text: value ? `${label} · ${num(byAction[value])}` : label,
        onclick: () => {
          action = value;
          for (const b of actionTabs.children) b.setAttribute("aria-checked", String(b.dataset.value === action));
          draw();
        },
      }),
    );
  }

  const timeFormat = new Intl.DateTimeFormat(language() === "ar" ? "ar-AE-u-nu-latn" : "en-GB", { timeStyle: "medium" });

  function record(log) {
    const agent = agentsById[log.agent_id];
    const text = recordText(log);
    const refs = sourcesOf(log);
    const meta = log.audit_metadata || {};
    const summary = text.replace(/\s+/g, " ");
    return h("li", { class: "audit-item", "data-action": log.action },
      h("details", {},
        h("summary", {},
          h("span", { class: "audit-dot", "aria-hidden": "true" }),
          h("span", { class: "audit-action", text: t(`action.${log.action}`) }),
          h("span", { class: "audit-agent", "--agent": agentColor(agent?.slug), text: agent ? agentName(agent.slug, agent.name) : t("audit.system") }),
          h("span", { class: "audit-summary", dir: textDir(summary), text: summary }),
          h("time", { class: "audit-time", datetime: log.created_at, text: timeFormat.format(new Date(log.created_at)) }),
        ),
        h("div", { class: "audit-detail" },
          text ? h("div", { class: "trace", dir: textDir(text), text }) : null,
          refs.length
            ? h("div", {},
                h("h4", { text: t("audit.sources", { n: num(refs.length) }) }),
                h("ol", { class: "sources" },
                  refs.map((r, i) =>
                    h("li", {},
                      h("span", { class: "n", text: `[${i + 1}]` }),
                      h("span", { dir: "auto" }, r.title || "—",
                        h("small", { text: " — " + [r.section, r.page ? t("audit.page", { n: r.page }) : null, r.score != null ? Number(r.score).toFixed(2) : null].filter(Boolean).join(" · ") }),
                      ),
                    ),
                  ),
                ),
              )
            : null,
          Object.keys(meta).length && log.action !== "retrieval"
            ? h("details", { class: "meta-box" }, h("summary", { text: t("audit.details") }), h("pre", { class: "trace mono", text: JSON.stringify(meta, null, 2) }))
            : null,
        ),
      ),
    );
  }

  function draw() {
    const q = search.value.trim().toLowerCase();
    const shown = logs.filter((l) =>
      (!action || l.action === action) &&
      (!agentFilter.value || agentsById[l.agent_id]?.slug === agentFilter.value) &&
      (!q || (l.reasoning || "").toLowerCase().includes(q)),
    );
    count.textContent = t("audit.shown", { n: num(shown.length), total: num(logs.length) });
    list.replaceChildren(...(shown.length ? shown.map(record) : [h("li", { class: "empty", text: t("audit.none") })]));
  }

  agentFilter.addEventListener("change", draw);
  search.addEventListener("input", draw);
  exportBtn.addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `mathuq-audit-${id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
  draw();
}
