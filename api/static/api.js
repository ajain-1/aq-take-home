/** Thin JSON client: every call resolves to { ok, status, data } and never throws. */
export async function request(path, options) {
  try {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

export const api = {
  health: () => request("/health"),
  dashboard: () => request("/dashboard"),
  tasks: () => request("/tasks"),
  task: (taskId) => request(`/tasks/${encodeURIComponent(taskId)}`),
  status: (id) => request(`/status/${id}`),
  results: (id) => request(`/results/${id}`),
  insights: (id) => request(`/insights/${id}?narrative=false`),
  episodes: (id, attempt) => request(`/submissions/${id}/attempts/${attempt}/episodes`),
  recordingUrl: (id, attempt) => `/submissions/${id}/attempts/${attempt}/recording`,
  submit: (form) => request("/submit", { method: "POST", body: form }),
};

/** Human-readable message from an error response. Our 422s carry a string `detail` (plus
 * an optional `report`); FastAPI's own form validation returns a list of field errors. */
export function errorMessage(response, fallback = "Request failed") {
  const detail = response.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${d.loc?.slice(-1)[0] ?? "field"}: ${d.msg}`).join("; ");
  return response.status === 0 ? "API unreachable" : `${fallback} (HTTP ${response.status})`;
}
