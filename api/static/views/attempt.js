import { api, errorMessage } from "../api.js";
import {
  attemptBadge, categoryLabel, compact, duration, errorBox, h, loading, outcomeBadge, poll, render,
  setBreadcrumbs, shortId, shortModel, tabs, terminal, testBadge, tile, tiles,
} from "../components.js";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);
const PLAYER_VERSION = "3.8.0";
const CONFIRMATION_MARKER = "TESTS FAILED! Are you sure";
const TIMEOUT_MARKER = "timed out after";

export function attemptView(container, params) {
  const id = params.id;
  const index = Number(params.attempt);
  const state = { index, selected: null, followLatest: true, run: null, attempt: null, trajectory: null, keyHandler: null };
  render(container, loading());

  const stop = poll(async () => {
    const status = await api.status(id);
    if (!status.ok) {
      render(container, errorBox(errorMessage(status, "Could not load the run")));
      return false;
    }
    state.run = status.data;
    const done = TERMINAL_STATUSES.has(state.run.status);
    const [episodes, results] = await Promise.all([api.episodes(id, index), done ? api.results(id) : null]);
    state.trajectory = episodes.ok ? episodes.data : null;
    state.attempt = results?.data?.attempts?.find((a) => a.attempt === index) ?? null;
    setBreadcrumbs(
      { label: "Dashboard", href: "#/" },
      state.run.task_id ? { label: state.run.task_id, href: `#/tasks/${encodeURIComponent(state.run.task_id)}` } : null,
      { label: `Run ${shortId(id)}`, href: `#/runs/${id}` },
      { label: `Attempt ${index}` },
    );
    renderPage(container, state, results?.data, !done);
    return !done;
  }, 4000);

  return () => {
    stop();
    if (state.keyHandler) document.removeEventListener("keydown", state.keyHandler);
  };
}

function renderPage(container, state, results, live) {
  const { run, attempt, trajectory } = state;
  const turns = trajectory ? buildTurns(trajectory, attempt) : [];
  if (state.followLatest && turns.length) state.selected = live ? turns.length - 1 : 0;
  state.selected = Math.min(state.selected ?? 0, Math.max(turns.length - 1, 0));

  const scrollTop = container.querySelector(".timeline")?.scrollTop;
  render(container,
    header(run, state.index, attempt, results, live),
    attempt ? summaryTiles(attempt) : null,
    attempt?.infrastructure_issues?.length ? errorBox(`Infrastructure: ${attempt.infrastructure_issues.join("; ")}`) : null,
    attempt?.error ? errorBox(attempt.error) : null,
    tabs([
      { label: `Trajectory${turns.length ? ` · ${turns.filter((t) => t.kind === "turn").length} turns` : ""}`, render: () => trajectoryPane(state, turns, live) },
      { label: attempt ? `Tests · ${attempt.passed_tests}/${attempt.total_tests}` : "Tests", render: () => testsPane(attempt, live) },
      { label: "Pytest output", render: () => terminal(attempt?.pytest_output ?? (live ? "Tests run after the agent finishes." : "No pytest output recorded.")) },
      { label: "Terminal replay", render: () => replayPane(run.submission_id, state.index, trajectory) },
    ], state.tab ?? 0, (i) => { state.tab = i; }),
  );
  const timeline = container.querySelector(".timeline");
  if (timeline && scrollTop != null && !live) timeline.scrollTop = scrollTop;
  installKeys(state, turns, container, live);
}

function header(run, current, attempt, results, live) {
  const siblings = (results?.attempts ?? run.progress.attempts.map((a) => ({ attempt: a.index }))).map((a) => a.attempt);
  return h("div", { class: "page-header" },
    h("div", {},
      h("p", { class: "eyebrow" }, run.task_id, " · run ", h("span", { class: "mono" }, shortId(run.submission_id))),
      h("h1", { class: "with-badge" }, `Attempt ${current}`,
        live ? outcomeBadge("running", "large") : attempt ? attemptBadge(attempt) : outcomeBadge("error", "large")),
      h("div", { class: "facts" },
        h("span", {}, run.agent, run.model ? h("span", { class: "muted" }, ` · ${shortModel(run.model)}`) : null),
        attempt && !attempt.resolved ? h("span", {}, categoryLabel(attempt.category)) : null)),
    siblings.length > 1
      ? h("div", { class: "pager" }, h("span", { class: "muted small" }, "Attempts"),
        siblings.map((n) => h("a", { class: `pill${n === current ? " active" : ""}`, href: `#/runs/${run.submission_id}/attempts/${n}` }, n)))
      : null);
}

