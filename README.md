# AfterQuery SWE Take-Home: Task Executor

## Context

You're building a system that runs AI agents against coding tasks on Kubernetes, then reports whether the agent solved each task.

Each task submission should create Kubernetes Jobs that run Terminal-Bench agents in isolation on Docker Desktop's built-in K8s cluster. An agent gets a task instruction, works in a terminal to solve it, then tests verify the result. Your system should support running N parallel agent attempts per task (e.g., 10 runs) and aggregating the results.

## What's Provided

- `api/main.py` - FastAPI application with stubbed endpoints
- `runner/run_task.py` - Task execution script (incomplete)
- `tasks/` - 6 tasks in our standard format, with Dockerfiles, tests, and reference solutions
- `terminal_bench/` - The Terminal-Bench agent framework (source code). This is the agent that solves tasks. Read this to understand how agents work.
- `scripts/` - Helper scripts for testing

### How Terminal-Bench Works

Terminal-Bench (`tb`) is our agent harness. Read the source code in `terminal_bench/` to understand how it works — the CLI entry point is `terminal_bench/cli/tb/main.py`, agents are in `terminal_bench/agents/`, and the harness is in `terminal_bench/harness/`. The `pyproject.toml` inside `terminal_bench/` lists all dependencies.

Your system should use the `tb` CLI to run the `terminus-1` agent with `anthropic/claude-opus-4-5-20250514` against each task. (The key above is an OpenRouter key, so you'll need to route the model through OpenRouter accordingly.)

Each task also has a `solution.sh` — a pre-written deterministic solution you can use to test your infrastructure while building it.

### Task Format

Each task directory contains:

```
task-name/
├── task.yaml           # Task instruction, timeouts, resource class, and metadata
├── Dockerfile          # Container environment setup
├── run-tests.sh        # Runs pytest to verify the solution
├── solution.sh         # Deterministic reference solution (for testing without an agent)
├── tests/
│   └── test_outputs.py # Pytest tests that verify the task was solved
└── [task-specific files]
```

Your system should read the `task.yaml` metadata and use it to configure execution (timeouts, resource allocation, etc.).


### Execution

Your system should execute tasks as Kubernetes Jobs and produce structured test results. All 6 tasks should run concurrently, not sequentially. When running N attempts per task, think about which steps need to happen N times and which don't.

## Requirements

### Part 1: Get It Working

Implement the API and runner so that:

- `POST /submit` accepts a task ZIP file, builds the image, creates a K8s Job, and returns a `submission_id`
- `GET /status/{submission_id}` returns current Job status
- `GET /results/{submission_id}` returns structured test results with per-test pass/fail

Verify with: `bash scripts/submit_task.sh csv-to-json-cli-fix`

All 6 tasks should pass through the pipeline and produce test results.

### Part 2: Make It Robust

Your system will be running long-lived K8s Jobs, managing Docker resources, and tracking state across async operations. Make it production-ready — think about what happens when things go wrong, take too long, or crash halfway through.


## Setup

### Prerequisites

- Docker Desktop with **Kubernetes enabled** (Settings → Kubernetes → Enable Kubernetes)
- `kubectl` configured and pointing to `docker-desktop` context
- Python 3.12+
- OpenRouter API key: `sk-or-v1-REPLACE_WITH_YOUR_OPENROUTER_KEY` (provided to you separately)

Verify your setup:

```bash
kubectl cluster-info
kubectl get nodes
```

### Running the API

```bash
pip install -r api/requirements.txt
cd api
uvicorn main:app --reload --port 8000
```

### Submitting a Task

```bash
# Submit a task directory (auto-zips it)
bash scripts/submit_task.sh csv-to-json-cli-fix

# Check status
bash scripts/check_status.sh <submission_id>

# Submit all 6 tasks
bash scripts/run_all.sh
```

### Stretch Goals

If you finish early:

**A. Simple UI** - Build a web frontend where you can drag and drop a zipped task, see it run, view the agent's episode/turns, and see whether tests passed or failed.

**B. Inference cost optimization** - We classify a task as a "learnable data point" if, across 10 runs with a SOTA model, between 2 and 7 runs have all tests passing. Running 10 SOTA runs per task is expensive. Design and implement a strategy that reduces total inference cost while still correctly identifying learnable data points.

**C. Task quality checks** - Before running expensive agent evaluations, you want confidence that the task infrastructure itself is sound. Read the agents in `terminal_bench/agents/` and design a pre-submission validation pipeline that catches broken tasks before they waste compute.

**D. Beyond pass/fail** — A submission that reports "3/10 runs passed" tells a customer almost nothing. Each run produces a full trajectory — the agent's actions, terminal output, and where things went wrong. Design and build something that turns N runs of a task into *insight a customer could act on* — and that they can **trust**: an insight is only as good as the evidence behind it, so how you keep it grounded and honest matters as much as how clever it is. We're deliberately not specifying the output — deciding what's valuable, and how to make it trustworthy, is the point.

## Evaluation Criteria

In order of importance:

1. **Does it work end-to-end?** - Can you submit all 6 tasks and get results via K8s Jobs?
2. **System design** - How did you decompose the runner? Separation of concerns?
3. **Robustness** - What happens when things go wrong?
4. **Code quality** - Clean, readable, well-structured

Include:
- All source code
- `CHANGELOG.md` describing what you did, why, and any design tradeoffs
- Your git commit history (we read it)
- One committed sample run — commit the output of at least one real `terminus-1` run (e.g. under `results/sample-run/`) so we can see the agent actually executed
