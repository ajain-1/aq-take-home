# Changelog

## Part 1 + Part 2: Task executor on Kubernetes

#### What I did
- Restored the parts of `terminal_bench/` that were missing and broke `tb run`: the run lock models, asciinema marker merging, Anthropic prompt caching, the asciinema timestamp script, and the `timeout.txt` / `formatted-response.txt` prompt templates, plus their imports. The S3/DB upload, registry, and livestream paths are left unimplemented because the executor never uses them.
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
- Made the helper scripts run on macOS's bash 3.2 (`head -n -1` and `declare -A` are not available there), and made polling stop on 404.

#### What I changed in tasks/
Every task was checked with plain Docker. Each one builds, its `solution.sh` passes every test, and every test fails when the task is left unsolved.

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
  - Pods that can never start (`ErrImageNeverPull`, `CreateContainerConfigError`, …) fail the submission immediately instead of waiting out the deadline.
- **Partial results.** An attempt that produced no results is reported as `status: error` with the pod's reason (e.g. `OOMKilled (exit code 137)`, `DeadlineExceeded`) while the other attempts still report. The submission is `failed` only if no attempt produced test results.
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

#### What I'd do next
- Replace the Docker socket with per-pod DinD/sysbox (or a remote BuildKit plus a registry) for real isolation, and use object storage instead of hostPath.
- Move the worker pool out of the API process into a queue-driven controller, so API restarts and deploys don't pause monitoring.
- Add per-submission cancellation (`DELETE /submissions/{id}`) and a cluster-wide attempt budget.

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
- **End-to-end oracle run** (always passes) on `config-manifest-validator` with at most 4 attempts in flight: waves of 4, 3 and 1 → `too_easy` after 8 attempts, with all Jobs, containers and images cleaned up.
- **End-to-end terminus-1 run** on `csv-to-json-cli-fix` with `confidence=0.9`: see `results/cost-optimization/terminus-adaptive-results.json`.

#### Design decisions
- **Exact by default.** "Learnable" is defined on 10 actual runs, so the default never changes a label; the probabilistic mode is opt-in and its error rate is published alongside its savings.
- **Errored attempts are replaced.** Attempts with no test results (infrastructure errors) don't count as passes or failures. They are replaced, up to 3 extra launches (`AQ_ADAPTIVE_EXTRA_LAUNCHES`), after which the class can come back `undetermined`.
- **Configurable caps and prices.** `AQ_ADAPTIVE_MAX_WAVE` caps attempts in flight. Prices default to Opus 4.5 list prices (`AQ_PRICE_*_PER_MTOK`). Token counts are terminal-bench's tokenizer estimates and ignore prompt caching, so dollar figures are approximate.
- **Not done:** screening with a cheaper model first. It is not exact against a SOTA-defined label, and the measured savings above come from attempts avoided, not cheaper ones.
