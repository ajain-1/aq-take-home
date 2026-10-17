# Changelog

## Part 1 + Part 2: Task executor on Kubernetes

#### What I did
- Re-implemented the parts of `terminal_bench/` that were missing and broke `tb run` (written from scratch to match how the harness calls them): the run lock models, asciinema marker merging, Anthropic prompt caching, the asciinema timestamp script, and the `timeout.txt` / `formatted-response.txt` prompt templates, plus their imports. The S3/DB upload, registry, and livestream paths are left unimplemented because the executor never uses them.
- Built the executor as a pipeline in `runner/`, with a thin FastAPI layer in `api/`:
  - `bundle.py`: safe ZIP extraction (no path traversal or symlinks, size and entry caps), `task.yaml` validation, and generation of the `docker-compose.yaml` that terminal-bench expects.
  - `docker_ops.py`: builds the task image once per submission, layers `tmux`/`asciinema` on top (task images don't include them), builds the content-addressed Job pod image, and cleans up containers, networks, and images by label.
  - `k8s.py`: one Indexed Job per submission, one index per attempt. The manifest is derived from `task.yaml`; the module also reads per-attempt state from pods and syncs the LLM Secret.
  - `results.py`: turns terminal-bench trial output into per-attempt and aggregate results.
  - `run_task.py`: the orchestrator (prepare → build → launch → wait → collect → cleanup).
  - `store.py`: SQLite-backed submission state.
  - `trial_entrypoint.py`: what each Job pod runs (`tb run` for a single attempt).
- `POST /submit` validates the ZIP synchronously and returns 422 for a malformed task, then queues the submission. It accepts optional `n_attempts` and `agent` (`terminus-1` by default; `oracle`/`nop` for infrastructure checks).
- `GET /status/{id}` returns status (`queued|running|completed|failed`), a fine-grained phase, timestamps, and per-attempt pod state, including retries and failure reasons.
- `GET /results/{id}` returns aggregate counts, per-test pass counts across attempts, and for each attempt: per-test pass/fail, failure mode, timings, token usage, the extracted pytest output, and the artifact directory (agent episodes, asciinema recording, tmux panes, pod log).
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
- `tasks/csv-to-json-cli-fix`: Checked; no changes needed.

#### Design decisions
- **The harness runs in the pod; the task container is a sibling on the host Docker daemon.** terminal-bench drives tasks through `docker compose` and `docker exec` + tmux, so each Job pod mounts the Docker socket. The alternative, Docker-in-Docker sidecars, would mean privileged pods plus a registry or `docker load` to get the image into every pod. Locally that is slower and has more moving parts. The tradeoff is that the socket mount effectively gives root on the node. In production I'd use DinD/sysbox or a registry-backed runtime.
- **Build once, run N times.** The task image is built a single time per submission on the host daemon; the N attempt pods use it via `imagePullPolicy: Never` and the generated compose file (which has no `build:` section). `tb` runs with `--no-rebuild --no-cleanup` so one attempt can't delete the image another attempt is using; the executor removes it once, after every attempt has finished. The Job pod image is tagged by a content hash of its sources, so it is rebuilt only when `runner/` or `terminal_bench/` changes.
- **`task.yaml` drives execution.**
  - `resource_class` maps to pod resource requests, so the scheduler queues work when the node is full, and to `cpus`/`mem_limit` on the task container.
  - The agent and test timeouts are enforced by `tb`.
  - The Job's `activeDeadlineSeconds` (`(agent + test + overhead) × (1 + retries)`) is the backstop for hangs.
- **Shared storage is a hostPath at the same absolute path** in the API, the pods, and the task containers. This is the local stand-in for a bucket. Docker Desktop's daemon sees macOS paths under `/host_mnt`, so the compose bind mounts are prefixed with it (`AQ_HOST_PATH_PREFIX`).
- **Passing, across N attempts.** `passed` means every attempt resolved the task. `summary.resolved_attempts`/`pass_rate` and per-test `pass_rate` give the distribution, which is what the "learnable data point" classification needs.

#### Robustness
- **Durability and restart recovery.** Submission state lives in SQLite (WAL). On startup the API re-queues unfinished submissions. Every stage is idempotent:
  - extraction is skipped if already done;
  - an image that already exists is not rebuilt;
  - Job creation adopts an existing Job on HTTP 409;
  - waiting simply re-attaches to the running Job.

  On shutdown, in-flight submissions are left resumable rather than marked failed.
- **Failure isolation.**
  - A failing test is a normal result, not an infrastructure failure.
  - Infrastructure failures of a single attempt (e.g. an OOM-killed or evicted pod) are retried once via `backoffLimitPerIndex` without touching the other attempts.
  - A retried pod first removes leftover task containers and partial output from the previous try.
  - Pods that can never start fail the submission immediately instead of waiting out the deadline: container-level errors (`ErrImageNeverPull`, `CreateContainerConfigError`, …) and volume failures (`FailedMount`, read from pod events after 3 repeats so a transient hiccup doesn't count).
- **Task container memory.** `resource_class` caps the task container through compose `mem_limit`, with `memswap_limit` set to the same value (otherwise Docker silently adds an equal amount of swap and the limit doubles). If a task exceeds it, Docker kills the task container rather than the pod. terminal-bench would report that as a plain agent or test failure, so the pod watches Docker's `oom` events for its task container, and the attempt's `infrastructure_issues` says it was OOM-killed.
- **Partial results.** Each attempt has one of three statuses: `completed` (tests ran), `tests_not_run` (the trial finished but produced no parseable test results, e.g. a test timeout), or `error` (no results at all, reported with the pod's reason, e.g. `OOMKilled (exit code 137)`). The other attempts still report either way. The submission is `failed` only if every attempt errored.
- **Timeouts everywhere.** Docker builds (`AQ_BUILD_TIMEOUT_SEC`), the Job deadline, and an executor-side wait deadline (Job deadline plus a grace period) after which the Job is deleted.
- **Cleanup always runs** after a terminal outcome: the Job is deleted, then labelled task containers and networks (which can be orphaned when a pod is killed before compose teardown), then the task images. `ttlSecondsAfterFinished` is a fallback. Each pod log is saved next to its attempt before the Job is deleted.
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
- The Job's `activeDeadlineSeconds` starts when the Job is created, so time spent `Pending` on a saturated node counts against it.
- Docker builds are not interruptible, so a clean API shutdown waits for in-flight builds to finish.

#### Fixes from code review
- **Resume:** never re-creates a Job once launched. The persisted `launched_at` makes a resumed run re-attach and collect instead of re-running paid attempts, even if the Job was garbage-collected.
- **API startup:** the API is wired in the FastAPI lifespan (`api/context.py`), and the cluster client connects lazily, so a missing kubeconfig shows up as `k8s_available: false` on `/health` instead of a crash at startup. The `runner`/`api` loggers get their own handler, because uvicorn owns the root logger.
- **Settings and agents:** settings are read from the environment when the API starts (`Settings.from_env()`), not at import, and the agent catalog lives in one place (`runner/config.py`).
- **Pod mounts:** pods mount only their own submission directory, not the whole data directory (which holds the state database and other submissions).
- **Store and uploads:** `store.update` holds its lock across the read and the write, and uploads are read only up to the size limit.
- **Retried pods:** logs from every try of an attempt are kept (`pod-try-N.log`). The pod entrypoint forwards SIGTERM to `tb`.
- **Linting:** `ruff.toml` added, and the code is clean under it.

#### End-to-end verification
- All 6 tasks ran concurrently via `scripts/run_all.sh` with `terminus-1`: csv-to-json 5/5, broken-coordinate-transform 8/8, config-manifest-validator 7/7, broken-flask-api 9/9, fix-maven-artifact-dependencies 10/10, log-rotation-analyzer 3/7 (an agent failure, not an infrastructure one). No Jobs or task containers were left afterwards.
- The committed real run is in `results/sample-run/` (csv-to-json-cli-fix: results, agent episodes, asciinema recording, tmux panes).
- Restart recovery: an oracle submission with 2 attempts was interrupted by an API restart, resumed, and passed 5/5 on both attempts.

#### What I'd do next
- Replace the Docker socket with per-pod DinD/sysbox (or a remote BuildKit plus a registry) for real isolation, and use object storage instead of hostPath.
- Move the worker pool out of the API process into a queue-driven controller, so API restarts and deploys don't pause monitoring.
- Add per-submission cancellation (`DELETE /submissions/{id}`) and a cluster-wide attempt budget.

## Stretch goal A: UI

#### What I did
- Added a web UI at `GET /ui`. It is plain HTML/CSS/JS in `api/static/` with no build step, served by the same FastAPI app.
  - **Submit:** drag and drop (or choose) a task ZIP, pick the number of attempts and the agent, and submit. Validation errors from `/submit` (e.g. a malformed ZIP) are shown inline.
  - **Watch it run:** the page polls `/status` every 2.5s and shows the status, phase, timestamps, and a chip per attempt with its pod state, retry count and failure reason. The submission list refreshes every 5s, and the URL hash makes a submission linkable.
  - **Agent trajectory:** each LLM turn is shown with the agent's state analysis, plan, the exact keystrokes it sent (blocking/timeout), whether it marked the task complete, and the terminal output it saw afterwards. The initial prompt and the terminal after the agent and after the tests are collapsible. The trajectory works during a run, since agent logs are written as the agent goes.
  - **Results:** resolved attempts, pass rate, and per-test pass counts across attempts, plus a tab per attempt with per-test pass/fail, timings, token usage and the pytest output.
- Added read-only endpoints in `api/ui_routes.py`, kept out of `main.py`:
  - `GET /submissions` lists the most recent submissions.
  - `GET /submissions/{id}/attempts/{n}/episodes` returns the turn-by-turn trajectory (`agent-logs/episode-N/{prompt.txt,response.json}`) plus the tmux pane snapshots.

#### Design decisions
- **No frontend toolchain.** A single static page keeps the UI deployable with the API and reviewable in one sitting. All content goes through `textContent` (a tiny `h()` DOM helper), never `innerHTML`, so agent output and terminal text can't inject markup.
- **Turns are paired with what the agent saw next.** terminus-1 feeds the terminal output after a turn's commands back as the next prompt, so the API attaches episode N+1's prompt to episode N as its "observation". That puts each action next to its effect.
- **Safe paths.** Artifact paths are never taken from the request. The submission ID must exist in the store, the attempt index is an int bounded by `n_attempts`, and the trial directory is found by globbing inside that attempt's own directory.

#### How I verified it
- Developed the trajectory viewer against the committed real run (`results/sample-run`). Then did one real `terminus-1` run end to end through the UI in Chrome: uploaded `config-manifest-validator.zip` through the file input, submitted, watched the live status and live trajectory, and saw the final results (7/7 passed). I restarted the API mid-run; the submission resumed and finished.
- Screenshots are in `docs/ui/`: `submitted-running.jpg`, `live-trajectory.jpg`, `completed-results.jpg`, `pytest-output.jpg`, `trajectory.jpg`.
- Checked with curl that path-traversal attempts and an out-of-range attempt index return 404, and that a non-ZIP upload returns 422.

#### Tradeoffs / what I'd do next
- Polling rather than server-sent events or WebSockets: simpler and good enough at a 2.5s interval. SSE would cut latency and load.
- No asciinema playback yet. The `.cast` recordings are already saved per trial, and embedding asciinema-player would let you replay the terminal.
- No auth. The UI exposes everything the API does, which is fine for a local tool but not for a shared deployment.

## Stretch goal B: Inference cost optimization

#### What I did
- `strategy=adaptive` on `POST /submit` runs attempts in waves (one Indexed Job per wave, with a global attempt offset) and stops as soon as the 10-run learnability class is decided. `/results` gains a `learnability` block: `classification` (`learnable | too_easy | too_hard | undetermined`), passing/failing runs, `attempts_used` vs. `target_runs`, measured tokens, estimated cost, and estimated tokens/cost saved versus running all 10. `/status` shows the waves.
- `runner/learnability.py` holds the decision rules. Out of 10 runs the class is already fixed once passes ≥ 8 (too easy), failures ≥ 9 (too hard), or passes ≥ 2 and failures ≥ 3 (learnable), because no outcome of the remaining runs can change it. Stopping exactly then (`confidence=1.0`, the default) always returns the same answer as running all 10.
- Optional `confidence < 1.0` also stops once the posterior predictive probability of one class (uniform Beta prior on the per-run pass rate, Beta-Binomial over the remaining runs) reaches the threshold. This trades a bounded misclassification rate for fewer runs.
- `scripts/simulate_cost.py` produces `results/cost-optimization/simulation.md`. It replays all 1024 outcome sequences of 10 runs, so the expectations are exact rather than sampled, and checks every classification against the 10-run rule.

#### Results
- **Exact policy:** 0 misclassifications across all 1024 sequences × wave caps {1, 3, 5, 10}. It uses 7.85 attempts on average instead of 10 (22% fewer, p uniform). That is 8 for a task every run solves, 9 for one every run fails, and about 6.6 near p = 0.4. At the measured $0.61 per terminus-1 attempt, that is $4.75 instead of $6.05 per task.
- **Confidence stopping:** 0.95 → 7.34 attempts (27% fewer) with a 0.5% misclassification rate; 0.9 → 6.43 attempts (36% fewer) with a 3.1% rate.
- **Waves cost nothing extra.** Each wave launches `runs_until_decidable` attempts: the fewest more runs after which a decision is even possible. A one-at-a-time policy would run every one of those, so parallel waves have exactly the sequential policy's cost (checked for every sequence in the tests), and latency drops from about 7.9 waves to about 2.9 (averaged over p). The first wave is always 5. A naive "batches of 5" alternative costs 9.21 attempts.
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
