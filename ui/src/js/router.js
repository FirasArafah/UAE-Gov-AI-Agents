import { t } from "./i18n.js";

/**
 * Path-based routing (/simulations, /chat/<id>) with the History API. Links to same-origin
 * paths are handled in the page; addresses from the earlier hash routing (/#/kb) are
 * converted to their path form.
 */

const routes = [];
let go = () => {};

function notFound() {
  const box = document.createElement("div");
  box.className = "page empty-page";
  const text = document.createElement("p");
  text.textContent = t("page.notFound");
  const link = document.createElement("a");
  link.className = "btn";
  link.href = "/";
  link.textContent = t("page.back");
  box.append(text, link);
  return box;
}

export function route(pattern, render) {
  const keys = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "/?$"
  );
  routes.push({ regex, keys, render });
}

/** Go to a path in the page; replace keeps the current entry out of the history. */
export function navigate(path, { replace = false } = {}) {
  if (path === location.pathname + location.search) return go();
  history[replace ? "replaceState" : "pushState"](null, "", path);
  return go();
}

/** Point the address bar at another path without rendering again (e.g. a new chat's id). */
export function setAddress(path) {
  history.replaceState(null, "", path);
}

/** Render the current page again, e.g. after the interface language changed. */
export const refreshRoute = () => go();

function isInternalLink(event) {
  const link = event.target.closest?.("a[href]");
  if (!link || link.target || link.hasAttribute("download")) return null;
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return null;
  }
  const url = new URL(link.href, location.href);
  if (url.origin !== location.origin || url.pathname.startsWith("/api")) return null;
  return url;
}

export function startRouter(container, onNavigate) {
  // Addresses from the earlier hash routing: /#/simulation/<id> becomes /simulation/<id>.
  if (location.hash.startsWith("#/")) {
    history.replaceState(null, "", location.hash.slice(1) || "/");
  }

  go = async () => {
    const path = location.pathname || "/";
    onNavigate?.(path);
    for (const r of routes) {
      const m = path.match(r.regex);
      if (m) {
        const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
        container.innerHTML = "";
        container.scrollTop = 0;
        await r.render(container, params);
        return;
      }
    }
    container.replaceChildren(notFound());
  };

  document.addEventListener("click", (event) => {
    const url = isInternalLink(event);
    if (!url) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  });
  window.addEventListener("popstate", () => go());
  go();
}
