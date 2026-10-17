"use strict";

const STATUS_POLL_MS = 2500;
const LIST_POLL_MS = 5000;
const TERMINAL = new Set(["completed", "failed"]);

const state = { selectedId: null, statusTimer: null, file: null };

/** Build a DOM element; string children become text nodes, so content is never parsed as HTML. */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Replace an element's children, skipping empty slots (replaceChildren would print "null"). */
function render(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((child) => child != null && child !== false));
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, data };
}

const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
const fmtSec = (sec) => (sec == null ? "—" : sec < 90 ? `${sec.toFixed(1)}s` : `${(sec / 60).toFixed(1)}m`);
const badge = (text, kind = text) => h("span", { class: `badge ${kind}` }, text);
const kv = (pairs) => h("div", { class: "kv" }, pairs.map(([k, v]) => h("div", {}, h("span", {}, k), h("span", {}, v ?? "—"))));
const collapsible = (title, text) => text ? h("details", {}, h("summary", {}, title), h("pre", {}, text)) : null;

async function refreshHealth() {
  const { data } = await api("/health");
  const el = document.getElementById("health");
  el.textContent = data ? `docker ${data.docker_available ? "up" : "down"} · k8s ${data.k8s_available ? "up" : "down"}` : "API unreachable";
}

function setupUpload() {
  const zone = document.getElementById("dropzone");
  const input = document.getElementById("file-input");
  const button = document.getElementById("submit-button");
  const error = document.getElementById("submit-error");

  const choose = (file) => {
    state.file = file;
    zone.classList.toggle("ready", Boolean(file));
    document.getElementById("dropzone-text").textContent = file ? file.name : "Drop a task .zip here or click to choose";
    button.disabled = !file;
  };

  input.addEventListener("change", () => choose(input.files[0]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("active"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("active"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("active");
    choose(e.dataTransfer.files[0]);
  });

  document.getElementById("submit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    button.disabled = true;
    const form = new FormData();
    form.append("file", state.file);
    form.append("n_attempts", document.getElementById("n-attempts").value);
    form.append("agent", document.getElementById("agent").value);
    const { ok, data } = await api("/submit", { method: "POST", body: form });
    button.disabled = false;
    if (!ok) {
      error.textContent = data?.detail ?? "Submission failed";
      error.hidden = false;
      return;
    }
    choose(null);
    input.value = "";
    await refreshList();
    select(data.submission_id);
  });
}

async function refreshList() {
  const { data } = await api("/submissions");
  const list = document.getElementById("submission-list");
  render(list, ...(data ?? []).map((s) => {
    const outcome = s.summary ? `${s.summary.resolved_attempts}/${s.summary.n_attempts} resolved` : s.phase;
    return h("li", { class: s.submission_id === state.selectedId ? "selected" : "", onclick: () => select(s.submission_id) },
      h("div", {}, h("strong", {}, s.task_id ?? s.submission_id), " ", badge(s.status)),
      h("div", { class: "meta" }, h("span", {}, `${s.agent} · ${outcome}`), h("span", {}, fmtTime(s.created_at))));
  }));
}

function select(id) {
  state.selectedId = id;
  if (location.hash !== `#${id}`) location.hash = id;
  clearTimeout(state.statusTimer);
  const detail = document.getElementById("detail");
  render(detail,
    h("div", { id: "progress" }, h("p", { class: "empty" }, "Loading…")),
    h("div", { id: "results" }),
    h("div", { id: "trajectory" }),
  );
  refreshList();
  pollStatus(id);
}

async function pollStatus(id) {
  const { ok, data } = await api(`/status/${id}`);
  if (id !== state.selectedId) return;
  if (!ok) {
    render(document.getElementById("progress"), h("p", { class: "error" }, data?.detail ?? "Not found"));
    return;
  }
  renderProgress(data);
  if (TERMINAL.has(data.status)) {
    const results = await api(`/results/${id}`);
    if (id === state.selectedId && results.ok) renderResults(results.data);
    refreshList();
  } else {
    state.statusTimer = setTimeout(() => pollStatus(id), STATUS_POLL_MS);
  }
  if (!document.getElementById("trajectory").hasChildNodes()) renderTrajectoryPicker(data);
}

function renderProgress(s) {
  const p = s.progress;
  render(document.getElementById("progress"),
    h("div", { class: "detail-header" }, h("h2", {}, s.task_id ?? s.submission_id), badge(s.status), badge(p.phase, "phase")),
    kv([
      ["Submission", s.submission_id], ["Agent", s.agent], ["Model", s.model],
      ["Created", fmtTime(s.created_at)], ["Started", fmtTime(s.started_at)], ["Finished", fmtTime(s.finished_at)],
      ["Attempts", `${p.succeeded} succeeded · ${p.running} running · ${p.pending} pending · ${p.failed} failed (of ${p.attempts_total})`],
    ]),
    s.error ? h("p", { class: "error" }, s.error) : null,
    h("div", { class: "attempt-chips" }, p.attempts.map((a) =>
      h("div", { class: "chip" }, `Attempt ${a.index} `, badge(a.state), a.retries ? ` · ${a.retries} retr${a.retries > 1 ? "ies" : "y"}` : "",
        a.reason ? h("small", {}, a.reason) : null))),
  );
}

function renderResults(r) {
  const container = document.getElementById("results");
  if (!r.summary) {
    render(container, h("h3", {}, "Results"), h("p", { class: "error" }, r.error ?? "No results"));
    return;
  }
  const attemptPanel = h("div", {});
  const tabs = h("div", { class: "tabs" });
  const showAttempt = (index) => {
    [...tabs.children].forEach((tab, i) => tab.classList.toggle("active", i === index));
    render(attemptPanel, renderAttempt(r.attempts[index]));
  };
  tabs.append(...r.attempts.map((a, i) =>
    h("button", { type: "button", onclick: () => showAttempt(i) }, `Attempt ${a.attempt} `, badge(a.status === "error" ? "error" : a.resolved ? "passed" : "failed"))));

  render(container,
    h("h3", {}, "Results ", badge(r.passed ? "passed" : "failed")),
    kv([
      ["Resolved attempts", `${r.summary.resolved_attempts}/${r.summary.n_attempts}`],
      ["Pass rate", `${Math.round(r.summary.pass_rate * 100)}%`],
      ["Tests passing in every attempt", `${r.passed_tests}/${r.total_tests}`],
      ["Tests not run", r.summary.tests_not_run_attempts ?? 0],
      ["Errored attempts", r.summary.errored_attempts],
      ["Execution time", fmtSec(r.execution_time_sec)],
    ]),
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Test"), h("th", {}, "Passed"), h("th", {}, "Failed"), h("th", {}, "Pass rate"))),
      h("tbody", {}, r.tests.map((t) => h("tr", {},
        h("td", { class: "name" }, t.name), h("td", {}, t.passed), h("td", {}, t.failed),
        h("td", {}, badge(`${Math.round(t.pass_rate * 100)}%`, t.failed ? "failed" : "passed")))))),
    h("h3", {}, "Attempts"), tabs, attemptPanel,
  );
  if (r.attempts.length) showAttempt(0);
}

