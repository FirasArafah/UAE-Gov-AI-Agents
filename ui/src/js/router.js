import { t } from "./i18n.js";

const routes = [];

function notFound() {
  const box = document.createElement("div");
  box.className = "page empty-page";
  const text = document.createElement("p");
  text.textContent = t("page.notFound");
  const link = document.createElement("a");
  link.className = "btn";
  link.href = "#/";
  link.textContent = t("page.back");
  box.append(text, link);
  return box;
}

export function route(pattern, render) {
  const keys = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "$"
  );
  routes.push({ regex, keys, render });
}

let rerender = () => {};

/** Render the current page again, e.g. after the interface language changed. */
export const refreshRoute = () => rerender();

export function startRouter(container, onNavigate) {
  async function go() {
    const path = location.hash.slice(1) || "/";
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
  }
  rerender = go;
  window.addEventListener("hashchange", go);
  go();
}
