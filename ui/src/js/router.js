const routes = [];

export function route(pattern, render) {
  const keys = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "$"
  );
  routes.push({ regex, keys, render });
}

export function startRouter(container, onNavigate) {
  async function go() {
    const path = location.hash.slice(1) || "/";
    onNavigate?.(path);
    for (const r of routes) {
      const m = path.match(r.regex);
      if (m) {
        const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
        container.innerHTML = "";
        window.scrollTo(0, 0);
        await r.render(container, params);
        return;
      }
    }
    container.innerHTML = `<div class="empty">Page not found. <a href="#/">Back to Ask agents</a></div>`;
  }
  window.addEventListener("hashchange", go);
  go();
}
