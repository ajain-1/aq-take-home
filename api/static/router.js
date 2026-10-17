/** Hash router: each route maps a pattern like "/runs/:id" to a view function that
 * renders into the container and may return a cleanup function (e.g. stop polling). */
export function createRouter(routes, container, notFound) {
  let cleanup = null;

  function match(path) {
    const parts = path.split("/").filter(Boolean);
    for (const [pattern, view] of routes) {
      const keys = pattern.split("/").filter(Boolean);
      if (keys.length !== parts.length) continue;
      const params = {};
      const ok = keys.every((key, i) => {
        if (key.startsWith(":")) return (params[key.slice(1)] = decodeURIComponent(parts[i])), true;
        return key === parts[i];
      });
      if (ok) return { view, params };
    }
    return { view: notFound, params: {} };
  }

  function navigate() {
    cleanup?.();
    const [path, query = ""] = (location.hash.slice(1) || "/").split("?");
    const { view, params } = match(path);
    container.replaceChildren();
    window.scrollTo(0, 0);
    cleanup = view(container, params, new URLSearchParams(query)) ?? null;
    document.querySelectorAll("[data-nav]").forEach((link) =>
      link.classList.toggle("active", link.dataset.nav === (path.startsWith("/submit") ? "submit" : "dashboard")));
  }

  window.addEventListener("hashchange", navigate);
  return { start: navigate };
}

export const go = (path) => { location.hash = path; };
