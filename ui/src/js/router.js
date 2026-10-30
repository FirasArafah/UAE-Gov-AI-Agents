const routes = [];

export function route(pattern, render) {
  const keys = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, k) => (keys.push(k), "([^/]+)")) + "$"
  );
  routes.push({ regex, keys, render });
}

export function startRouter(container) {
  async function go() {
    const path = location.hash.slice(1) || "/";
    for (const r of routes) {
      const m = path.match(r.regex);
      if (m) {
        const params = Object.fromEntries(r.keys.map((k, i) => [k, m[i + 1]]));
        container.innerHTML = "";
        await r.render(container, params);
        return;
      }
    }
    container.textContent = "Page not found";
  }
  window.addEventListener("hashchange", go);
  go();
}