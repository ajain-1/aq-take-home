import { api, errorMessage } from "../api.js";
import {
  PHASE_LABELS, card, categoryBar, compact, duration, errorBox, h, loading, money, outcomeBadge, pct,
  poll, rateBar, render, setBreadcrumbs, shortId, table, tile, tiles, time, verdictBadge,
} from "../components.js";
import { go } from "../router.js";

export function dashboardView(container) {
  setBreadcrumbs({ label: "Dashboard" });
  render(container, loading());

  return poll(async () => {
    const [dashboard, tasks] = await Promise.all([api.dashboard(), api.tasks()]);
    if (!dashboard.ok || !tasks.ok) {
      render(container, errorBox(errorMessage(dashboard.ok ? tasks : dashboard, "Could not load the dashboard")));
      return true;
    }
    render(container, page(dashboard.data, tasks.data));
    return dashboard.data.active_runs.length > 0;
  }, 5000);
}

function page(d, tasks) {
  const rate = d.pass_rate;
  return [
    h("div", { class: "page-header" },
      h("div", {}, h("h1", {}, "Dashboard"), h("p", { class: "subtitle" }, "How agents are doing across every task you've submitted."))),
    tiles(
      tile("Tasks", d.tasks),
      tile("Runs", d.runs, "submissions, incl. oracle checks"),
      tile("Agent attempts", d.agent_attempts),
      tile("Resolve rate", pct(rate.rate),
        rate.trials ? `${rate.passes}/${rate.trials} · 95% CI ${pct(rate.interval_95[0])}–${pct(rate.interval_95[1])}` : "no agent attempts yet"),
      tile("Median attempt", duration(d.median_attempt_sec)),
      tile("Model spend", money(d.cost_usd), `${compact(d.tokens.input)} in · ${compact(d.tokens.output)} out tokens`),
    ),
    d.active_runs.length ? card("Running now", h("div", { class: "active-runs" }, d.active_runs.map(activeRun))) : null,
    card("Tasks", tasksTable(tasks)),
    card("Why agent attempts fail", categoryBar(d.failure_categories)),
  ];
}

function activeRun(run) {
  return h("a", { class: "active-run", href: `#/runs/${run.submission_id}` },
    h("div", { class: "active-run-top" }, h("strong", {}, run.task_id ?? "…"), outcomeBadge(run.outcome)),
    h("div", { class: "muted" }, PHASE_LABELS[run.phase] ?? run.phase,
      run.attempts_total ? ` · ${run.attempts_running}/${run.attempts_total} attempts running` : ""),
    h("div", { class: "muted small" }, `${run.agent} · started `, time(run.created_at), ` · ${shortId(run.submission_id)}`));
}

function tasksTable(tasks) {
  return table(
    [
      { label: "Task", render: (t) => h("a", { class: "strong", href: `#/tasks/${encodeURIComponent(t.task_id)}` }, t.task_id) },
      { label: "Resolve rate (agent attempts)", class: "w-rate", render: (t) => rateBar(t.pass_rate.passes, t.pass_rate.trials) },
      { label: "Learnability", render: (t) => verdictBadge(t.learnability) },
      { label: "Runs", class: "num", render: (t) => t.runs },
      { label: "Median attempt", class: "num", render: (t) => duration(t.median_attempt_sec) },
      { label: "Last run", render: (t) => h("span", { class: "nowrap" }, outcomeBadge(t.last_run.outcome), " ", time(t.last_run.created_at)) },
    ],
    tasks,
    { onRowClick: (t) => go(`/tasks/${encodeURIComponent(t.task_id)}`), empty: "No runs yet — start one with “New run”." },
  );
}
