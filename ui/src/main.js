import "./style.css";
import { api } from "./js/api.js";
import { h } from "./js/render.js";
import { applyLanguage, language, setLanguage, t } from "./js/i18n.js";
import { refreshRoute, route, startRouter } from "./js/router.js";
import { forgetChat, presetMode, renderChat } from "./pages/chat.js";
import { renderRoster } from "./pages/roster.js";
import { renderAudit } from "./pages/audit.js";
import { renderKnowledgeBase } from "./pages/kb.js";
import { renderScenarios } from "./pages/scenarios.js";
import { renderSimulation } from "./pages/simulation.js";

applyLanguage();

// Every address has the form /#/<page>: a bare "/", "/#", "#chat" or another path is rewritten.
function canonicalUrl() {
  const page = location.hash.replace(/^#\/?/, "");
  const target = `/#/${page}`;
  if (location.pathname !== "/" || !location.hash.startsWith("#/")) {
    history.replaceState(null, "", target);
  }
}
canonicalUrl();
window.addEventListener("hashchange", canonicalUrl);

document.getElementById("lang-toggle").addEventListener("click", () => {
  setLanguage(language() === "ar" ? "en" : "ar");
});
window.addEventListener("language-changed", () => {
  refreshRoute();
  loadRecents();
  checkHealth();
});

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

function markActiveRecent() {
  for (const a of document.querySelectorAll("#recents a")) {
    a.classList.toggle("active", a.getAttribute("href") === location.hash);
  }
}

function markActiveNav(path) {
  const section = "/" + (path.split("/")[1] || "");
  const aliases = { "/chat": "/", "/new": "/", "/simulation": "/simulations", "/audit": "/simulations" };
  const current = aliases[section] ?? section;
  for (const a of document.querySelectorAll("#nav a")) {
    a.classList.toggle("active", a.dataset.nav === current);
    if (a.dataset.nav === current) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  markActiveRecent();
}

async function loadRecents() {
  const list = document.getElementById("recents");
  try {
    const chats = await api("/chats");
    list.replaceChildren(
      ...chats.map((c) => h("a", { href: `#/chat/${c.id}`, dir: "auto", title: c.title, text: c.title })),
    );
    if (!chats.length) list.replaceChildren(h("small", { class: "muted", text: t("recents.empty") }));
    markActiveRecent();
  } catch {
    list.replaceChildren(h("small", { class: "muted", text: t("recents.error") }));
  }
}
window.addEventListener("chats-changed", loadRecents);
loadRecents();

async function checkHealth() {
  const el = document.getElementById("health");
  const label = el.querySelector("span");
  try {
    const h = await api("/health");
    const ok = h.status === "ok";
    el.className = "health " + (ok ? "ok" : "degraded");
    label.textContent = t(ok ? "health.ok" : "health.degraded");
    el.title = t("health.title", { db: h.db, llm: h.ollama, agents: (h.agents || []).length });
  } catch {
    el.className = "health down";
    label.textContent = t("health.down");
    el.title = t("health.down");
  }
}
checkHealth();
setInterval(checkHealth, 30000);

/** Agents and Knowledge base scroll as ordinary pages; the chat manages its own layout. */
const asPage = (render) => (container, params) => {
  const page = h("div", { class: "page" });
  container.append(page);
  return render(page, params);
};

route("/", renderChat);
route("/chat", renderChat);
route("/chat/:id", renderChat);
route("/new", () => {
  forgetChat();
  location.hash = "#/";
});
route("/ask/:agent", (_, { agent }) => {
  forgetChat();
  presetMode(agent);
  history.replaceState(null, "", "/#/");
  window.dispatchEvent(new HashChangeEvent("hashchange"));
});
route("/simulations", asPage(renderScenarios));
route("/simulation/:id", asPage(renderSimulation));
route("/audit/:id", asPage(renderAudit));
// Addresses used by earlier versions of the interface.
const redirect = (to) => (_, params) => {
  history.replaceState(null, "", `/#${to(params)}`);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
};
for (const old of ["/overview", "/scenarios", "/sessions"]) route(old, redirect(() => "/simulations"));
route("/session/:id", redirect(({ id }) => `/simulation/${id}`));
route("/agents", asPage(renderRoster));
route("/kb", asPage(renderKnowledgeBase));
startRouter(document.getElementById("app"), markActiveNav);
