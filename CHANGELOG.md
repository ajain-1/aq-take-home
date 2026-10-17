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
