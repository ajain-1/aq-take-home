# Cheat Sheet

## What it is
Upload a coding task → run an AI agent on it N times in parallel on Kubernetes → report which tests passed.
A task is **learnable** if 2–7 of 10 runs pass.

## Where things run

```
YOUR LAPTOP
├── FastAPI process ─────────────── api/ + runner/run_task.py
│     ├── HTTP routes (/submit, /status, /results)
│     ├── 16 worker threads  (1 thread = 1 submission, start → finish)
│     └── SQLite (data/executor.db) ← all state lives here
│
├── Kubernetes (Docker Desktop)
│     └── Job ──► Pod ×N            (1 pod = 1 attempt, runs `tb run`)
│                  │ docker.sock
│                  ▼
└── Docker ──► Task container ×N    (sandbox the AI types into; tests run here)

Shared folder: data/submissions/<id>/  (zip, task files, attempt outputs)
```

```
Pod = the DRIVER (harness + AI loop)   ──controls──►   Task container = the COMPUTER it types on
(Kubernetes manages it)                                (plain Docker; K8s can't see it)
```

## Life of a submission

```
POST /submit (zip)
   │  check params + zip, save row to SQLite (status=queued)      ← fast, returns 202
   ▼
in-memory queue (Python ThreadPoolExecutor, NOT Redis)
   ▼
worker thread runs TaskRunner:
   prepare ─► build image ONCE ─► create Job (N pods) ─► poll every 5s ─► collect ─► cleanup
                                       │
                         pod i: tb run → agent works → tests → results.json
```

## Durability

```
crash/restart ─► read SQLite ─► re-queue anything unfinished ─► re-run TaskRunner
                                                                    │
       every step is safe to repeat:                                ▼
       zip extracted?      → skip
       image exists?       → skip build
       Job exists (409)?   → reattach, don't relaunch (no double-paying)
```
- 1 crashed pod → K8s retries just that attempt once (`backoffLimitPerIndex: 1`).
- Pod deadline = agent timeout + test timeout + 10 min, counted from pod start (queue time doesn't count).
- Cleanup always runs (Jobs, containers, networks, images).

## Scaling (today → production)

```
TODAY (1 machine)                       PRODUCTION
─────────────────                       ──────────
API + workers in 1 process      ──►     API (many copies)  |  Workers (many copies)
SQLite file                     ──►     Postgres (shared, row locks so 1 worker per submission)
shared local folder             ──►     S3 (pods upload outputs)
1 node, fixed capacity          ──►     cluster autoscaler adds nodes for Pending pods
docker.sock (root on node)      ──►     sandboxed runtime (gVisor/Kata/sysbox) + image registry
poll K8s every 5s               ──►     watch events
```
**Cost reality:** ~98% of spend is LLM tokens, not compute. Save by running fewer attempts and using fewer tokens.

---

# Stretch goals

## A. UI — `GET /ui`

```
Dashboard ─► Task page ─► Run page ─► Attempt page
 (all tasks)  (per-test     (live phase,   (turn-by-turn: what the AI saw,
              grid across    attempt cards) what it typed, terminal replay)
              runs)
```
Plain JS, no build step. Polls every 2.5–5s. Renders text only (no `innerHTML`) so agent output can't inject markup.

## B. Cost — adaptive waves (`strategy=adaptive`)
Don't always run 10. Stop as soon as the 10-run answer **can't change**:

```
passes ≥ 8                  → too_easy
failures ≥ 9                → too_hard
passes ≥ 2 AND failures ≥ 3 → learnable
```

```
wave 1: 5 attempts  (min runs before ANY answer is possible)
   ├─ decided? ─► stop
   └─ no ──► wave 2: min runs still needed ──► ... (never more than 10)
```
- **Exact:** same label as running 10, always (checked all 1024 outcome sequences).
- **7.85 runs avg vs 10 → 22% cheaper** ($6.05 → $4.75 per task).
- Optional `confidence=0.95` → 27% cheaper, 0.5% wrong labels.
- Rejected: screening with a cheap model — same task scored 10/10 on Opus, 2/10 on GPT-4.1-mini.

## C. Task quality — validation before spending money (`validation=static|full`)

```
static checks ──► image probe ──► reference runs ──► PASS → run the AI
 (ms, read files)  (build image,    oracle ×2 must pass
                    check dirs/      (same results each time)
                    tools exist)     nop ×1 must fail
     │                  │                  │
     └──── any error ───┴──────────────────┴──► REJECT (no AI money spent)
```
Cheapest first. Caught every bug in the original tasks but one (5 of 6 tasks were broken).

## D. Insights — `GET /insights/{id}`
Turns N runs into findings a customer can act on, and only publishes what's proven:

```
run artifacts ──► rules find patterns ──► each claim cites evidence (quote + file + line)
                                                  │
                                  verifier re-reads the files independently
                                          │                     │
                                     all verified          any fails
                                          ▼                     ▼
                                      published         withheld (rejected_insights)
```
Reports: pass rate ± interval, per-test pass rates, why each attempt failed, "hidden requirements"
(strings tests check that the instruction never mentions).
**Example:** log-rotation 0/5 → tests needed headings the instruction never stated → fixed → 10/10.
