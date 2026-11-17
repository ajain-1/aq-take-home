# Production & Scaling Cheat Sheet

## Rough numbers (say these first)

```
10k tasks/day × 10 attempts       = 100k attempts/day
100k × ~10 min / 1440 min/day     ≈ 700 attempts running at once
700 × ~1.5 vCPU                   ≈ 1,000 vCPU   ≈ $1k/day compute
100k × $0.60 LLM per attempt      ≈ $60k/day tokens
                                   ─────────────
                                   ~98% of spend = LLM → save on runs & tokens, not servers
submit rate ≈ 0.1 req/s           → API load is trivial; the hard part is supervising long jobs
```

## Target architecture

```
                    ┌──────────────────────────────┐
 client ──HTTPS──►  │ API (stateless, N replicas)  │── presigned URL ──► S3 (task zips)
                    │ auth · validate · 202        │
                    └──────────────┬───────────────┘
                                   │ INSERT status=queued
                                   ▼
                    ┌──────────────────────────────┐
                    │ Postgres                     │  submissions, waves, attempts, leases
                    └──────────────┬───────────────┘
                                   │ claim (SKIP LOCKED + lease)
                                   ▼
                    ┌──────────────────────────────┐
                    │ Workers / controller (M reps)│◄── K8s watch events (Job done, pod failed)
                    └───┬──────────────┬───────────┘
                        │              │
              build ────▼──┐     ┌─────▼────────────┐
              BuildKit ──► Registry  Kueue (quotas, fairness)
                           │     └─────┬────────────┘
                           │           ▼
                           │     K8s Jobs → pods (sandboxed) ──► LLM gateway ──► OpenRouter / Anthropic
                           └────────►  pull image              (rate limits, keys, retries)
                                       │
                                       └──► S3 (attempt outputs, logs, recordings)
```

## What changes, and why

| Today | Production | Why |
|---|---|---|
| API + workers in one process | Separate API and workers | Deploy API without pausing runs; scale each independently |
| SQLite file | Postgres | Shared across machines; row locks |
| In-memory thread pool queue | Postgres queue with leases (or SQS) | Survives crashes; many workers, no double-runs |
| Thread held per submission for hours | Event-driven reconcile loop | Do a step, save, release; wake on K8s events |
| Poll K8s every 5s | Watches / informers | apiserver load ∝ changes, not submissions |
| Local shared folder | S3 | Pods on many machines can't share a folder |
| Build on host Docker, `imagePullPolicy: Never` | BuildKit → registry, tag = hash of task contents | Any node can pull; same task built once |
| `docker.sock` in pod (root on node) | gVisor / Kata / Firecracker or sysbox | Untrusted agent code can't escape |
| 1 node, fixed capacity | Autoscaler (Karpenter) + node pools | Add nodes for Pending pods, remove idle |
| FIFO, no tenants | Kueue + per-tenant quotas | One customer can't starve the rest |

## Work queue with leases (replaces thread pool + resume-on-startup)

```
worker loop:
  SELECT … WHERE status='queued' OR lease_expires_at < now()
  FOR UPDATE SKIP LOCKED LIMIT 1          ← two workers never grab the same row
  set lease_owner=me, lease_expires_at=now()+60s
  do ONE step (build | launch wave | collect | cleanup), save it
  renew lease while waiting · release when done

worker dies ─► lease expires ─► another worker picks it up ─► steps are idempotent ─► no double work
```
At-least-once delivery + idempotent steps = effectively once.

## Images

```
task zip ─► hash(contents) ─► registry has it? ── yes ─► reuse (no build)
                                     │ no
                                     ▼
                         BuildKit (remote, cached layers) ─► push ─► nodes pull
                                                                   (pre-pull base images,
                                                                    lazy pull: SOCI/stargz)
```

## Sandboxing

```
TODAY:   pod ──docker.sock──► host Docker   (pod can do anything on the node)

PROD:    pod [ harness container | task container ]   in a microVM (Kata/gVisor)
              └── exec into task container via K8s, no Docker socket
         NetworkPolicy: task container has NO network; harness may reach the LLM gateway only
```

## Compute scaling

```
Pods Pending (no room) ─► Karpenter adds a node ─► pods schedule
Nodes idle             ─► Karpenter removes them

node pools by resource_class:  small | medium | large
spot instances: oracle/nop/validation runs (cheap to redo)
on-demand:      LLM agent runs (preemption wastes tokens already paid for)
```
- Right-size `resource_class` from measured CPU/memory, not guesses.
- Count the task container in the pod's resource request (today K8s can't see it).

## Fairness & admission

```
submit ─► tenant over quota? ─► 429 / wait in queue
        ─► Kueue admits Jobs by tenant quota, priority, fair share
        ─► global LLM concurrency limit (token bucket per provider/key)
```
**The real ceiling is LLM rate limits, not the cluster.** Start attempts only as fast as the provider allows.

## LLM gateway

```
pods ─► gateway ─► provider
         ├─ rate limiting per key/provider
         ├─ retries with backoff, failover to another key/provider
         ├─ prompt caching (re-sent conversation ≈ 10% price)
         └─ token metering per tenant/submission → budgets & billing
```

## Cost levers (biggest first)

```
1. don't run broken tasks       → validation before running the AI (5 of 6 tasks were broken)
2. run fewer attempts           → adaptive stopping (−22% exact, −27% at 0.5% error)
3. fewer tokens per attempt     → prompt caching, trim old terminal output, turn caps
4. never re-run identical work  → cache results by (task hash, agent, model)
5. guardrails                   → per-tenant budgets, cost estimate before submit
6. compute                      → spot, right-sizing, bin-packing (small slice of spend)
```

## Reliability

```
failure                          handling
───────                          ────────
worker crash                     lease expires → another worker resumes
pod crash / OOM / eviction       retry that attempt only (backoffLimitPerIndex)
node loss                        pods rescheduled; outputs already in S3 survive
LLM 429 / 5xx                    gateway backoff + failover; NOT counted as agent failure
stuck pod                        per-pod deadline + worker backstop deletes the Job
long queue                       queue cap → clear "no capacity" error
bad deploy                       canary tasks (oracle must pass, nop must fail) gate rollout
```
Key rule: **infrastructure errors never count toward the learnable label** (they're replaced, not scored).

## Observability

```
metrics:  queue time · attempt duration · infra-error rate · tokens & $ per attempt
          · pass rate by task/model · failure categories · Pending pods · LLM 429s
traces:   submission → wave → attempt → LLM calls
alerts:   infra-error spike (looks like "too hard" if missed) · queue age · spend vs budget
logs:     structured, tagged with submission_id / attempt
```

## Security & multi-tenancy

- Auth on API and UI; per-tenant namespaces or labels + quotas.
- Secrets from a secret manager, mounted per pod; never logged.
- Untrusted zips: keep the existing extraction checks (no path traversal/symlinks, size caps); build in isolated builders.
- Pin model versions + image digests → reproducible results.

## API changes

```
POST   /submit                 (unchanged, + tenant, + budget)
DELETE /submissions/{id}       cancel → delete Jobs → cleanup
GET    /submissions/{id}/events  SSE/webhooks instead of polling
POST   /datasets               submit many tasks at once
```
