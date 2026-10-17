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

## Stretch goal D: Beyond pass/fail

#### What I did
- Added `runner/insights/`, which turns the N attempts of a submission into findings a customer can act on. It is served by `GET /insights/{id}` (`?format=markdown`, `?refresh=true`, `?narrative=false`) and written to `insights.json` / `insights.md` in the submission directory. `python -m runner.insights <dir>` regenerates and re-verifies a report offline.
- What it reports:
  - **Outcome with honest uncertainty.** Resolved k/N with a 95% Wilson interval, and a learnability verdict. At N=10 it applies the exact 2–7-of-10 rule; below that it commits to "likely learnable / too easy / too hard" only when the whole interval supports it, and otherwise says `insufficient_evidence`.
  - **Per-test pass rates**, each with its own interval.
  - **Per-attempt failure taxonomy**: `infrastructure_issue` (e.g. task-container OOM, cited from the pod's `task-container-events.jsonl`), `infrastructure_error`, `tests_not_run`, `agent_timeout`, `test_timeout`, `llm_error`, `tests_unparseable`, `stopped_without_completing`, `declared_done_with_failing_tests`, and `declared_done_despite_failure_warning` (terminus showed the agent its "TESTS FAILED! Are you sure" prompt and it declared done anyway).
  - **Consistent failures**: a test that fails in every completed attempt, flagged as systematic when the assertion message is identical each time.
  - **Hidden requirements (task-quality signal).** The test file is parsed with `ast` to find the literal strings each failing test checks for, skipping assertion messages, docstrings, f-strings, dict keys and call arguments, and taking the literal prefix of regexes. A literal counts as hidden if it is absent from the instruction and was never shown to an agent by the environment before that agent typed it. The agent's own echoed output doesn't count as discovery.
  - **Divergence**: for tests that pass in some attempts and fail in others, a literal that every passing attempt typed and no failing attempt did.
- Evidence committed in `results/insights/`:
  - **`log-rotation-analyzer`, 5 attempts: 0/5 resolved.** Four tests fail in all 5 attempts, three of them with an identical assertion each time. Every attempt declared success with failing tests. The tests require strings the instruction never states (`SYSTEM OVERVIEW`, `LOG FILE ANALYSIS`, `Total log size:`, `Potential space reduction:`, `Large file`, …). Concretely: the task under-specifies its report format, so the 0% pass rate measures the spec, not the agent. 67/67 evidence items verify from the committed files.
  - **`broken-flask-api`, 5 attempts: 5/5 resolved.** The report says so, and still gives `insufficient_evidence` for learnability (interval 57–100%) rather than declaring it too easy.
  - **`broken-coordinate-transform`, 5 attempts: 5/5 resolved**, with the same honest `insufficient_evidence` verdict. None of the live runs produced mixed results, so pass-versus-fail divergence detection is exercised only by the synthetic unit test (`tests/test_insights.py`), not by committed run evidence.

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
     - `test_timeout_budget`: `run-tests.sh` installs packages over the network but the test timeout is under 90s.
     - `solution_present`: the task has a `solution.sh`.
  2. **Image probe** (`image_probe.py`): builds the image exactly as the executor does and runs a shell probe in it with networking off. It flags directories the instruction points the agent at that are missing or empty, and tools the tests call that the image lacks and `run-tests.sh` doesn't install.
  3. **Reference runs** (`reference_runs.py`): the oracle (2 attempts) and nop (1 attempt) agents run as ordinary submissions through the existing pipeline: Jobs, retries, cleanup, restart recovery.
     - **Oracle:** must resolve every attempt, with identical per-test results (determinism), and with tests not taking over half of `max_test_timeout_sec`. A task-container OOM is reported as `resource_class_fits`.
     - **Nop:** must not resolve the task. Tests that pass on the untouched environment are listed as `info`, since they don't measure the agent's work.
- **API endpoints** (`api/validation.py`, `api/validation_routes.py`):
  - `POST /validate` (`mode=static|full`, `force`) returns a report of findings, each with a stage, severity, check and message.
  - `GET /validations/{id}` returns a report.
  - `POST /submit` gains `validation=none|static|full`.
    - `static` rejects with a 422 that carries the report.
    - `full` puts the submission in a `validating` phase. `GatedTaskRunner` runs the validation before the agents and fails the submission (pointing at the report) if it finds errors, so no agent compute is spent on a broken task.
- `scripts/validation_report.py` validates every task in a directory and writes per-task JSON reports and a `SUMMARY.md`.
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
  - **log-rotation-analyzer:** `instruction_path_empty` for both `/var/log/samples/` and `/etc/logrotate.d/samples/`.
  - **Duplicated instructions:** `duplicated_instruction` on all three affected tasks.
- `docs/validation/fixed-tasks/`: the current tasks. All six pass every stage with no errors or warnings. The only findings are `info` notes on two tests that pass without any work (Flask's `test_requirements_file_exists`, csv's `test_utf8_stdout_encoding`).

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
- An optional LLM reviewer that compares the instruction, tests and solution for unstated requirements, kept advisory and separate from these deterministic checks.
