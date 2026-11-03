import { api } from "../js/api.js";
import { AGENTS, agentColor, agentInitials } from "../js/agents.js";
import { h } from "../js/render.js";

// ITU-T Y.3172 high-level ML pipeline, mapped onto SYNORA's components.
const PIPELINE = [
  { code: "SRC", title: "Sources", text: "UAE laws, strategies and charters; ITU, OECD, UNESCO and EU AI Act references." },
  { code: "C · PP", title: "Collect & pre-process", text: "Page-aware extraction, article-level chunking, bilingual bge-m3 embeddings in pgvector." },
  { code: "M", title: "Model", text: "Role-specific agents on a local LLM, each retrieving from its own legal domain first." },
  { code: "P", title: "Policy", text: "Citation verification, coordinator synthesis and human escalation of conflicts." },
  { code: "D · SINK", title: "Distribute & act", text: "Audit trail, assessments and a policy gap report mapped to global practice." },
];

export async function renderHome(container) {
  const stats = h("div", { class: "stats" },
    ["Agents", "Documents", "Indexed chunks", "Simulations"].map((label) =>
      h("div", { class: "stat" }, h("b", { html: '<span class="skeleton" style="display:block;width:40px;height:22px"></span>' }), h("span", { text: label })),
    ),
  );
  const cards = h("div", { class: "cards wide" }, h("div", { class: "card" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: { width: "60%" } })));
  const recent = h("div", { class: "panel list" });
  const status = h("p", { class: "error" });

  container.append(
    h("section", { class: "hero" },
      h("div", {},
        h("div", { class: "eyebrow", text: "Multi-agent AI governance simulation" }),
        h("h1", { text: "When a government AI system goes wrong, who decides what happens next?" }),
        h("p", { text: "SYNORA runs incident scenarios against agents that each hold a different institutional mandate. Events arrive in stages, every claim is cited to national law or a global reference, and the Coordinator reconciles their independent assessments into a gap report." }),
        h("div", { class: "card-actions" },
          h("a", { class: "btn primary", href: "#scenarios", text: "Run a scenario" }),
          h("a", { class: "btn", href: "#/chat", text: "Ask the agents" }),
          h("a", { class: "btn ghost", href: "#/kb", text: "Browse the knowledge base →" }),
        ),
      ),
      h("div", { class: "hero-agents" },
        Object.entries(AGENTS).map(([slug, a]) =>
          h("div", { class: "hero-agent", "--agent": a.color },
            h("span", { class: "avatar", text: a.short }),
            h("div", {}, h("b", { text: a.name }), h("span", { text: a.mandate })),
          ),
        ),
      ),
    ),
    h("section", { class: "section" }, stats),
    h("section", { class: "section", id: "scenarios" },
      h("div", { class: "section-head" }, h("h2", { text: "Scenarios" }), h("span", { class: "muted", text: "Events are released one at a time, as information would arrive in a real incident." })),
      status,
      cards,
    ),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("h2", { text: "Recent simulations" }), h("a", { href: "#/sessions", text: "All simulations →" })),
      recent,
    ),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("h2", { text: "Architecture" }), h("span", { class: "muted", text: "Mapped to the ITU-T Y.3172 machine learning pipeline" })),
      h("div", { class: "pipeline" },
        PIPELINE.map((s) => h("div", { class: "pipe-step" }, h("span", { class: "code", text: s.code }), h("h3", { text: s.title }), h("p", { text: s.text }))),
      ),
    ),
  );

  // The anchor link scrolls instead of changing the route.
  container.querySelector('a[href="#scenarios"]').addEventListener("click", (e) => {
    e.preventDefault();
    container.querySelector("#scenarios").scrollIntoView({ behavior: "smooth" });
  });

  try {
    const [agents, scenarios, documents, sessions] = await Promise.all([
      api("/agents"),
      api("/scenarios"),
      api("/documents").catch(() => []),
      api("/sessions?limit=20").catch(() => []),
    ]);
    const active = sessions.filter((s) => s.message_count > 0).slice(0, 5);
    const chunks = documents.reduce((n, d) => n + d.chunk_count, 0);
    const values = [agents.length, documents.length, chunks.toLocaleString(), active.length >= 5 ? "5+" : active.length];
    stats.querySelectorAll(".stat b").forEach((b, i) => (b.textContent = values[i]));

    cards.innerHTML = "";
    if (!scenarios.length) cards.append(h("div", { class: "empty", text: "No scenarios loaded. Run make seed." }));
    for (const s of scenarios) cards.append(scenarioCard(s));

    recent.innerHTML = "";
    if (!active.length) recent.append(h("div", { class: "list-row muted", text: "No simulations yet — start one above." }));
    for (const s of active) recent.append(sessionRow(s));
  } catch (err) {
    status.textContent = "Could not load data: " + err.message;
    cards.innerHTML = "";
  }
}

export function sessionRow(s) {
  return h("a", { class: "list-row", href: `#/session/${s.id}` },
    h("span", { class: "status-pill", "data-status": s.status, text: s.status }),
    h("div", { class: "grow" },
      h("b", { text: s.scenario_title }),
      h("small", { text: ` · event ${s.current_sequence} · ${s.message_count} messages` }),
    ),
    h("small", { text: new Date(s.created_at).toLocaleString() }),
  );
}

function scenarioCard(s) {
  const meta = s.scenario_metadata || {};
  const error = h("p", { class: "error" });
  const button = h("button", { class: "btn primary", type: "button", text: "Start simulation" });

  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Starting…";
    error.textContent = "";
    try {
      const session = await api("/sessions", { method: "POST", body: JSON.stringify({ scenario_id: s.id }) });
      await api(`/sessions/${session.id}/start`, { method: "POST" });
      location.hash = `#/session/${session.id}`;
    } catch (err) {
      button.disabled = false;
      button.textContent = "Start simulation";
      error.textContent = "Could not start: " + err.message;
    }
  });

  return h("article", { class: "card accent-top" },
    h("div", { class: "tags" },
      h("span", { class: "tag accent", text: s.domain.replace(/_/g, " ") }),
      meta.includes_controversy ? h("span", { class: "tag warn", text: "includes controversy" }) : null,
    ),
    h("h3", { text: s.title }),
    h("p", { class: "muted grow", text: s.description }),
    (meta.itu_dimensions || []).length
      ? h("div", { class: "tags" }, meta.itu_dimensions.map((d) => h("span", { class: "tag", text: d })))
      : null,
    h("div", { class: "card-actions" }, button,
      h("span", { class: "tags" }, Object.keys(AGENTS).map((slug) => h("span", { class: "avatar", "--agent": agentColor(slug), style: { width: "24px", height: "24px", fontSize: "0.6rem", borderRadius: "7px" }, title: AGENTS[slug].name, text: agentInitials(slug) }))),
    ),
    error,
  );
}
