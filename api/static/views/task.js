import { api, errorMessage } from "../api.js";
import {
  card, categoryBar, chip, duration, errorBox, h, humanize, loading, money, outcomeBadge, pct, render,
  setBreadcrumbs, shortId, table, tile, tiles, time, verdictBadge,
} from "../components.js";
import { go } from "../router.js";
import { insightsCard } from "./insights.js";

export function taskView(container, { taskId }) {
  setBreadcrumbs({ label: "Dashboard", href: "#/" }, { label: taskId });
  render(container, loading());
  api.task(taskId).then((response) => {
    render(container, response.ok ? page(response.data) : errorBox(errorMessage(response, "Could not load the task")));
  });
}

function page(task) {
  const spec = task.spec ?? {};
  const rate = task.pass_rate;
  return [
    h("div", { class: "page-header" },
      h("div", {},
        h("p", { class: "eyebrow" }, "Task"),
        h("h1", {}, task.task_id),
        h("div", { class: "chips" },
          spec.difficulty ? chip(spec.difficulty) : null,
          spec.category ? chip(humanize(spec.category)) : null,
          spec.resource_class ? chip(`${spec.resource_class} resources`) : null,
          spec.max_agent_timeout_sec ? chip(`agent ≤ ${duration(spec.max_agent_timeout_sec)}`) : null,
          spec.max_test_timeout_sec ? chip(`tests ≤ ${duration(spec.max_test_timeout_sec)}`) : null)),
      h("a", { class: "button primary", href: "#/submit" }, "Run again")),
    spec.instruction
      ? h("details", { class: "card instruction" }, h("summary", {}, "Instruction given to the agent"), h("pre", { class: "prose" }, spec.instruction))
      : null,
    tiles(
      tile("Resolve rate", pct(rate.rate),
        rate.trials ? `${rate.passes}/${rate.trials} agent attempts · 95% CI ${pct(rate.interval_95[0])}–${pct(rate.interval_95[1])}` : "no agent attempts yet"),
      tile("Learnability", verdictBadge(task.learnability), "10-run rule: learnable if 2–7 of 10 pass"),
      tile("Runs", task.runs, `${task.agent_runs} with an LLM agent`),
      tile("Median attempt", duration(task.median_attempt_sec)),
      tile("Model spend", money(task.cost_usd)),
    ),
    card("Test results across agent attempts", heatmap(task.heatmap),
      h("p", { class: "muted small" }, "Each column is one attempt (oldest first). Tests that fail in every column point at the task or a capability gap rather than noise.")),
    h("div", { class: "grid-2" },
      card("Why attempts fail", categoryBar(task.failure_categories)),
      task.latest_validation ? validationCard(task.latest_validation) : card("Task validation", h("p", { class: "muted" }, "Not validated yet. Submit with a validation gate to check it with the oracle and nop agents."))),
    task.latest_agent_run_id ? insightsCard(task.latest_agent_run_id, { title: "Insights from the latest agent run" }) : null,
    card("Runs", runsTable(task.runs_list)),
  ];
}

function heatmap({ columns, rows }) {
  if (!columns.length) return h("p", { class: "muted" }, "No agent attempts yet.");
  const runGroups = [];
  for (const column of columns) {
    const last = runGroups.at(-1);
    if (last?.id === column.submission_id) last.span += 1;
    else runGroups.push({ id: column.submission_id, span: 1 });
  }
  const runHeader = h("tr", {}, h("th", {}),
    runGroups.map((g) => h("th", { class: "heat-run", colspan: g.span },
      h("a", { href: `#/runs/${g.id}`, title: `run ${g.id}` }, g.span > 1 ? `run ${shortId(g.id)}` : shortId(g.id).slice(0, 4)))),
    h("th", {}));
  const header = h("tr", {},
    h("th", { class: "heat-test" }, "Test"),
    columns.map((c) => h("th", { class: "heat-col", title: `run ${shortId(c.submission_id)} · attempt ${c.attempt}` },
      h("a", { href: `#/runs/${c.submission_id}/attempts/${c.attempt}`, class: c.resolved ? "pass" : "fail" }, c.resolved ? "✓" : "✗"))),
    h("th", { class: "num" }, "Pass rate"));
  const body = rows.map((row) => h("tr", {},
    h("td", { class: "heat-test mono" }, row.test),
    row.cells.map((status, i) => h("td", { class: "heat-cell" },
      h("a", {
        class: `cell ${status ?? "none"}`,
        href: `#/runs/${columns[i].submission_id}/attempts/${columns[i].attempt}`,
        title: `${row.test}: ${status ?? "not run"} (run ${shortId(columns[i].submission_id)}, attempt ${columns[i].attempt})`,
      }))),
    h("td", { class: "num" }, pct(row.pass_rate))));
  return h("div", { class: "heatmap-wrap" }, h("table", { class: "heatmap" }, h("thead", {}, runHeader, header), h("tbody", {}, body)));
}

function validationCard(report) {
  return card("Task validation",
    h("div", { class: "row" },
      h("span", { class: `badge ${report.passed ? "outcome-passed" : report.status === "running" ? "outcome-running" : "outcome-failed"}` },
        report.passed ? "Valid" : report.status === "completed" || report.status === "failed" ? "Problems found" : humanize(report.status)),
      h("span", { class: "muted" }, ` ${report.mode} validation · `, time(report.created_at))),
    report.findings?.length
      ? h("ul", { class: "plain-list" }, report.findings.map((f) =>
        h("li", {}, h("span", { class: `badge severity-${f.severity === "error" ? "high" : f.severity === "warning" ? "medium" : "low"}` }, f.severity), " ", f.message ?? f.title ?? f.check)))
      : h("p", { class: "muted" }, "No findings."));
}

function runsTable(runs) {
  return table(
    [
      { label: "When", render: (r) => time(r.created_at) },
      { label: "Outcome", render: (r) => outcomeBadge(r.outcome) },
      { label: "Agent", render: (r) => h("span", { class: "nowrap" }, r.agent, r.model ? h("span", { class: "muted" }, ` · ${r.model}`) : null) },
      { label: "Strategy", render: (r) => r.strategy },
      { label: "Resolved", class: "num", render: (r) => (r.resolved_attempts == null ? "—" : `${r.resolved_attempts}/${r.attempts}`) },
      { label: "Duration", class: "num", render: (r) => duration(r.duration_sec) },
      { label: "Run", render: (r) => h("span", { class: "mono muted" }, shortId(r.submission_id)) },
    ],
    runs,
    { onRowClick: (r) => go(`/runs/${r.submission_id}`) },
  );
}

