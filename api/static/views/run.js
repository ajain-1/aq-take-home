import { api, errorMessage } from "../api.js";
import {
  PHASE_LABELS, attemptBadge, card, categoryLabel, chip, compact, duration, errorBox, h, loading,
  outcomeBadge, pct, poll, render, setBreadcrumbs, shortId, shortModel, table, tile, tiles, time,
  verdictBadge,
} from "../components.js";
import { insightsCard } from "./insights.js";

const STEPS = ["preparing", "building_image", "running_attempts", "collecting_results", "done"];
const TERMINAL = new Set(["completed", "failed"]);

export function runView(container, { id }) {
  setBreadcrumbs({ label: "Dashboard", href: "#/" }, { label: `Run ${shortId(id)}` });
  render(container, loading());

  return poll(async () => {
    const status = await api.status(id);
    if (!status.ok) {
      render(container, errorBox(errorMessage(status, "Could not load the run")));
      return status.status !== 404;
    }
    const run = status.data;
    setBreadcrumbs(
      { label: "Dashboard", href: "#/" },
      run.task_id ? { label: run.task_id, href: `#/tasks/${encodeURIComponent(run.task_id)}` } : null,
      { label: `Run ${shortId(id)}` },
    );
    if (!TERMINAL.has(run.status)) {
      render(container, header(run, null), liveProgress(run));
      return true;
    }
    const results = await api.results(id);
    render(container, header(run, results.data), finished(run, results.data));
    return false;
  }, 2500);
}

function runOutcome(run, results) {
  if (run.status === "queued") return "queued";
  if (run.status === "running") return "running";
  const summary = results?.summary;
  if (run.status === "failed" || !summary) return "error";
  if (summary.resolved_attempts === summary.n_attempts) return "passed";
  return summary.resolved_attempts ? "partial" : "failed";
}

function header(run, results) {
  const summary = results?.summary;
  return h("div", { class: "page-header" },
    h("div", {},
      h("p", { class: "eyebrow" }, "Run ", h("span", { class: "mono" }, shortId(run.submission_id))),
      h("h1", { class: "with-badge" }, run.task_id ?? "Run", outcomeBadge(runOutcome(run, results), "large")),
      h("div", { class: "facts" },
        h("span", {}, run.agent, run.model ? h("span", { class: "muted" }, ` · ${shortModel(run.model)}`) : null),
        h("span", {}, run.strategy === "adaptive" ? "adaptive strategy" : `${run.n_attempts} attempt${run.n_attempts === 1 ? "" : "s"}`),
        summary ? h("span", {}, `${summary.resolved_attempts}/${summary.n_attempts} resolved`) : null,
        results?.execution_time_sec != null ? h("span", {}, duration(results.execution_time_sec)) : null,
        h("span", {}, "started ", time(run.created_at)))),
    run.task_id ? h("a", { class: "button", href: `#/tasks/${encodeURIComponent(run.task_id)}` }, "Task overview") : null);
}

function stepper(run) {
  const steps = run.validation_id ? ["validating", ...STEPS] : STEPS;
  const current = run.progress.phase === "launching" ? "running_attempts" : run.progress.phase;
  const index = steps.indexOf(current);
  return h("ol", { class: "stepper" }, steps.map((step, i) =>
    h("li", { class: i < index ? "done" : i === index ? "current" : "" }, PHASE_LABELS[step])));
}

function liveProgress(run) {
  const attempts = run.progress.attempts;
  const total = run.progress.attempts_total || run.n_attempts;
  return [
    card(null, stepper(run),
      run.progress.phase === "building_image" ? h("p", { class: "muted" }, "Building the task image once; all attempts reuse it.") : null),
    card(`Attempts${total ? ` (${total})` : ""}`,
      attempts.length
        ? h("div", { class: "attempt-grid" }, attempts.map((a) => h("a", { class: "attempt-card live", href: `#/runs/${run.submission_id}/attempts/${a.index}` },
          h("div", { class: "attempt-card-top" }, h("strong", {}, `Attempt ${a.index}`), outcomeBadge(a.state === "pending" ? "queued" : "running")),
          h("div", { class: "muted small" }, `pod: ${a.state}`, a.retries ? ` · retried ${a.retries}×` : ""),
          a.reason ? h("div", { class: "muted small" }, a.reason) : null,
          h("div", { class: "link-hint" }, "Watch trajectory →"))))
        : h("p", { class: "muted" }, "Attempts start once the image is built.")),
  ];
}