function summaryTiles(attempt) {
  return tiles(
    tile("Tests passed", `${attempt.passed_tests}/${attempt.total_tests}`),
    tile("Agent time", duration(attempt.agent_duration_sec)),
    tile("Test time", duration(attempt.test_duration_sec)),
    tile("Tokens", `${compact(attempt.input_tokens)} in`, `${compact(attempt.output_tokens)} out`),
    tile("Retries", attempt.retries ?? 0, "pod restarts after infra failures"),
  );
}

// --- trajectory ----------------------------------------------------------------

function extract(text, start, end) {
  if (!text) return null;
  const from = text.indexOf(start);
  if (from < 0) return null;
  const rest = text.slice(from + start.length);
  const to = end ? rest.indexOf(end) : -1;
  return (to >= 0 ? rest.slice(0, to) : rest).trim();
}

function buildTurns(trajectory, attempt) {
  const episodes = trajectory.episodes;
  const turns = [];
  const firstPrompt = episodes[0]?.prompt;
  if (firstPrompt) {
    turns.push({
      kind: "task",
      title: "Task given to the agent",
      instruction: extract(firstPrompt, "Instruction:\n", "\n\nYour response must be") ?? firstPrompt,
      screen: extract(firstPrompt, "The current terminal state is:\n"),
      prompt: firstPrompt,
    });
  }
  episodes.forEach((episode, i) => {
    const response = typeof episode.response === "object" && episode.response ? episode.response : null;
    // The prompt is written before the model replies, so the newest turn of a live
    // attempt has no response yet.
    const pending = episode.response == null;
    const observation = episode.observation ?? (i === episodes.length - 1 ? trajectory.panes?.["post-agent"] : null);
    turns.push({
      kind: "turn",
      number: i + 1,
      pending,
      title: pending ? "Waiting for the model…" : response?.explanation || (response ? "No plan given" : "Unparseable response"),
      state: response?.state_analysis,
      commands: response?.commands ?? [],
      done: Boolean(response?.is_task_complete),
      warned: Boolean(episode.observation?.includes(CONFIRMATION_MARKER)),
      timedOut: Boolean(episode.observation?.startsWith("Previous command:") && episode.observation.includes(TIMEOUT_MARKER)),
      raw: response || pending ? null : String(episode.response),
      observation,
      final: i === episodes.length - 1,
    });
  });
  if (attempt) {
    turns.push({ kind: "verdict", title: attempt.resolved ? "Tests passed" : "Tests failed", attempt });
  }
  return turns;
}

function trajectoryPane(state, turns, live) {
  if (!turns.length) {
    return h("p", { class: "muted state" }, live ? "Waiting for the agent's first turn…" : "No trajectory was recorded for this attempt.");
  }
  const detail = h("div", { class: "turn-detail" });
  const items = turns.map((turn, i) => h("button", {
    type: "button",
    class: `timeline-item kind-${turn.kind}${i === state.selected ? " active" : ""}`,
    onclick: () => select(i, true),
  }, timelineLabel(turn)));

  function select(i, manual) {
    state.selected = i;
    if (manual) state.followLatest = i === turns.length - 1 && live;
    items.forEach((item, j) => item.classList.toggle("active", i === j));
    items[i].scrollIntoView({ block: "nearest" });
    render(detail, turnDetail(turns[i], turns.filter((t) => t.kind === "turn").length));
  }
  state.select = select;

  const pane = h("div", { class: "trajectory" },
    h("div", { class: "timeline" }, items, live ? h("div", { class: "timeline-live" }, "● agent is working…") : null,
      h("p", { class: "muted small hint" }, "Use ↑ ↓ or j k to step through turns")),
    detail);
  select(state.selected, false);
  return pane;
}

function timelineLabel(turn) {
  if (turn.kind === "task") return [h("span", { class: "tl-num" }, "▶"), h("span", { class: "tl-title" }, turn.title)];
  if (turn.kind === "verdict") {
    return [h("span", { class: `tl-num ${turn.attempt.resolved ? "pass" : "fail"}` }, turn.attempt.resolved ? "✓" : "✗"),
      h("span", { class: "tl-title" }, `${turn.title} · ${turn.attempt.passed_tests}/${turn.attempt.total_tests}`)];
  }
  return [
    h("span", { class: "tl-num" }, turn.number),
    h("span", { class: "tl-body" },
      h("span", { class: "tl-title" }, turn.title),
      h("span", { class: "tl-meta" },
        turn.pending ? "thinking" : `${turn.commands.length} command${turn.commands.length === 1 ? "" : "s"}`,
        turn.done ? h("span", { class: "marker done" }, "declared done") : null,
        turn.warned ? h("span", { class: "marker warn" }, "warned: tests failing") : null,
        turn.timedOut ? h("span", { class: "marker warn" }, "command timed out") : null)),
  ];
}

