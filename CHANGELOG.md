# Changelog

## Part 1 + Part 2: Task executor on Kubernetes

#### What I did
- Re-implemented the parts of `terminal_bench/` that were missing and broke `tb run` (written from scratch to match how the harness calls them): the run lock models, asciinema marker merging, Anthropic prompt caching, the asciinema timestamp script, and the `timeout.txt` / `formatted-response.txt` prompt templates, plus their imports. The S3/DB upload, registry, and livestream paths are left unimplemented because the executor never uses them.
- Built the executor as a pipeline in `runner/`, with a thin FastAPI layer in `api/`:
  - `bundle.py`: safe ZIP extraction (no path traversal or symlinks, size and entry caps), `task.yaml` validation, and generation of the `docker-compose.yaml` that terminal-bench expects.
  - `docker_ops.py`: builds the task image once per submission, layers `tmux`/`asciinema` on top (task images don't include them), builds the content-addressed Job pod image, and cleans up containers, networks, and images by label.
  - `k8s.py`: one Indexed Job per wave of attempts (a fixed-strategy submission is a single wave), one index per attempt. The manifest is derived from `task.yaml`; the module also reads per-attempt state from pods and syncs the LLM Secret.
  - `results.py`: turns terminal-bench trial output into per-attempt and aggregate results.
  - `run_task.py`: the orchestrator (prepare → build → launch and wait for each wave → collect → cleanup).
  - `store.py`: SQLite-backed state (a shared document store for submissions and validations).
  - `trial_entrypoint.py`: what each Job pod runs (`tb run` for a single attempt).
  - `paths.py` / `trajectory.py`: the one on-disk submission layout and the one agent-trajectory loader, shared by the runner, results, UI, insights and validation.
- `POST /submit` validates the ZIP synchronously and returns 422 for a malformed task, then queues the submission. It accepts optional `n_attempts` and `agent` (`terminus-1` by default; `oracle`/`nop` for infrastructure checks), plus `strategy`/`confidence` (stretch goal B) and `validation` (stretch goal C).
- `GET /status/{id}` returns status (`queued|running|completed|failed`), a fine-grained phase, timestamps, and per-attempt pod state, including retries and failure reasons.
- `GET /results/{id}` returns aggregate counts, per-test pass counts across attempts, and for each attempt: per-test pass/fail, failure mode, infrastructure issues (e.g. task-container OOM), timings, token usage, the extracted pytest output, and the artifact directory (agent episodes, asciinema recording, tmux panes, pod logs).
- Made the helper scripts run on macOS's bash 3.2 and BSD tools: replaced `head -n -1` and `declare -A`, and fixed `mktemp /tmp/task-XXXXXX.zip`, which BSD `mktemp` does not randomize (every run reused one literal file). `run_all.sh` no longer exits silently under `set -e` when a submit fails, and polling stops on 404.
- Model routing: the README's `anthropic/claude-opus-4-5-20250514` is not an OpenRouter model ID. The executor uses `openrouter/anthropic/claude-opus-4.5` through LiteLLM (configurable with `AQ_MODEL`).

#### What I changed in tasks/
Every task was checked with plain Docker (`scripts/verify_task.sh`; logs in `results/task-verification/`). Each one builds, its `solution.sh` passes every test, and with the task left unsolved every test fails except one file-existence check each in `broken-flask-api` and `csv-to-json-cli-fix`, which check files the task already provides.

- `tasks/broken-coordinate-transform/task.yaml`: Removed the duplicated copy of the instruction. The instruction also said to keep "the same format already in buggy.cpp", but that format prints prompts, a "Result matrix C:" header and trailing spaces, and the tests reject all of those. It now says to print only the result rows, with values separated by single spaces.
- `tasks/config-manifest-validator/task.yaml`: Removed the duplicated copy of the instruction.
- `tasks/config-manifest-validator/tests/test_outputs.py`, `solution.sh`: The instruction asks for `manifest.txt`, but the tests and the solution used `hello.txt`, so an agent that followed the instruction could never pass. I kept the instruction as the spec and changed both files to `/app/manifest.txt`. The content test also required the file to contain *only* "Hello, world!", while the instruction only requires it as the first line, so the test now checks the first line.
- `tasks/broken-flask-api/Dockerfile`: `WORKDIR /workspace` → `/app`. Every test reads `/app/app.py`, `/app/requirements.txt` and `/app/data/users.json`, so the oracle failed too.
- `tasks/fix-maven-artifact-dependencies/Dockerfile`: `COPY libs /app/lib` → `/app/libs`. The top-level `CMakeLists.txt` uses `add_subdirectory(libs/...)` and the stray-artifact test allows `libs`, so the project could not configure at all.
- `tasks/fix-maven-artifact-dependencies/task.yaml`: The instruction (pasted twice) described a Maven/Java project (pom.xml, JARs, `java -jar`), but the environment and tests are a CMake/C++ shared-library project. I rewrote it to describe the real project and what the tests check: compile_commands.json, SONAME/versioning, RPATH, link order, PUBLIC includes, `add_dependencies`, and no stray files. I also raised `max_test_timeout_sec` from 60 to 180, because `run-tests.sh` runs `apt-get`, installs uv and does about ten clean CMake builds, which already took about 31s on an idle machine.
- `tasks/fix-maven-artifact-dependencies/tests/test_outputs.py`: Two tests passed for the wrong reason.
  - **Link order:** `test_shared_lib_link_order_math_before_calc` scanned every file under `build/` and stopped at the first one that mentioned both libraries. That was the `libcalc.so` binary, whose NEEDED entry happens to put `libmath` first. The calculator's real `link.txt` always lists calc before math, because CMake sorts dependents before their dependencies. The test now checks the declared order in calculator's `target_link_libraries`.
  - **Comment matches:** `test_explicit_dependencies_present_to_avoid_races` and the manual-include check matched text inside comments; the original `app/CMakeLists.txt` comment literally contains `add_dependencies(calculator math calc)`. Both now strip comments first.
- `tasks/fix-maven-artifact-dependencies/solution.sh`: The guard that skips adding `add_dependencies` if it is already present also matched that comment, so the oracle never added the line. The guard now only matches an uncommented line.
- `tasks/log-rotation-analyzer/generate-samples.sh`: The sample logs and logrotate configs were written to `/app/sample_logs` and `/app/sample_configs`, while the instruction points the agent at `/var/log/samples/` and `/etc/logrotate.d/samples/`, which were left empty. The script now writes there; `log_metadata.json` stays in `/app`.
- `tasks/log-rotation-analyzer/task.yaml`: The tests read `analysis_report.txt`, `optimized_logrotate.conf` and `rotation_summary.csv` from the working directory, but the instruction never said where to write them. It now says `/app`.
  - **Report format.** The tests also require exact text the instruction never stated: the title `LOG ROTATION ANALYSIS REPORT`, the section headings `SYSTEM OVERVIEW`, `LOG FILE ANALYSIS`, `SUMMARY` and `RECOMMENDATIONS:`, `ISSUE (HIGH|MEDIUM|LOW)` markers, and the `Total log size:`, `Estimated total savings:` and `Potential space reduction: N%` lines. Stretch goal D's insight report found this (`results/insights/log-rotation-analyzer/insights.md`): 0/5 terminus-1 attempts resolved, with four tests failing in every attempt on exactly these strings. The instruction now states the format, the CSV header and the config expectations; the tests are unchanged. The oracle still passes 7/7 and nop fails 7/7 (`results/task-verification/log-rotation-analyzer.*.log`). The insight runs predate this fix.
  - **Result after the fix:** 10/10 terminus-1 attempts resolved, all 7/7 tests (`results/insights/log-rotation-analyzer-after-fix/`). Both B's rule and D's report now classify the task as `too_easy`. The 0/5 before the fix measured the under-specified instruction, not the agent.
- `tasks/csv-to-json-cli-fix`: Checked; no changes needed.

#### Design decisions
- **The harness runs in the pod; the task container is a sibling on the host Docker daemon.** terminal-bench drives tasks through `docker compose` and `docker exec` + tmux, so each Job pod mounts the Docker socket. The alternative, Docker-in-Docker sidecars, would mean privileged pods plus a registry or `docker load` to get the image into every pod. Locally that is slower and has more moving parts. The tradeoff is that the socket mount effectively gives root on the node. In production I'd use DinD/sysbox or a registry-backed runtime.
- **Build once, run N times.** The task image is built a single time per submission on the host daemon; the N attempt pods use it via `imagePullPolicy: Never` and the generated compose file (which has no `build:` section). `tb` runs with `--no-rebuild --no-cleanup` so one attempt can't delete the image another attempt is using; the executor removes it once, after every attempt has finished. The Job pod image is tagged by a content hash of its sources, so it is rebuilt only when `runner/` or `terminal_bench/` changes. One exception: with `validation=full`, the image probe and the oracle and nop reference runs each build the task image again before the gated run. That keeps every validation stage independent at the cost of extra builds, which Docker's layer cache keeps cheap.
- **`task.yaml` drives execution.**
  - `resource_class` maps to pod resource requests, so the scheduler queues work when the node is full, and to `cpus`/`mem_limit` on the task container.
  - The agent and test timeouts are enforced by `tb`.
  - Each attempt pod has `activeDeadlineSeconds` = `agent + test + overhead` as the backstop for hangs. A pod's deadline counts from when it starts, so time spent queued for cluster capacity never counts against it.
- **Shared storage is a hostPath at the same absolute path** in the API, the pods, and the task containers. This is the local stand-in for a bucket. Docker Desktop's daemon sees macOS paths under `/host_mnt`, so the compose bind mounts are prefixed with it (`AQ_HOST_PATH_PREFIX`).
- **Passing, across N attempts.** `passed` means every attempt resolved the task. `summary.resolved_attempts`/`pass_rate` and per-test `pass_rate` give the distribution, which is what the "learnable data point" classification needs.

#### Robustness
- **Durability and restart recovery.** Submission state lives in SQLite (WAL). On startup the API re-queues unfinished submissions. Every stage is idempotent:
  - extraction is skipped if already done;
  - an image that already exists is not rebuilt;
  - Job creation adopts an existing Job on HTTP 409;
  - waiting simply re-attaches to the unfinished wave's Job.

  On shutdown, in-flight submissions are left resumable rather than marked failed. A submission never runs in two threads at once (`TaskRunner.run` refuses a submission that is already running), and waves are planned inside one store update, so a wave is never added twice.
- **Failure isolation.**
  - A failing test is a normal result, not an infrastructure failure.
  - Infrastructure failures of a single attempt (e.g. an OOM-killed or evicted pod) are retried once via `backoffLimitPerIndex` without touching the other attempts.
  - A retried pod first removes leftover task containers and partial output from the previous try.
  - Pods that can never start fail the submission immediately instead of waiting out the deadline: container-level errors (`ErrImageNeverPull`, `CreateContainerConfigError`, …) and volume failures (`FailedMount`, read from pod events after 3 repeats so a transient hiccup doesn't count).
- **Task container memory.** `resource_class` caps the task container through compose `mem_limit`, with `memswap_limit` set to the same value (otherwise Docker silently adds an equal amount of swap and the limit doubles). If a task exceeds it, Docker kills the task container rather than the pod. terminal-bench would report that as a plain agent or test failure, so the pod watches Docker's `oom` events for its task container, and the attempt's `infrastructure_issues` says it was OOM-killed.
- **Partial results.** Each attempt has one of three statuses: `completed` (tests ran), `tests_not_run` (the trial finished but produced no parseable test results, e.g. a test timeout), or `error` (no results at all, reported with the pod's reason, e.g. `OOMKilled (exit code 137)`). The other attempts still report either way. The submission is `failed` only if every attempt errored.
- **Timeouts everywhere.**
  - **Docker builds:** limited by `AQ_BUILD_TIMEOUT_SEC`.
  - **Per-pod deadline:** each try of an attempt has its own deadline.
  - **Executor backstop:** it charges only time while attempts are actually running, persisted per wave so it survives restarts. Past every try's budget plus a grace period, it deletes the Job.
  - **Queue cap:** a wave whose attempts only wait for capacity fails after `AQ_MAX_QUEUE_SEC` (default 1 hour) with a clear "waited for cluster capacity" error, and `/status` shows queued attempts as `Unschedulable` with the scheduler's message.
  - **Verified live:** on an N=10 run, 7 attempts queued as `Unschedulable: Insufficient memory` while the wave clock charged only running time.
- **Cleanup always runs.** Each wave's Job is deleted once its attempts finish, after every try's pod log is saved next to its attempt. After a terminal outcome, the executor removes any remaining Jobs of the submission, then labelled task containers and networks (which can be orphaned when a pod is killed before compose teardown), then the task images. `ttlSecondsAfterFinished` (24h) is a fallback.
- **Bounded concurrency.** A worker pool caps active submissions and a semaphore caps concurrent Docker builds. Pod resource requests let Kubernetes queue attempts rather than overcommit the node.
- **Secrets.** The OpenRouter key is read from `.env` (gitignored) and reaches pods only through a Kubernetes Secret; it is never written to disk by the executor or logged.

#### Running it
```bash
echo 'OPENROUTER_API_KEY=sk-or-...' > .env        # gitignored; synced to a K8s Secret
python3.12 -m venv .venv && .venv/bin/pip install -r api/requirements.txt
cd api && ../.venv/bin/uvicorn main:app --port 8000
bash scripts/run_all.sh                           # API_URL=... to use another port
```
The first submission builds the Job pod image (a few minutes); later submissions reuse it. Per-submission artifacts live under `data/submissions/<id>/`.

#### Known limitations
- Docker builds are not interruptible, so a clean API shutdown waits for in-flight builds to finish.

#### Fixes from code reviews
- **Resume:** never re-creates a Job once launched. The persisted `launched_at` makes a resumed run re-attach and collect instead of re-running paid attempts, even if the Job was garbage-collected.
- **API startup:** the API is wired in the FastAPI lifespan (`api/context.py`), and the cluster client connects lazily, so a missing kubeconfig shows up as `k8s_available: false` on `/health` instead of a crash at startup. The `runner`/`api` loggers get their own handler, because uvicorn owns the root logger.
- **Settings and agents:** settings are read from the environment when the API starts (`Settings.from_env()`), not at import, and the agent catalog lives in one place (`runner/config.py`).
- **Pod mounts:** pods mount only their own submission directory, not the whole data directory (which holds the state database and other submissions).
- **Store and uploads:** `store.update` holds its lock across the read and the write, and uploads are read only up to the size limit.
- **Retried pods:** logs from every try of an attempt are kept (`pod-try-N.log`). The pod entrypoint forwards SIGTERM to `tb`.
- **Linting:** `ruff.toml` added, and the code is clean under it.
- **Second review (after the stretch goals were merged):**
  - **Validation gate:** composed instead of inherited. `TaskRunner` no longer knows about validations. `SubmissionService` runs the gate (validate, then run or fail), and `/submit` with a gate is one call that checks every parameter before creating anything. A gating validation is linked to its submission from the moment it is created, and one whose static checks fail finishes immediately, so neither can be orphaned. Oracle/nop runs of an unfinished validation are resumed only by that validation, never twice.
  - **Shared code:** one `DocumentStore` base for submissions and validations (atomic updates in both), one submission layout (`runner/paths.py`) and one trajectory loader (`runner/trajectory.py`) shared by the runner, results, UI, insights and validation.
  - **One learnability rule:** insights (D) use the same exact 10-run rule as the adaptive strategy (B), so the two can't disagree. Savings are reported only for adaptive runs.
  - **Robustness:** a truncated `results.json` or events line now fails only its own attempt, not the whole submission.
  - **Insights endpoint:** read-only; the LLM summary is opt-in, its model is a setting (`AQ_INSIGHTS_MODEL`), and failures are logged.
  - **Consistency:** every 422 has a string `detail` (plus `report` when there is one), insight categories are renamed to `no_results` / `task_container_oom`, and the remaining limits (`AQ_MAX_CONCURRENT_VALIDATIONS`) are settings.

#### Robustness verification
- **Unit tests:** 142 under `tests/`. They drive `TaskRunner` with a fake cluster client: fixed and adaptive waves, resume with launched and unlaunched waves, shutdown leaving the submission resumable, a run refused while the same submission is already executing, waves planned once under concurrent callers, deadline and vanished-Job attribution, corrupt per-attempt results, and failure cleanup. They also cover bundle security (traversal, symlinks, size and entry caps), store atomicity, Kubernetes pod-state parsing, the Job manifest, the validation gate paths (static reject, linked at creation, failed gate, reference runs not resumed twice) and the API routes.
- **Live scenarios:** `tests/robustness/live_scenarios.py` runs against the real cluster with fixture tasks and the oracle/nop agents. The evidence is in `tests/robustness/live_results.json`.
  - **Passed:** upload validation (11 malformed cases, all 422); the static and full validation gates, including an API SIGKILL mid-validation (reference runs re-attached and never run twice); parallel attempts with pod logs and full cleanup; agent timeout; task-container OOM, capped at 1 GB with no swap and flagged; build failure; killed pods retried with partial results and orphan removal; per-try pod deadlines; API restarts while running (SIGKILL), while building (SIGTERM) and after the Job vanished; a queued backlog surviving a restart; harness OOM retried; unstartable pods failing in seconds; build timeout; an adaptive restart mid-wave with every attempt run exactly once; and the key never written to disk.
  - **Not re-run after the deadline rework:** the adaptive wave-1 pod crash, and the new queue cap (no fixture can be made unschedulable without starving the shared cluster). Both are covered by unit tests.
- **Bugs fixed:**
  - One transient apiserver error used to fail the submission and delete its Job.
  - Attempts of a failed or vanished Job were reported as "pending". They now carry the Job's reason, scoped to their wave, while attempts that already failed keep their own pod reason.
  - Kubernetes Job rejections are reported concisely.
  - An explicit `n_attempts=0` or `agent=""` was silently replaced by the default.
  - Two concurrent callers could each append a wave.
  - The same submission could execute in two threads.

#### End-to-end verification
- All 6 tasks ran concurrently via `scripts/run_all.sh` with `terminus-1`, one attempt each. Tests passed per task: csv-to-json 5/5, broken-coordinate-transform 8/8, config-manifest-validator 7/7, broken-flask-api 9/9, fix-maven-artifact-dependencies 10/10, log-rotation-analyzer 3/7 (an agent failure, not an infrastructure one). No Jobs or task containers were left afterwards. Evidence: each submission's `/results` JSON and the script output are in `results/e2e-all-tasks/`.
- The committed real run is in `results/sample-run/` (csv-to-json-cli-fix: results, agent episodes, asciinema recording, tmux panes).
- Restart recovery: a submission was interrupted by an API restart while its attempt was running, then resumed and completed. Evidence: `results/restart-recovery/` holds the API's interrupted and resuming log lines and the final results.

#### What I'd do next
- Replace the Docker socket with per-pod DinD/sysbox (or a remote BuildKit plus a registry) for real isolation, and use object storage instead of hostPath.
- Move the worker pool out of the API process into a queue-driven controller, so API restarts and deploys don't pause monitoring.
- Add per-submission cancellation (`DELETE /submissions/{id}`) and a cluster-wide attempt budget.

## Stretch goal A: UI

#### What I did
- A web UI at `GET /ui`, organized around how you actually look at results: tasks first, then the runs of a task, then the attempts of a run. It is unbundled ES modules in `api/static/` (`app.js` entry point, `api.js`, `router.js`, `components.js`, `views/*.js`) with a hash router, so every screen has its own link.
  - **Dashboard** (`#/`): headline numbers (tasks, runs, agent attempts, overall resolve rate with a 95% interval, median attempt time, model spend and tokens), a "running now" strip with each active run's phase, a table with one row per task (resolve rate bar, learnability, runs, median attempt, last outcome), and a breakdown of why agent attempts fail.
  - **Task page** (`#/tasks/{id}`):
    - the task's spec: difficulty, category, resources, timeouts, and the instruction (collapsible);
    - aggregates across all its runs;
    - a **per-test grid** (rows are tests, columns are attempts across runs, oldest first), so a test that fails in every column stands out;
    - **Caveat:** a task's aggregates group runs by task ID, so runs of an edited task (e.g. `log-rotation-analyzer` before and after its instruction fix) are combined. Grouping by a hash of the task's contents would separate versions.
    - failure categories, the latest validation report (C), D's insight findings with their verified evidence, and the list of runs.
  - **Run page** (`#/runs/{id}`): one outcome badge (Passed, Partially passed, Failed, Running, Queued or Error).
    - **While running:** a phase stepper and one card per attempt, with the pod state as grey detail.
    - **When done:** headline numbers, attempt cards (resolved, tests x/y, duration, tokens, failure category, infrastructure issues), the per-test table across this run's attempts (shown once), the adaptive strategy's waves and decision (B), and insights.
  - **Attempt page** (`#/runs/{id}/attempts/{n}`): the trajectory view.
    - On the left, a compact timeline: the task given to the agent, then one line per turn with its plan, number of commands, and markers for "declared done", "warned: tests failing" and "command timed out"; it ends with the test verdict.
    - On the right, the selected turn: what the agent saw, what it decided, the exact commands, and the terminal output it saw next.
    - `↑`/`↓` or `j`/`k` step through turns, and a live attempt follows the newest turn (one still waiting for the model shows as "Waiting for the model…").
    - Other tabs: Tests, Pytest output, and **Terminal replay**, which plays the attempt's asciinema recording (asciinema-player 3.8.0, pinned) with the agent's turns as markers.
  - **Submit** (`#/submit`): a drop zone plus agent, strategy (fixed attempts, or adaptive with a stopping rule) and validation gate. It goes straight to the new run's page; a 422 shows its message and, for a failed static gate, the report's findings.
- **One status vocabulary:** only the outcome is coloured. Pipeline phase and pod state are neutral grey text, so "pod succeeded" can never sit next to "tests failed" again.
- **Read-only endpoints** in `api/ui_routes.py`, backed by `runner/catalog.py`, a pure, unit-tested aggregation module (`tests/test_catalog.py`):
  - `GET /dashboard` and `GET /tasks`;
  - `GET /tasks/{task_id}` (spec, aggregates, per-test grid, runs, latest validation);
  - `GET /submissions` and `GET /submissions/{id}/attempts/{n}/episodes`;
  - `GET /submissions/{id}/attempts/{n}/recording`.
- **`GET /results`** now adds a `category` to each attempt (from `catalog.attempt_category`, using the same names as D's insights), so the UI never re-derives it.

#### Design decisions
- **Aggregates count LLM-agent attempts only.** Oracle/nop runs are listed, but never pooled into a task's resolve rate. A task's learnability prefers the latest adaptive run's exact decision (B) and otherwise applies the same exact 10-run rule to the pooled attempts, so it says "Not enough runs" until it's decided.
- **Attempts are bounded by what actually ran**, not by `n_attempts`. Adaptive runs launch a variable number of attempts, so the episodes and recording endpoints return 404 for anything else, and paths are never built from the request.
- **No frontend toolchain, safe rendering.** All content goes through a small `h()` DOM helper that only creates text nodes, never `innerHTML`, so agent output and terminal text can't inject markup. Static files are served with `Cache-Control: no-cache`, so browsers revalidate the modules and never keep running a stale UI after a change.
- **Polling, not push.** The pages showing live data poll (every 2.5s for a run, 4s for an attempt, 5s on the dashboard while something is running) and stop once the run finishes.

#### Bug found while building the replay
- terminal-bench merges the agent's turn markers into `agent.cast` while asciinema is still recording; the session is only stopped afterwards. `AsciinemaHandler` rewrote the file in place, so asciinema's later writes landed in the middle of the merged content and split JSON lines, and the player refused the file.
  - **Fix:** it now writes the merged file elsewhere and atomically replaces it (late writes go to the old inode), and skips partial lines instead of raising mid-trial.
  - **Older recordings:** the recording endpoint drops corrupt lines, so they still play.
  - **Tests:** `tests/test_recordings.py` covers both.

#### How I verified it
- **Data:** a copy of the real data (the six-task `terminus-1` run and earlier oracle runs), plus one new 3-attempt `terminus-1` run of `log-rotation-analyzer` and an adaptive oracle run of `csv-to-json-cli-fix` submitted through the UI.
- **Screens in Chrome:** dashboard, task page, run page (live and finished), attempt page (live, finished, keyboard stepping, terminal replay) and the submit flow.
- **The new run doubles as evidence for the task fix:** it passed 3/3 after the instruction change. The task page's grid shows the earlier run failing the same four tests and all three new attempts passing them.
- **Screenshots** in `docs/ui/`: `dashboard.jpg`, `task.jpg`, `run-live.jpg`, `run-finished.jpg`, `attempt-trajectory.jpg`, `attempt-replay.jpg`, `submit.jpg`.

#### Tradeoffs / what I'd do next
- Polling rather than server-sent events: simpler and good enough here. SSE would cut latency and load.
- The live adaptive run page shows the current wave's attempts but not yet the plan ("wave 2 of up to 10 attempts").
- No auth. The UI exposes everything the API does, which is fine for a local tool but not for a shared deployment.

## Stretch goal B: Inference cost optimization

#### What I did
- `strategy=adaptive` on `POST /submit` runs attempts in waves (one Indexed Job per wave, with a global attempt offset) and stops as soon as the 10-run learnability class is decided. `/results` gains a `learnability` block: `classification` (`learnable | too_easy | too_hard | undetermined`), passing/failing runs, `attempts_used` vs. `target_runs`, measured tokens, estimated cost, and estimated tokens/cost saved versus running all 10. Savings are reported only for adaptive runs (`null` for fixed-strategy runs), and D's insights use the same decision rules. `/status` shows the waves.
- `runner/learnability.py` holds the decision rules. Out of 10 runs the class is already fixed once passes ≥ 8 (too easy), failures ≥ 9 (too hard), or passes ≥ 2 and failures ≥ 3 (learnable), because no outcome of the remaining runs can change it. Stopping exactly then (`confidence=1.0`, the default) always returns the same answer as running all 10.
- Optional `confidence < 1.0` also stops once the posterior predictive probability of one class (uniform Beta prior on the per-run pass rate, Beta-Binomial over the remaining runs) reaches the threshold. This trades a bounded misclassification rate for fewer runs.
- `scripts/simulate_cost.py` produces `results/cost-optimization/simulation.md`. It replays all 1024 outcome sequences of 10 runs, so the expectations are exact rather than sampled, and checks every classification against the 10-run rule.

#### Results
- **Exact policy:** 0 misclassifications across all 1024 sequences × wave caps {1, 3, 5, 10}. It uses 7.85 attempts on average instead of 10 (22% fewer, p uniform). That is 8 for a task every run solves, 9 for one every run fails, and about 6.6 near p = 0.4. At the measured $0.61 per terminus-1 attempt, that is $4.75 instead of $6.05 per task.
- **Confidence stopping:** 0.95 → 7.34 attempts (27% fewer) with a 0.5% misclassification rate; 0.9 → 6.43 attempts (36% fewer) with a 3.1% rate.
- **Waves cost nothing extra.** Each wave launches `runs_until_decidable` attempts: the fewest more runs after which a decision is even possible. A one-at-a-time policy would run every one of those, so parallel waves have exactly the sequential policy's cost (checked for every sequence in the tests), and latency drops from about 7.9 waves to about 2.9 (averaged over p). With the default cap, the first wave is 5 (the oracle run below used a cap of 4: waves of 4, 3, 1). A naive "batches of 5" alternative costs 9.21 attempts.
- **No in-flight cancellation is needed.** A wave never exceeds the minimum runs to a decision, so a decision can't arrive mid-wave.

#### Verification
- `tests/test_learnability.py` (31 tests): boundary cases; exactness against the 10-run rule for every sequence and wave cap; the stopping point is the first decidable prefix; parallel cost equals sequential cost; class probabilities sum to 1; replacement of errored attempts is bounded.
- **End-to-end oracle run** (always passes) on `config-manifest-validator` with at most 4 attempts in flight: waves of 4, 3 and 1 → `too_easy` after 8 attempts, with all Jobs, containers and images cleaned up (`results/cost-optimization/oracle-adaptive-results.json`).
- **End-to-end terminus-1 run** on `csv-to-json-cli-fix` with `confidence=0.9`: waves of 4 and 1, all 5 passed → `too_easy` after 5 attempts. It used 139,551 input / 8,777 output tokens (about $0.92) and saved an estimated 5 attempts (about $0.92) versus running all 10 (`results/cost-optimization/terminus-adaptive-results.json`).

#### Design decisions
- **Exact by default.** "Learnable" is defined on 10 actual runs, so the default never changes a label; the probabilistic mode is opt-in and its error rate is published alongside its savings.
- **Errored attempts are replaced.** Attempts with no test results (infrastructure errors) don't count as passes or failures. They are replaced, up to 3 extra launches (`AQ_ADAPTIVE_EXTRA_LAUNCHES`), after which the class can come back `undetermined`.
- **Configurable caps and prices.** `AQ_ADAPTIVE_MAX_WAVE` caps attempts in flight. Prices default to Opus 4.5 list prices (`AQ_PRICE_*_PER_MTOK`). Token counts are terminal-bench's tokenizer estimates and ignore prompt caching, so dollar figures are approximate.
- **Not done:** screening with a cheaper model first. It is not exact against a SOTA-defined label, and the measured savings above come from attempts avoided, not cheaper ones.

## Stretch goal C: Task quality checks

#### What I did
- Added a validation pipeline (`runner/validation/`) that checks a task before any agent compute is spent on it. It runs in three stages, cheapest first:
  1. **Static checks** (`static_checks.py`, milliseconds, no containers), reading `task.yaml`, the Dockerfile, `run-tests.sh`, the tests and the solution:
     - `task_schema`: `task.yaml` parses and `resource_class` is known.
     - `duplicated_instruction`: the instruction repeats a block of three or more lines.
     - `pytest_invocation`: pytest runs with `-rA`, which terminal-bench's parser needs.
     - `tests_present`: the tests contain at least one test function.
     - `workdir`: the Dockerfile sets a `WORKDIR`.
     - `test_paths_outside_image`: the tests read absolute paths under a directory the image never creates (by `WORKDIR`, `COPY` or `mkdir`).
     - `copy_renames_directory`: a `COPY` renames a directory that other task files still refer to by its old name.
     - `tested_files_not_in_instruction`: the tests open a file that the task doesn't ship and the instruction never names.
     - `instruction_describes_other_project`: the instruction names several files that nothing else in the task contains.
     - `unstated_test_literals` (warning): text a test requires that the instruction never states and no file the task ships shows, e.g. an exact report heading. It reuses the literal extraction from stretch goal D (`runner/test_literals.py`, shared by both), which skips assertion messages, f-strings, dict keys, set literals (allow-lists), call arguments and `x not in y` checks. Paths and file names are left to the file checks.
     - `test_timeout_budget`: `run-tests.sh` installs packages over the network but the test timeout is under 90s.
     - `solution_present`: the task has a `solution.sh`.
  2. **Image probe** (`image_probe.py`): builds the image exactly as the executor does and runs a shell probe in it with networking off. It flags directories the instruction points the agent at that are missing or empty, and tools the tests call that the image lacks and `run-tests.sh` doesn't install.
  3. **Reference runs** (`reference_runs.py`): the oracle (2 attempts) and nop (1 attempt) agents run as ordinary submissions through the existing pipeline: Jobs, retries, cleanup, restart recovery.
     - **Oracle:** must resolve every attempt, with identical per-test results (determinism), and with tests not taking over half of `max_test_timeout_sec`. A task-container OOM is reported as `resource_class_fits`.
     - **Nop:** must not resolve the task. Tests that pass on the untouched environment are listed as `info`, since they don't measure the agent's work.
- **API endpoints** (`api/validation.py`, `api/validation_routes.py`):
  - `POST /validate` (`mode=static|full`, `force`) returns a report of findings, each with a stage, severity, check and message.
  - `GET /validations/{id}` returns a report.
  - `POST /submit` gains an optional `validation=static|full` (omit it for no gate).
    - `static` rejects with a 422 whose body carries the report.
    - `full` puts the submission in a `validating` phase. The submission worker runs the validation before the agents and fails the submission (pointing at the report) if it finds errors, so no agent compute is spent on a broken task.
- `scripts/validation_report.py` validates every task in a directory and writes per-task JSON reports and a `SUMMARY.md`. `--refresh-static` re-runs only the static checks locally against existing reports, keeping the image-probe and oracle/nop findings, so a new static check doesn't need new Job runs.
- Unit tests for each static check and for the Dockerfile parser: `tests/test_validation_static_checks.py`.

#### Evidence
- `docs/validation/original-tasks/`: the six tasks exactly as they were in the initial commit, validated with `force=true` so every stage ran. The pipeline flags every bug that was later fixed by hand:
  - **broken-flask-api:** `test_paths_outside_image` (WORKDIR `/workspace`, tests read `/app/...`), and the oracle fails 3 tests.
  - **fix-maven-artifact-dependencies:**
    - `copy_renames_directory` (`libs/` copied to `/app/lib`);
    - `instruction_describes_other_project` (8 Maven/Java files that exist nowhere);
    - `test_timeout_budget` (60s);
    - the oracle fails all 10 tests.
  - **config-manifest-validator:** `tested_files_not_in_instruction` (`hello.txt`) and `instruction_files_unused` (`manifest.txt`).
  - **log-rotation-analyzer:** `instruction_path_empty` for both `/var/log/samples/` and `/etc/logrotate.d/samples/`, and `unstated_test_literals` for the report headings and summary lines the tests require.
  - **fix-maven-artifact-dependencies** also gets `unstated_test_literals` for `RUNPATH`, which its Maven/Java instruction never mentions.
  - **Duplicated instructions:** `duplicated_instruction` on all three affected tasks.
- `docs/validation/fixed-tasks/`: the current tasks. All six pass every stage with no errors or warnings. The only findings are `info` notes on two tests that pass without any work (Flask's `test_requirements_file_exists`, csv's `test_utf8_stdout_encoding`).
  - **Before the log-rotation instruction fix,** `unstated_test_literals` flagged the fixed log-rotation-analyzer too, matching what stretch goal D found from real runs. The git history keeps both versions of the report.

#### Design decisions
- **Cheap stages gate expensive ones.** Static errors stop the pipeline before an image is built unless `force` is set, which is the point of validating at all. The image probe only builds the image, which the reference runs then reuse from Docker's layer cache.
- **The reference runs reuse the submission pipeline instead of a parallel code path.** The oracle and nop runs are real submissions, so they exercise the exact infrastructure an agent run would. They also inherit its robustness, and a validation can resume after an API restart because it records its child submission IDs.
- **Severities reflect consequence.**
  - `error` means the task is unsolvable, unverifiable or self-contradictory.
  - `warning` means it is likely to mislead the agent or be flaky.
  - `info` means it is worth a reviewer's attention.

  A validation passes when it has no errors.
- **The static checks are heuristics tuned on these tasks.** They read text, so they can be fooled, for example by a path built from variables in the tests. The image probe and reference runs are the backstop for whatever text analysis misses.

#### What I'd do next
- Mutation checks: break the oracle's output (truncate files, flip values) and confirm the tests catch it. Some tests could only be confirmed to pass for the wrong reason, like the original link-order test, by reading the code.
- Run the oracle under the task's own resource limits with N>2 attempts on a loaded node, to surface timing flakiness before customers see it.

## Stretch goal D: Beyond pass/fail

#### What I did
- Added `runner/insights/`, which turns the N attempts of a submission into findings a customer can act on. It is served read-only by `GET /insights/{id}` (`?format=markdown`, `?narrative=true` for the LLM summary), computed from the stored artifacts on each request. `python -m runner.insights <dir>` regenerates and re-verifies a report offline and writes `insights.json` / `insights.md` beside it.
- What it reports:
  - **Outcome with honest uncertainty.** Resolved k/N with a 95% Wilson interval for context, and the learnability class from `runner.learnability`, the same exact 10-run rule the adaptive strategy (B) stops on. Errored attempts are excluded, as in B. If the runs so far don't decide the class, the verdict is `undetermined` rather than a guess, so B and D can never disagree about the same run.
  - **Per-test pass rates**, each with its own interval.
  - **Per-attempt failure taxonomy**: `task_container_oom` (cited from the pod's `task-container-events.jsonl`), `no_results` (the pod produced no trial results), `tests_not_run`, `agent_timeout`, `test_timeout`, `llm_error`, `tests_unparseable`, `stopped_without_completing`, `declared_done_with_failing_tests`, and `declared_done_despite_failure_warning` (terminus showed the agent its "TESTS FAILED! Are you sure" prompt and it declared done anyway).
  - **Consistent failures**: a test that fails in every completed attempt, flagged as systematic when the assertion message is identical each time.
  - **Hidden requirements (task-quality signal).** The test file is parsed with `ast` (`runner/test_literals.py`, shared with stretch goal C's `unstated_test_literals` static check) to find the literal strings each failing test checks for. It skips assertion messages, docstrings, f-strings, dict keys, set literals, call arguments and `x not in y` checks, and takes the literal prefix of regexes. A literal counts as hidden if it is absent from the instruction and was never shown to an agent by the environment before that agent typed it. The agent's own echoed output doesn't count as discovery.
  - **Divergence**: for tests that pass in some attempts and fail in others, a literal that every passing attempt typed and no failing attempt did.
- Evidence committed in `results/insights/`:
  - **`log-rotation-analyzer`, 5 attempts: 0/5 resolved.** Four tests fail in all 5 attempts, three of them with an identical assertion each time. Every attempt declared success with failing tests. The tests require strings the instruction never states (`SYSTEM OVERVIEW`, `LOG FILE ANALYSIS`, `Total log size:`, `Potential space reduction:`, `Large file`, …). Concretely: the task under-specifies its report format, so the 0% pass rate measures the spec, not the agent. 67/67 evidence items verify from the committed files. This finding led to fixing the task's instruction (see the tasks section); the committed runs predate that fix.
  - **`broken-flask-api`, 5 attempts: 5/5 resolved.** The report says so, and gives `undetermined` for learnability (8 passes are needed to call it too easy) rather than declaring it too easy.
  - **`broken-coordinate-transform`, 5 attempts: 5/5 resolved**, with the same honest `undetermined` verdict. None of the live runs produced mixed results, so pass-versus-fail divergence detection is exercised only by the synthetic unit test (`tests/test_insights.py`), not by committed run evidence.
  - **`log-rotation-analyzer` after its instruction fix, 10 attempts: 10/10 resolved** (`results/insights/log-rotation-analyzer-after-fix/`), verdict `too_easy`. This was run specifically to get mixed results for divergence detection, but the fixed task turned out too easy for Opus 4.5. Divergence detection therefore still has no real-run evidence; a weaker model would be the cheap way to get a mixed sample.

#### How trust is enforced
- Every finding carries evidence IDs. Each item is either a verbatim quote, with its source path relative to the submission and, where relevant, line, attempt and episode, or an absence claim scoped to exactly what it is about (`task.yaml#instruction`).
- `evidence.verify` re-reads the artifacts independently of the parsers that produced the claim. JSON is compared by its decoded string values, so keystrokes are matched without escaping artefacts.
- A finding is published only if all its evidence verifies; otherwise it is moved to `rejected_insights` and listed as withheld. During development this caught a real false positive: an absence check against all of `task.yaml` matched `difficulty: medium`, which led to scoping absence checks to the instruction field.
- The optional LLM narrative (`openai/gpt-4.1-mini` via OpenRouter) only sees verified findings. Each sentence must cite IDs from them, and every number in a sentence must appear in the cited material; failing sentences are dropped and counted. The report says that the findings, not the narrative, are the source of truth.
- Limitations are stated in every report: rule-based classification, lexical matching, and wide intervals at small N.

#### Design decisions
- **Deterministic first.** Every finding comes from rules over recorded artifacts; the LLM is used only for an optional, citation-checked summary.
- **Self-contained and portable.** The analysis lives in its own package, the endpoint in its own router (`api/insights_routes.py`), and the only executor change is wiring. Paths are relative to the submission directory, so a copied evidence directory re-verifies anywhere.

#### What I'd do next
- Cluster failing trajectories by their first divergent command, and diff the files each attempt finally produced against what the tests read.
- Use the pytest assertion introspection (the `E` lines) to explain *how* an output missed (e.g. which section header was absent), not just that it did.
