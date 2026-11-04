import { api } from "../js/api.js";
import { AGENTS, agentColor, agentInitials } from "../js/agents.js";
import { h } from "../js/render.js";

// Where each agent's retrieval starts (mirrors ROLE_DOMAINS in agents/base.py).
const RETRIEVAL_DOMAIN = {
  icp: "Government services (entry & residence law)",
  auditor: "Data protection",
  privacy: "Data protection (PDPL)",
  coordinator: "Data protection; synthesizes other agents",
};

export async function renderRoster(container) {
  const cards = h("div", { class: "cards" });
  const status = h("p", { class: "muted", text: "Loading…" });
  container.append(
    h("div", { class: "page-head" },
      h("div", {},
        h("div", { class: "eyebrow", text: "Institutional roles" }),
        h("h1", { text: "Agents" }),
        h("p", { text: "Each agent represents a government actor with its own mandate, its own slice of the knowledge base and its own temperature. They receive different events and produce independent assessments; the Coordinator reconciles them." }),
      ),
    ),
    status,
    cards,
  );

  try {
    const agents = await api("/agents");
    status.remove();
    for (const a of agents) {
      cards.append(
        h("article", { class: "card accent-top", "--agent": agentColor(a.slug) },
          h("div", { style: { display: "flex", gap: "12px", alignItems: "center" } },
            h("span", { class: "avatar lg", text: agentInitials(a.slug, a.name) }),
            h("div", {}, h("h3", { text: a.name }), h("small", { class: "muted", text: AGENTS[a.slug]?.mandate || a.role })),
          ),
          h("p", { class: "grow", dir: "auto", text: a.mandate }),
          RETRIEVAL_DOMAIN[a.slug]
            ? h("div", { class: "tags" }, h("span", { class: "tag", text: "Retrieves first from: " + RETRIEVAL_DOMAIN[a.slug] }))
            : null,
          h("div", { class: "card-actions" }, h("a", { class: "btn sm", href: "#/", text: "Ask this agent" })),
        ),
      );
    }
  } catch (err) {
    status.className = "error";
    status.textContent = "Could not load agents: " + err.message;
  }
}
