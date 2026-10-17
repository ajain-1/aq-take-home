import { api } from "../api.js";
import { card, h, loading, render } from "../components.js";

/** Evidence-backed findings (runner/insights) for one finished run. Each finding lists
 * the verbatim quotes it rests on; unverified findings are withheld by the backend. */
export function insightsCard(submissionId, { title = "Insights", onLoaded } = {}) {
  const body = h("div", {}, loading("Analysing attempts…"));
  api.insights(submissionId).then((response) => {
    if (!response.ok) {
      render(body, h("p", { class: "muted" }, "No insights available for this run."));
      return;
    }
    onLoaded?.(response.data);
    render(body, findings(response.data));
  });
  return card(title, body);
}

function findings(report) {
  const items = (report.insights ?? []).filter((finding) => finding.category !== "attempt_failure");
  const learnability = report.outcome?.learnability;
  return [
    learnability ? h("p", { class: "muted" }, `Statistics: ${learnability.basis}.`) : null,
    items.length
      ? groupByCategory(items).map(([category, group]) => h("div", { class: "finding-group" },
        h("h4", {}, CATEGORY_TITLES[category] ?? category.replaceAll("_", " ")),
        h("div", { class: "findings" }, group.map((finding) => findingItem(finding, report.evidence)))))
      : h("p", { class: "muted" }, "Nothing notable: no consistent failures or task-quality signals."),
    report.rejected_insights?.length
      ? h("p", { class: "muted small" }, `${report.rejected_insights.length} finding(s) withheld because their evidence did not verify.`)
      : null,
  ];
}

const CATEGORY_TITLES = {
  consistent_test_failure: "Tests that fail in every attempt",
  hidden_requirement: "Possible task problems: tests check things the instruction never states",
  divergence: "What passing attempts did differently",
};

function groupByCategory(items) {
  const groups = new Map();
  for (const item of items) groups.set(item.category, [...(groups.get(item.category) ?? []), item]);
  return [...groups];
}

function findingItem(finding, evidence) {
  const quotes = (finding.evidence ?? []).map((id) => evidence[id]).filter(Boolean);
  return h("details", { class: "finding", "data-severity": finding.severity },
    h("summary", {},
      h("span", { class: `badge severity-${finding.severity}` }, finding.severity),
      h("span", { class: "finding-title" }, finding.title)),
    h("p", {}, finding.detail),
    quotes.length ? h("ul", { class: "evidence" }, quotes.map(evidenceItem)) : null);
}

function evidenceItem(item) {
  const where = [
    item.attempt != null ? `attempt ${item.attempt}` : null,
    item.episode != null ? `turn ${item.episode + 1}` : null,
    item.line != null ? `line ${item.line}` : null,
  ].filter(Boolean).join(" · ");
  return h("li", {},
    h("span", { class: `badge ${item.verified ? "test-passed" : "test-failed"}` }, item.verified ? "verified" : "unverified"),
    " ",
    item.kind === "absence" ? h("span", {}, "absent from instruction: ") : null,
    h("code", {}, item.quote),
    where ? h("span", { class: "muted small" }, ` — ${where}`) : null);
}
