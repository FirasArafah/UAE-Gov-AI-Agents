import { api } from "../js/api.js";
import { h } from "../js/render.js";
import { sessionRow } from "./home.js";

export async function renderSessions(container) {
  const list = h("div", { class: "panel list" }, h("div", { class: "list-row" }, h("div", { class: "skeleton", style: { width: "50%" } })));
  container.append(
    h("div", { class: "page-head" },
      h("div", {},
        h("div", { class: "eyebrow", text: "Simulations" }),
        h("h1", { text: "Scenario sessions" }),
        h("p", { text: "Every session keeps its full record: released events, agent assessments, reasoning traces, audit log and gap report. Sessions are immutable audit records." }),
      ),
      h("a", { class: "btn primary", href: "#/", text: "Start a new simulation" }),
    ),
    list,
  );
  try {
    const sessions = await api("/sessions?limit=50");
    list.innerHTML = "";
    if (!sessions.length) list.append(h("div", { class: "list-row muted", text: "No simulations yet." }));
    for (const s of sessions) list.append(sessionRow(s));
  } catch (err) {
    list.innerHTML = "";
    list.append(h("div", { class: "list-row error", text: "Could not load sessions: " + err.message }));
  }
}
