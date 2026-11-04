import "./style.css";
import { api } from "./js/api.js";
import { h } from "./js/render.js";
import { applyLanguage, language, setLanguage, t } from "./js/i18n.js";
import { navigate, refreshRoute, route, startRouter } from "./js/router.js";
import { closeDrawer, setPageTitle } from "./js/shell.js";
import { forgetChat, presetMode, renderChat } from "./pages/chat.js";
import { renderRoster } from "./pages/roster.js";
import { renderAudit } from "./pages/audit.js";
import { renderKnowledgeBase } from "./pages/kb.js";
import { renderScenarios } from "./pages/scenarios.js";
import { renderSimulation } from "./pages/simulation.js";

applyLanguage();

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
    a.classList.toggle("active", a.getAttribute("href") === location.pathname);
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
  closeDrawer();
  // Pages with their own title (a chat, a simulation run) replace this once they have loaded.
  const titles = { "/": "nav.newChat", "/simulations": "nav.simulations", "/agents": "nav.agents", "/kb": "nav.kb", "/audit": "audit.title" };
  setPageTitle(titles[section] ? t(titles[section]) : "");
}

const MORE_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="5" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="19" cy="12" r="1.8" fill="currentColor"/></svg>';

async function loadRecents() {
  const list = document.getElementById("recents");
  try {
    const chats = await api("/chats");
    list.replaceChildren(...chats.map(recentItem));
    if (!chats.length) list.replaceChildren(h("small", { class: "muted", text: t("recents.empty") }));
    markActiveRecent();
  } catch {
    list.replaceChildren(h("small", { class: "muted", text: t("recents.error") }));
  }
}

/** One Recent entry: the link plus a menu to rename or delete the chat. */
function recentItem(chat) {
  const link = h("a", { href: `/chat/${chat.id}`, dir: "auto", title: chat.title, text: chat.title });
  const label = t("recents.options", { title: chat.title });
  const more = h("button", {
    class: "recent-more",
    type: "button",
    html: MORE_ICON,
    title: label,
    "aria-label": label,
    "aria-haspopup": "menu",
    "aria-expanded": "false",
    onclick: (e) => {
      e.stopPropagation();
      openRecentMenu(more, [
        [t("recents.rename"), () => startRename(item, link, chat)],
        [t("recents.delete"), () => deleteChat(chat), "danger"],
      ]);
    },
  });
  const item = h("div", { class: "recent-item" }, link, more);
  return item;
}

let recentMenu = null;

function closeRecentMenu() {
  if (!recentMenu) return;
  recentMenu.opener.setAttribute("aria-expanded", "false");
  recentMenu.el.remove();
  recentMenu = null;
}

function openRecentMenu(opener, entries) {
  const reopen = recentMenu?.opener === opener;
  closeRecentMenu();
  if (reopen) return;
  const el = h("div", { class: "recent-menu", role: "menu" },
    ...entries.map(([label, run, tone]) =>
      h("button", {
        type: "button",
        role: "menuitem",
        class: tone || "",
        text: label,
        onclick: () => {
          closeRecentMenu();
          run();
        },
      }),
    ),
  );
  document.body.append(el);
  const box = opener.getBoundingClientRect();
  const rtl = document.documentElement.dir === "rtl";
  el.style.top = `${Math.min(box.bottom + 4, innerHeight - el.offsetHeight - 8)}px`;
  el.style.left = rtl ? `${box.left}px` : `${Math.max(8, box.right - el.offsetWidth)}px`;
  opener.setAttribute("aria-expanded", "true");
  recentMenu = { el, opener };
  el.querySelector("button").focus();
}

document.addEventListener("click", (e) => {
  if (recentMenu && !recentMenu.el.contains(e.target)) closeRecentMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && recentMenu) {
    const opener = recentMenu.opener;
    closeRecentMenu();
    opener.focus();
  }
});
document.getElementById("recents").addEventListener("scroll", closeRecentMenu);

function startRename(item, link, chat) {
  const input = h("input", { class: "recent-rename", dir: "auto", maxlength: 80, "aria-label": t("recents.renameLabel") });
  input.value = chat.title;
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (save && title && title !== chat.title) {
      try {
        const renamed = await api(`/chats/${chat.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
        window.dispatchEvent(new CustomEvent("chat-renamed", { detail: { id: chat.id, title: renamed.title } }));
      } catch (err) {
        alert(t("recents.failed", { error: err.message }));
      }
      loadRecents();
    } else {
      item.classList.remove("renaming");
      input.replaceWith(link);
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      finish(true);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      finish(false);
    }
  });
  input.addEventListener("blur", () => finish(true));
  link.replaceWith(input);
  item.classList.add("renaming");
  input.focus();
  input.select();
}

async function deleteChat(chat) {
  if (!confirm(t("recents.confirmDelete", { title: chat.title }))) return;
  try {
    await api(`/chats/${chat.id}`, { method: "DELETE" });
  } catch (err) {
    alert(t("recents.failed", { error: err.message }));
    return;
  }
  if (location.pathname === `/chat/${chat.id}`) {
    forgetChat();
    navigate("/");
  }
  loadRecents();
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
  navigate("/", { replace: true });
});
route("/ask/:agent", (_, { agent }) => {
  forgetChat();
  presetMode(agent);
  navigate("/", { replace: true });
});
route("/simulations", asPage(renderScenarios));
route("/simulation/:id", asPage(renderSimulation));
route("/audit/:id", asPage(renderAudit));
// Addresses used by earlier versions of the interface.
const redirect = (to) => (_, params) => navigate(to(params), { replace: true });
for (const old of ["/overview", "/scenarios", "/sessions"]) route(old, redirect(() => "/simulations"));
route("/session/:id", redirect(({ id }) => `/simulation/${id}`));
route("/agents", asPage(renderRoster));
route("/kb", asPage(renderKnowledgeBase));
startRouter(document.getElementById("app"), markActiveNav);
