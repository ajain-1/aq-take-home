# Robustness verification

Two layers of evidence:

- **Unit tests** (`tests/`, `python -m pytest tests`). They drive `TaskRunner` with a fake cluster client and a temporary data directory, plus the store, bundle validation, Kubernetes parsing, result collection and the API routes.
- **Live scenarios** (`tests/robustness/live_scenarios.py`). These run against a real API, the Docker Desktop Kubernetes cluster and the host Docker daemon. They use fixture tasks (`tests/fixtures/rb-*`) and the oracle/nop agents only, so no LLM calls. Each scenario records what it observed in `live_results.json`.

## Live scenarios

| Measure | Scenario | How it is triggered | Observed |
|---|---|---|---|
| Upload validation | `validation_rejections` | path traversal, symlink, missing files, bad YAML, unknown `resource_class`, not a ZIP, oversized, `n_attempts` 0 / 11 / "abc", unknown agent | All 11 cases returned 422; none were tracked and nothing escaped the data directory |
| Validation gate | `gate_static_reject` | `validation=static` and `validation=full` on a task without `WORKDIR` | Both returned 422 with a string `detail` and a report naming `workdir`; nothing was tracked |
| Gate under restart | `gate_full_restart_mid_validation` | `validation=full`; the API is SIGKILLed while an oracle/nop reference run is in flight | The validation passed all 4 stages and the gated run completed. Each reference run had exactly one wave and one pod per attempt, and only the gated submission was resumed |
| Parallel attempts, pod logs, cleanup | `happy_parallel_attempts` | 2 attempts | Both passed, a `pod-try-0.log` was saved per attempt, and nothing leaked (Jobs, containers, networks, images) |
| Agent timeout | `agent_timeout` | the solution sleeps past `max_agent_timeout_sec` | `failure_mode: agent_timeout`; the submission completed (unresolved) |
| Task-container memory | `task_container_oom` | the solution allocates beyond the `small` class | Container capped at 1 GB, no swap, 1 CPU; the OOM kill was flagged in `infrastructure_issues` |
| Build failure | `build_failure` | `RUN exit 3` in the Dockerfile | Failed with the build error; no attempts launched |
| Crash, retry, partial results, orphans | `crash_retry_partial_orphans` | `docker kill` of attempt 1's pod twice | Attempt 0 resolved; attempt 1 errored with exit code 137 after 1 retry. The retry removed the orphaned task container, both tries' logs were kept, and the manifest uses a `secretKeyRef` and never contains the key |
| Per-try deadline | `job_deadline` | the solution hangs | Each try was stopped by its pod's own deadline and the attempt failed with `DeadlineExceeded` after one retry |
| Restart while running | `restart_sigkill_while_running` | API SIGKILLed mid-attempt | Resumed: the running attempt was adopted (0 retries) and completed |
| Restart while building | `restart_sigterm_while_building` | API SIGTERMed during the image build | Completed after the restart |
| Job deleted while the API was down | `restart_after_job_vanished` | API SIGKILLed, then the Job deleted | Not relaunched; the attempt was reported as `job failed: JobNotFound` |
| Queued backlog | `restart_with_queued_backlog` | worker pool of 1, two submissions, SIGKILL | The second stayed `queued` while the first ran; both completed after the restart |
| Harness OOM | `harness_oom_retry` | `AQ_HARNESS_MEMORY_LIMIT=48Mi` | The pod was OOM-killed, retried once, and the attempt reported `OOMKilled` |
| Unstartable pods | `unstartable_pod_fails_fast` | `AQ_RUNNER_IMAGE` set to a missing image | Failed in seconds with `ErrImageNeverPull`, well before the deadline |
| Build timeout | `build_timeout` | `AQ_BUILD_TIMEOUT_SEC=15` with a slow build | Failed with "timed out after 15s" |
| Adaptive restart mid-wave | `adaptive_restart_mid_wave` | waves of 2; the API is SIGKILLed during wave 1 | 4 waves of 2 decided `too_easy`. Every attempt ran exactly once, because the in-flight wave was re-attached |
| Secret handling | `secret_not_leaked` | grep the whole data directory for the key | No file contains the key |

`live_results.json` holds the full evidence for each scenario: submission IDs, results excerpts, leftover checks and durations. Most scenarios ran on code from before the queue-aware deadline change; the per-try deadline, crash/retry/orphans, vanished Job, gate restart, harness OOM and secret scenarios were re-run on the current code.

## Bugs found and fixed

- **Transient cluster errors:** one apiserver error during polling used to fail the submission, and cleanup then deleted the Job. Polling now retries until the deadline.
- **Misattributed Job failures:** when a Job failed (or vanished), the attempts whose pods were gone were reported as "no results (pod state: pending)". They now report the Job's reason (`job failed: JobNotFound`, …), scoped to the failing wave. Attempts that had already failed on their own keep their pod's reason (for example `OOMKilled`).
- **Rejected Jobs:** Kubernetes Job rejections are reported concisely instead of as a raw API dump.
- **Zero values:** an explicit `n_attempts=0` or `agent=""` was silently replaced by the default (`x or default`). It is now rejected.
- **Wave planning race:** two concurrent callers could each append a wave. Planning now happens inside one store update.
- **Concurrent runs:** the same submission could execute in two threads. `TaskRunner.run` now refuses to start a submission that is already running.
- **Report gap:** validation reports now show the submission a validation gates.

## Not verified live

- The queue cap (`AQ_MAX_QUEUE_SEC`). It is covered by unit tests (`tests/test_deadlines.py`), but no live fixture can be made unschedulable without starving the shared cluster.
- `adaptive_wave1_pod_failure` (a crashed wave-1 attempt replaced by an extra launch). It was not re-run after the deadline rework; the same logic is covered by unit tests.
