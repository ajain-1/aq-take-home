import { api, errorMessage } from "../api.js";
import { card, h, render, setBreadcrumbs } from "../components.js";
import { go } from "../router.js";

const AGENTS = [
  ["terminus-1", "terminus-1 — the LLM agent (uses inference)"],
  ["oracle", "oracle — runs solution.sh; checks the task and infrastructure"],
  ["nop", "nop — does nothing; tests should fail"],
];
const VALIDATION = [
  ["", "None"],
  ["static", "Static checks — reject obviously broken tasks instantly"],
  ["full", "Full — also run the oracle and nop agents before any LLM attempt"],
];

export function submitView(container) {
  setBreadcrumbs({ label: "Dashboard", href: "#/" }, { label: "New run" });
  const state = { file: null };

  const fileInput = h("input", { type: "file", accept: ".zip", hidden: true, onchange: () => setFile(fileInput.files[0]) });
  const dropText = h("span", {}, "Drop a task .zip here, or click to choose");
  const dropzone = h("label", { class: "dropzone" }, fileInput, h("div", { class: "drop-icon" }, "⬆"), dropText,
    h("span", { class: "muted small" }, "A zipped task directory with task.yaml, Dockerfile, run-tests.sh and tests/"));
  for (const type of ["dragenter", "dragover"]) dropzone.addEventListener(type, (e) => { e.preventDefault(); dropzone.classList.add("over"); });
  for (const type of ["dragleave", "drop"]) dropzone.addEventListener(type, () => dropzone.classList.remove("over"));
  dropzone.addEventListener("drop", (e) => { e.preventDefault(); setFile(e.dataTransfer.files[0]); });

  const agent = select("agent", AGENTS);
  const strategy = select("strategy", [["fixed", "Fixed number of attempts"], ["adaptive", "Adaptive — stop once learnability is decided"]]);
  const attempts = h("input", { type: "number", name: "n_attempts", min: 1, max: 10, value: 1 });
  const confidence = select("confidence", [["1.0", "Exact (same answer as 10 runs)"], ["0.95", "95% confident"], ["0.9", "90% confident"]]);
  const validation = select("validation", VALIDATION);
  const attemptsField = field("Attempts", attempts, "Run in parallel as one Kubernetes Job");
  const confidenceField = field("Stopping rule", confidence, "Runs in waves and stops early; up to 10 attempts");
  const feedback = h("div", { class: "feedback" });
  const button = h("button", { class: "button primary", type: "submit", disabled: true }, "Start run");

  function setFile(file) {
    state.file = file ?? null;
    render(dropText, file ? h("strong", {}, file.name) : "Drop a task .zip here, or click to choose");
    dropzone.classList.toggle("has-file", Boolean(file));
    button.disabled = !file;
  }

  function syncStrategy() {
    const adaptive = strategy.value === "adaptive";
    attemptsField.hidden = adaptive;
    confidenceField.hidden = !adaptive;
  }
  strategy.addEventListener("change", syncStrategy);
  syncStrategy();

  async function submit(event) {
    event.preventDefault();
    const form = new FormData();
    form.append("file", state.file);
    form.append("agent", agent.value);
    if (validation.value) form.append("validation", validation.value);
    if (strategy.value === "adaptive") {
      form.append("strategy", "adaptive");
      form.append("confidence", confidence.value);
    } else {
      form.append("n_attempts", attempts.value);
    }
    button.disabled = true;
    render(feedback, h("p", { class: "muted" }, "Uploading…"));
    const response = await api.submit(form);
    button.disabled = false;
    if (response.ok) {
      go(`/runs/${response.data.submission_id}`);
      return;
    }
    render(feedback, rejection(response));
  }

  render(container,
    h("div", { class: "page-header" }, h("div", {}, h("h1", {}, "New run"), h("p", { class: "subtitle" }, "Upload a task and choose how to run it."))),
    card(null,
      h("form", { class: "submit-form", onsubmit: submit },
        dropzone,
        h("div", { class: "form-grid" },
          field("Agent", agent),
          field("Strategy", strategy),
          attemptsField,
          confidenceField,
          field("Validation before running", validation)),
        h("div", { class: "form-actions" }, button),
        feedback)));
}

function select(name, options) {
  return h("select", { name }, options.map(([value, label]) => h("option", { value }, label)));
}

function field(label, control, hint) {
  return h("label", { class: "field" }, h("span", { class: "field-label" }, label), control,
    hint ? h("span", { class: "muted small" }, hint) : null);
}

/** A 422 carries a message and, for a failed validation gate, the validation report. */
function rejection(response) {
  const report = response.data?.report;
  return h("div", { class: "error-box" },
    h("strong", {}, errorMessage(response, "Submission failed")),
    report?.findings?.length
      ? h("ul", { class: "plain-list" }, report.findings.map((f) =>
        h("li", {}, h("span", { class: `badge severity-${f.severity === "error" ? "high" : f.severity === "warning" ? "medium" : "low"}` }, f.severity), " ", f.message)))
      : null);
}