function turnDetail(turn, totalTurns) {
  if (turn.kind === "task") {
    return [
      h("h3", {}, "Task given to the agent"),
      h("pre", { class: "prose" }, turn.instruction),
      turn.screen ? [h("h4", {}, "Terminal at start"), terminal(turn.screen)] : null,
      h("details", {}, h("summary", { class: "muted" }, "Full system prompt"), h("pre", { class: "prose small" }, turn.prompt)),
    ];
  }
  if (turn.kind === "verdict") {
    return [
      h("h3", {}, turn.title, " ", attemptBadge(turn.attempt)),
      h("ul", { class: "test-list" }, (turn.attempt.tests ?? []).map((t) => h("li", {}, testBadge(t.status), h("span", { class: "mono" }, t.name)))),
    ];
  }
  return [
    h("div", { class: "turn-head" },
      h("h3", {}, `Turn ${turn.number}`, h("span", { class: "muted" }, ` of ${totalTurns}`)),
      turn.done ? h("span", { class: "marker done" }, "agent declared the task complete") : null),
    turn.pending ? h("p", { class: "muted" }, "The agent has sent this turn's prompt and is waiting for the model's reply.") : null,
    turn.state ? section("What the agent saw", h("p", {}, turn.state)) : null,
    turn.pending ? null : section("What it decided", h("p", {}, turn.title)),
    turn.raw ? section("Raw response", terminal(turn.raw)) : null,
    turn.commands.length
      ? section("Commands sent", h("div", { class: "commands" }, turn.commands.map((c) =>
        h("div", { class: "command" },
          h("pre", { class: "terminal command-keys" }, h("span", { class: "prompt" }, "$ "), c.keystrokes.replace(/\n$/, "")),
          h("div", { class: "muted small" }, c.is_blocking ? `waited for completion · up to ${c.timeout_sec}s` : `sent without waiting · ${c.timeout_sec}s`)))))
      : null,
    turn.warned ? h("div", { class: "callout warn" }, "The harness detected failing tests and asked the agent to confirm before finishing.") : null,
    turn.observation
      ? section(turn.final ? "Terminal when the agent stopped" : "Terminal after these commands", terminal(turn.observation, "observation"))
      : null,
  ];
}

const section = (title, body) => h("div", { class: "turn-section" }, h("h4", {}, title), body);

function installKeys(state, turns, container, live) {
  if (state.keyHandler) document.removeEventListener("keydown", state.keyHandler);
  state.keyHandler = (event) => {
    if (!container.querySelector(".trajectory") || ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) return;
    const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[event.key];
    if (!step || !state.select) return;
    event.preventDefault();
    const next = Math.max(0, Math.min(turns.length - 1, state.selected + step));
    state.select(next, true);
    state.followLatest = live && next === turns.length - 1;
  };
  document.addEventListener("keydown", state.keyHandler);
}

// --- other tabs ------------------------------------------------------------------

function testsPane(attempt, live) {
  if (!attempt) return h("p", { class: "muted state" }, live ? "Tests run after the agent finishes." : "No test results recorded.");
  if (!attempt.tests?.length) return h("p", { class: "muted state" }, "The tests did not produce parseable results.");
  const sorted = [...attempt.tests].sort((a, b) => (a.status === b.status ? 0 : a.status === "failed" ? -1 : 1));
  return h("ul", { class: "test-list" }, sorted.map((t) => h("li", {}, testBadge(t.status), h("span", { class: "mono" }, t.name))));
}

function replayPane(submissionId, attemptIndex, trajectory) {
  if (!trajectory?.has_recording) return h("p", { class: "muted state" }, "No terminal recording for this attempt.");
  const target = h("div", { class: "player" }, loading("Loading player…"));
  loadPlayer().then((player) => {
    target.replaceChildren();
    player.create(api.recordingUrl(submissionId, attemptIndex), target, { fit: "width", idleTimeLimit: 2, terminalFontSize: "13px" });
  }).catch(() => render(target, errorBox("Could not load the asciinema player.")));
  return [h("p", { class: "muted small" }, "Full session recording. Markers on the timeline are the agent's turns."), target];
}

let playerPromise = null;
function loadPlayer() {
  playerPromise ??= new Promise((resolve, reject) => {
    const base = `https://cdn.jsdelivr.net/npm/asciinema-player@${PLAYER_VERSION}/dist/bundle`;
    document.head.append(h("link", { rel: "stylesheet", href: `${base}/asciinema-player.css` }));
    const script = h("script", { src: `${base}/asciinema-player.min.js` });
    script.onload = () => resolve(window.AsciinemaPlayer);
    script.onerror = reject;
    document.head.append(script);
  });
  return playerPromise;
}
