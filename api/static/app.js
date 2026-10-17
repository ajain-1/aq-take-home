import { api } from "./api.js";
import { h, poll, render, setBreadcrumbs } from "./components.js";
import { createRouter } from "./router.js";
import { attemptView } from "./views/attempt.js";
import { dashboardView } from "./views/dashboard.js";
import { runView } from "./views/run.js";
import { submitView } from "./views/submit.js";
import { taskView } from "./views/task.js";

function notFound(container) {
  setBreadcrumbs({ label: "Dashboard", href: "#/" }, { label: "Not found" });
  render(container, h("p", { class: "muted state" }, "This page doesn't exist. ", h("a", { href: "#/" }, "Go to the dashboard.")));
}

const router = createRouter(
  [
    ["/", dashboardView],
    ["/tasks/:taskId", taskView],
    ["/runs/:id", runView],
    ["/runs/:id/attempts/:attempt", attemptView],
    ["/submit", submitView],
  ],
  document.getElementById("view"),
  notFound,
);
router.start();

poll(async () => {
  const { ok, data } = await api.health();
  const dot = (up, label) => h("span", { class: `dot ${up ? "up" : "down"}`, title: `${label} ${up ? "up" : "down"}` }, label);
  render(document.getElementById("health"),
    ok ? [dot(data.docker_available, "Docker"), dot(data.k8s_available, "Kubernetes")] : h("span", { class: "dot down" }, "API unreachable"));
}, 15000);