function finished(run, results) {
  if (!results || !results.attempts?.length) {
    return card("This run did not produce results", errorBox(run.error ?? results?.error ?? "Unknown error"));
  }
  const summary = results.summary;
  const tokensIn = results.attempts.reduce((sum, a) => sum + (a.input_tokens ?? 0), 0);
  const tokensOut = results.attempts.reduce((sum, a) => sum + (a.output_tokens ?? 0), 0);
  const categories = {};
  const attemptCards = h("div", { class: "attempt-grid" }, results.attempts.map((a) => attemptCard(run, a, categories)));
  const insights = insightsCard(run.submission_id, {
    title: "Insights",
    onLoaded: (report) => {
      for (const a of report.attempts ?? []) categories[a.attempt]?.replaceChildren(categoryLabel(a.category));
    },
  });
  return [
    tiles(
      tile("Attempts resolved", `${summary.resolved_attempts}/${summary.n_attempts}`, pct(summary.pass_rate)),
      tile("Tests passing in every attempt", `${results.passed_tests}/${results.total_tests}`),
      tile("Duration", duration(results.execution_time_sec)),
      tile("Tokens", `${compact(tokensIn)} in`, `${compact(tokensOut)} out`),
    ),
    run.error ? errorBox(run.error) : null,
    run.strategy === "adaptive" && results.learnability ? adaptiveCard(run, results.learnability) : null,
    card("Attempts", attemptCards),
    results.attempts.length > 1 ? card("Tests across attempts", testsMatrix(run, results)) : card("Tests", testsMatrix(run, results)),
    insights,
  ];
}

function attemptCard(run, attempt, categories) {
  const category = h("span", {}, categoryLabel(attempt.category));
  categories[attempt.attempt] = category;
  return h("a", { class: `attempt-card ${attempt.resolved ? "ok" : "bad"}`, href: `#/runs/${run.submission_id}/attempts/${attempt.attempt}` },
    h("div", { class: "attempt-card-top" }, h("strong", {}, `Attempt ${attempt.attempt}`), attemptBadge(attempt)),
    h("div", { class: "attempt-tests" },
      h("div", { class: "rate-bar" }, h("div", { class: "rate-fill", style: `width:${attempt.total_tests ? (attempt.passed_tests / attempt.total_tests) * 100 : 0}%` })),
      h("span", { class: "small nowrap" }, `${attempt.passed_tests}/${attempt.total_tests} tests`)),
    attempt.resolved ? null : h("div", { class: "small" }, category),
    h("div", { class: "muted small" }, `${duration(attempt.duration_sec)} · ${compact(attempt.input_tokens)} tokens in`),
    attempt.infrastructure_issues?.length ? h("div", { class: "warn small" }, `⚠ ${attempt.infrastructure_issues.join("; ")}`) : null,
    attempt.error ? h("div", { class: "warn small" }, attempt.error) : null,
    h("div", { class: "link-hint" }, "View trajectory →"));
}

function testsMatrix(run, results) {
  const byAttempt = results.attempts.map((a) => Object.fromEntries((a.tests ?? []).map((t) => [t.name, t.status])));
  return table(
    [
      { label: "Test", class: "mono", render: (t) => t.name },
      ...results.attempts.map((a, i) => ({
        label: `#${a.attempt}`,
        class: "center",
        render: (t) => h("a", { class: `cell ${byAttempt[i][t.name] ?? "none"}`, href: `#/runs/${run.submission_id}/attempts/${a.attempt}`, title: byAttempt[i][t.name] ?? "not run" }),
      })),
      { label: "Pass rate", class: "num", render: (t) => pct(t.pass_rate) },
    ],
    [...results.tests].sort((a, b) => a.pass_rate - b.pass_rate),
    { empty: "No test results were recorded." },
  );
}

function adaptiveCard(run, learnability) {
  const saved = learnability.estimated_savings_vs_target;
  return card("Adaptive strategy",
    h("div", { class: "row gap" },
      verdictBadge(learnability.classification),
      h("span", {}, `${learnability.passing_runs} passed · ${learnability.failing_runs} failed after ${learnability.attempts_used} of ${learnability.target_runs} runs`),
      saved?.attempts ? chip(`saved ${saved.attempts} runs (~$${saved.cost_usd.toFixed(2)})`) : null),
    h("p", { class: "muted small" }, `Stopped as soon as the 10-run classification could no longer change${learnability.confidence < 1 ? ` (confidence ${learnability.confidence})` : ""}.`),
    run.progress.waves?.length
      ? h("div", { class: "chips" }, run.progress.waves.map((w) => chip(`wave ${w.index + 1}: attempts ${w.offset}–${w.offset + w.size - 1}`)))
      : null);
}

