import "./style.css";
import { api } from "./js/api.js";
import { route, startRouter } from "./js/router.js";
import { renderHome } from "./pages/home.js";
import { renderSessions } from "./pages/sessions.js";
import { renderRoster } from "./pages/roster.js";
import { renderSimulation } from "./pages/simulation.js";
import { renderAudit } from "./pages/audit.js";
import { renderChat } from "./pages/chat.js";
import { renderKnowledgeBase } from "./pages/kb.js";

document.getElementById("theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = dark ? "light" : "dark";
  try {
    localStorage.setItem("theme", root.dataset.theme);
  } catch {
    /* storage unavailable */
  }
});

function markActiveNav(path) {
  const section = "/" + (path.split("/")[1] || "");
  const aliases = { "/session": "/sessions", "/audit": "/sessions", "/chat": "/" };
  const current = aliases[section] ?? section;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.nav === current);
    if (a.dataset.nav === current) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

async function checkHealth() {
  const el = document.getElementById("health");
  const label = el.querySelector("span");
  try {
    const h = await api("/health");
    const ok = h.status === "ok";
    el.className = "health " + (ok ? "ok" : "degraded");
    label.textContent = ok ? "Local LLM online" : "Degraded";
    el.title = `Database: ${h.db} · LLM: ${h.ollama} · Agents: ${(h.agents || []).length}`;
  } catch {
    el.className = "health down";
    label.textContent = "Backend offline";
    el.title = "The API did not respond";
  }
}
checkHealth();
setInterval(checkHealth, 30000);

// Asking the agent team is the landing page; /chat stays as an alias for older links.
route("/", renderChat);
route("/overview", renderHome);
route("/sessions", renderSessions);
route("/agents", renderRoster);
route("/session/:id", renderSimulation);
route("/audit/:id", renderAudit);
route("/chat", renderChat);
route("/kb", renderKnowledgeBase);
startRouter(document.getElementById("app"), markActiveNav);