function renderAttempt(a) {
  if (a.status === "error") return h("p", { class: "error" }, a.error);
  return h("div", {},
    kv([
      ["Outcome", a.resolved ? "resolved" : "unresolved"], ["Failure mode", a.failure_mode],
      ["Duration", fmtSec(a.duration_sec)], ["Agent time", fmtSec(a.agent_duration_sec)], ["Test time", fmtSec(a.test_duration_sec)],
      ["Tokens (in / out)", `${a.input_tokens ?? "—"} / ${a.output_tokens ?? "—"}`], ["Retries", a.retries],
    ]),
    h("table", {}, h("tbody", {}, a.tests.map((t) =>
      h("tr", {}, h("td", { class: "name" }, t.name), h("td", {}, badge(t.status)))))),
    collapsible("Pytest output", a.pytest_output),
  );
}

function renderTrajectoryPicker(status) {
  const container = document.getElementById("trajectory");
  const body = h("div", {});
  const tabs = h("div", { class: "tabs" });
  const load = async (index) => {
    [...tabs.children].forEach((tab, i) => tab.classList.toggle("active", i === index));
    render(body, h("p", { class: "empty" }, "Loading trajectory…"));
    const { ok, data } = await api(`/submissions/${status.submission_id}/attempts/${index}/episodes`);
    render(body, ok ? renderTrajectory(data) : h("p", { class: "empty" }, data?.detail ?? "Unavailable"));
  };
  tabs.append(...Array.from({ length: status.n_attempts }, (_, i) =>
    h("button", { type: "button", onclick: () => load(i) }, `Attempt ${i}`)));
  render(container,
    h("h3", {}, "Agent trajectory ", h("button", { type: "button", class: "link", onclick: () => load(Math.max(0, [...tabs.children].findIndex((t) => t.classList.contains("active")))) }, "refresh")),
    tabs, body,
  );
  load(0);
}

function renderTrajectory(t) {
  if (!t.episodes.length) return h("p", { class: "empty" }, "No agent turns recorded yet.");
  return h("div", {},
    h("p", { class: "label" }, `${t.episodes.length} turns`),
    t.episodes.map(renderEpisode),
    collapsible("Terminal after agent finished", t.panes["post-agent"]),
    collapsible("Terminal after tests", t.panes["post-test"]),
  );
}

function renderEpisode(e) {
  const r = typeof e.response === "object" && e.response ? e.response : null;
  return h("div", { class: "episode" },
    h("div", { class: "episode-head" }, h("strong", {}, `Turn ${e.index + 1}`), r?.is_task_complete ? badge("marked complete", "passed") : null),
    r ? [
      h("p", {}, h("span", { class: "label" }, "State: "), r.state_analysis),
      h("p", {}, h("span", { class: "label" }, "Plan: "), r.explanation),
      (r.commands ?? []).map((c) => h("div", { class: "command" },
        h("div", { class: "meta" }, `${c.is_blocking ? "blocking" : "non-blocking"} · ${c.timeout_sec}s timeout`),
        h("pre", {}, c.keystrokes))),
    ] : collapsible("Raw response", typeof e.response === "string" ? e.response : "No response recorded"),
    collapsible("Terminal output after this turn", e.observation),
    e.index === 0 ? collapsible("Initial prompt", e.prompt) : null,
  );
}

function start() {
  setupUpload();
  refreshHealth();
  refreshList();
  setInterval(refreshList, LIST_POLL_MS);
  window.addEventListener("hashchange", () => {
    const id = location.hash.slice(1);
    if (id && id !== state.selectedId) select(id);
  });
  if (location.hash.length > 1) select(location.hash.slice(1));
}

start();
