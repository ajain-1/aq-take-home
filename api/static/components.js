/** Shared rendering helpers. Content is always inserted as text nodes, never parsed as HTML. */

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === false || value == null) continue;
    if (key === "class") el.className = value;
    else if (key === "style") el.style.cssText = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function render(el, ...children) {
  el.replaceChildren();
  append(el, children);
}

// --- formatting -----------------------------------------------------------------

export function relTime(iso) {
  if (!iso) return "—";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const units = [["d", 86400], ["h", 3600], ["m", 60]];
  for (const [unit, size] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${unit} ago`;
  return "just now";
}

export const absTime = (iso) => (iso ? new Date(iso).toLocaleString() : "");
export const time = (iso) => h("time", { datetime: iso ?? "", title: absTime(iso), class: "nowrap" }, relTime(iso));

export function duration(sec) {
  if (sec == null) return "—";
  if (sec < 60) return `${sec.toFixed(0)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${String(Math.round(sec % 60)).padStart(2, "0")}s`;
  return `${(sec / 3600).toFixed(1)}h`;
}

export const pct = (rate) => (rate == null ? "—" : `${Math.round(rate * 100)}%`);
export const money = (usd) => (usd == null ? "—" : `$${usd.toFixed(2)}`);

export function compact(n) {
  if (n == null) return "—";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return String(n);
}

export const shortModel = (model) => (model ? model.split("/").pop() : null);
export const humanize = (value) => (value ? String(value).replaceAll("_", " ") : "—");
export const shortId = (id) => id.slice(0, 8);

// --- status vocabulary ------------------------------------------------------------
// Outcome is the only coloured status. Pipeline phase and pod state are neutral detail.

const OUTCOME_LABELS = {
  passed: "Passed", partial: "Partially passed", failed: "Failed",
  error: "Error", running: "Running", queued: "Queued",
};

export const outcomeBadge = (outcome, size = "") =>
  h("span", { class: `badge outcome-${outcome} ${size}` }, OUTCOME_LABELS[outcome] ?? humanize(outcome));

export function attemptBadge(attempt) {
  if (attempt.resolved) return h("span", { class: "badge outcome-passed" }, "Resolved");
  if (attempt.status === "error") return h("span", { class: "badge outcome-error" }, "Error");
  return h("span", { class: "badge outcome-failed" }, "Unresolved");
}

export const testBadge = (status) => h("span", { class: `badge test-${status}` }, status);
export const chip = (text, title) => h("span", { class: "chip", title }, text);

export const PHASE_LABELS = {
  queued: "Queued", validating: "Validating task", preparing: "Preparing",
  building_image: "Building image", launching: "Launching", running_attempts: "Running attempts",
  collecting_results: "Collecting results", done: "Done",
};

const CATEGORY_LABELS = {
  solved: "Solved",
  tests_failed: "Tests failed",
  declared_done_with_failing_tests: "Declared done with failing tests",
  declared_done_after_warning: "Declared done after warning",
  stopped_without_completing: "Stopped without completing",
  agent_timeout: "Agent timed out",
  test_timeout: "Tests timed out",
  tests_not_run: "Tests never ran",
  tests_unparseable: "Test output unparseable",
  llm_error: "LLM error",
  no_results: "No results (infrastructure)",
  task_container_oom: "Task container out of memory",
};
export const categoryLabel = (category) => CATEGORY_LABELS[category] ?? humanize(category);

const VERDICTS = {
  learnable: ["Learnable", "good"], too_easy: ["Too easy", "warn"], too_hard: ["Too hard", "warn"],
  undetermined: ["Not enough runs", "muted"],
};
export function verdictBadge(verdict) {
  if (!verdict) return h("span", { class: "muted" }, "—");
  const [label, tone] = VERDICTS[verdict] ?? [humanize(verdict), "muted"];
  return h("span", { class: `badge verdict-${tone}` }, label);
}

// --- building blocks ------------------------------------------------------------

export const card = (title, ...children) =>
  h("section", { class: "card" }, title ? h("h2", { class: "card-title" }, title) : null, children);

export const tile = (label, value, sub) =>
  h("div", { class: "tile" }, h("div", { class: "tile-label" }, label), h("div", { class: "tile-value" }, value),
    sub ? h("div", { class: "tile-sub" }, sub) : null);

export const tiles = (...items) => h("div", { class: "tiles" }, items);

export function rateBar(passes, trials) {
  const rate = trials ? passes / trials : 0;
  return h("div", { class: "rate" },
    h("div", { class: "rate-bar" }, h("div", { class: "rate-fill", style: `width:${rate * 100}%` })),
    h("span", { class: "rate-text nowrap" }, trials ? `${passes}/${trials}` : "no runs"));
}

export function categoryBar(categories) {
  const entries = Object.entries(categories ?? {}).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  if (!total) return h("p", { class: "muted" }, "No failed attempts.");
  return h("div", { class: "categories" },
    h("div", { class: "category-bar" },
      entries.map(([name, n], i) => h("div", {
        class: `segment c${i % 6}`, style: `flex:${n}`, title: `${categoryLabel(name)}: ${n}`,
      }))),
    h("ul", { class: "legend" },
      entries.map(([name, n], i) => h("li", {}, h("span", { class: `swatch c${i % 6}` }), `${categoryLabel(name)} `,
        h("span", { class: "muted" }, n)))));
}

export function table(columns, rows, { onRowClick, empty = "Nothing here yet." } = {}) {
  if (!rows.length) return h("p", { class: "muted empty" }, empty);
  return h("table", { class: `table${onRowClick ? " clickable" : ""}` },
    h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.class }, c.label)))),
    h("tbody", {}, rows.map((row) => h("tr", { onclick: onRowClick ? () => onRowClick(row) : null },
      columns.map((c) => h("td", { class: c.class }, c.render(row)))))));
}

export function tabs(items, initial = 0, onChange) {
  const body = h("div", { class: "tab-body" });
  const buttons = items.map((item, i) => h("button", { class: "tab", type: "button", onclick: () => select(i) }, item.label));
  function select(i) {
    buttons.forEach((b, j) => b.classList.toggle("active", i === j));
    render(body, item(items[i]));
    onChange?.(i);
  }
  const item = (it) => it.render();
  select(initial);
  return h("div", { class: "tabs" }, h("div", { class: "tab-bar" }, buttons), body);
}

export const loading = (text = "Loading…") => h("p", { class: "muted state" }, text);
export const errorBox = (text) => h("div", { class: "error-box" }, text);
export const terminal = (text, cls = "") => h("pre", { class: `terminal ${cls}` }, text || "(empty)");

export function setBreadcrumbs(...items) {
  const crumbs = items.filter(Boolean);
  render(document.getElementById("breadcrumbs"),
    crumbs.map((c, i) => [
      i ? h("span", { class: "crumb-sep" }, "›") : null,
      c.href && i < crumbs.length - 1 ? h("a", { href: c.href }, c.label) : h("span", {}, c.label),
    ]));
}

/** Run `fn` now and every `ms` until it returns false; returns a stop function. */
export function poll(fn, ms) {
  let timer = null;
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    const keepGoing = await fn();
    if (keepGoing !== false && !stopped) timer = setTimeout(tick, ms);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}
