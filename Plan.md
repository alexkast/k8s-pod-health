# K8s Pod Health Analyzer — Implementation Plan

## Context

Build a Python CLI tool that takes `kubectl get pods -o json` output and produces a rich, AI-powered health report. The tool should be demoable in 2 minutes, visually impressive with `rich` output, and showcase Claude AI for explaining pod issues and suggesting fixes.

## Architecture

```
stdin/file → [Parser] → [Sanitizer] → [Analyzer] → [Aggregator] → [AI Advisor] → [Renderer]
               │            │              │             │               │              │
          pydantic     strip env/      pure logic    group by        Claude API     rich tables
          models       secrets/volumes (issue detect) controller     (explain+fix)   + panels
```

- **AI is ON by default** (`--no-ai` flag to disable for offline use)
- **Input**: stdin pipe (`kubectl get pods -o json | pod-health`) or `--file pods.json`
- **Scope**: Pods only (status, restarts, OOM, image pulls, pending, resource limits)

### Security: Data Sanitization (before AI)

Raw `kubectl get pods -o json` dumps the full Pod spec including `env` blocks with plain-text secrets, volume definitions with inline sensitive data, and annotations that may hold credentials. **The parser/sanitizer MUST strip all sensitive fields before sending anything to the LLM.** Only send to Claude: container names, image names, statuses, reasons, restart counts, resource limits, and conditions.

## Tech Stack

- Python 3.11+, `uv` for deps
- `typer` (CLI), `rich` (output), `pydantic` (models), `anthropic` (AI)
- `pytest` (testing)

## Project Structure

```
01-p/
├── CLAUDE.md
├── Plan.md
├── README.md
├── pyproject.toml
├── .github/
│   ├── dependabot.yml          # automated dependency updates (pip ecosystem)
│   └── workflows/
│       ├── ci.yml              # lint + type-check + tests
│       └── security.yml        # Trivy scan → GitHub Security tab (SARIF)
├── src/
│   └── pod_health/
│       ├── __init__.py
│       ├── cli.py          # typer app, entry point
│       ├── parser.py       # pydantic models + JSON parsing
│       ├── analyzer.py     # rule-based issue detection
│       ├── ai_advisor.py   # Claude integration
│       └── renderer.py     # rich output formatting
├── tests/
│   ├── fixtures/
│   │   ├── healthy.json          # all pods running fine
│   │   ├── crashloop.json        # CrashLoopBackOff scenario
│   │   ├── imagepull.json        # ImagePullBackOff
│   │   ├── oomkilled.json        # OOMKilled (in lastState, current state running)
│   │   ├── duplicate_errors.json # 10 pods same Deployment, same error (aggregation test)
│   │   ├── init_failure.json      # init container CrashLoopBackOff
│   │   ├── pending.json          # stuck pending pods
│   │   ├── mixed.json            # healthy + unhealthy mix
│   │   └── single_pod.json       # single pod (not PodList)
│   ├── test_parser.py      # includes sanitization tests (env/secrets stripped)
│   └── test_analyzer.py    # includes OOMKilled lastState detection + aggregation
└── examples/
    └── sick-cluster.json   # dramatic demo fixture
```

## Implementation Steps

### Step 1: Project scaffolding
- `uv init`, configure `pyproject.toml` with dependencies and `[project.scripts]` entry point
- Create directory structure

### Step 2: Parser (`parser.py`)
- Pydantic models for K8s pod JSON structure (PodList, Pod, PodStatus, ContainerStatus)
- Use minimal pydantic models covering only the fields we need (status, containers, conditions, resources) — don't try to model the full K8s spec
- **Explicitly exclude `managedFields`** from pydantic models (use `model_config = ConfigDict(extra="ignore")`) — this field is massively bloated server-side-apply metadata that will spike memory for no diagnostic value
- **Parse `initContainerStatuses`** alongside `containerStatuses` — many pod failures happen during init phase (e.g., `Init:CrashLoopBackOff`, `Init:ImagePullBackOff`) which block main containers from ever starting
- `parse_pods(json_str: str) -> list[Pod]` — handles both PodList and single Pod
- `sanitize_for_ai(pods: list[Pod]) -> list[dict]` — strips `env`, `envFrom`, `volumes`, `volumeMounts`, annotations, and any field not needed for diagnosis. Returns only: container names, images, statuses, reasons, exit codes, restart counts, resource limits/requests, conditions
- Graceful error on malformed JSON with human-friendly message

### Step 3: Analyzer (`analyzer.py`)
- `analyze_pod(pod: Pod) -> PodReport` — returns issues list with severity (critical/warning/info)
- Detection rules:
  - CrashLoopBackOff → critical (including `Init:CrashLoopBackOff` from init containers)
  - ImagePullBackOff → critical (including `Init:ImagePullBackOff` from init containers)
  - OOMKilled → critical (check BOTH `state.terminated.reason` AND `lastState.terminated.reason` — a pod that was OOMKilled and restarted will show `running` in current state but `OOMKilled` in `lastState`)
  - High restart count (>5) → warning
  - Not ready containers → warning
  - Pending phase → warning
  - No resource limits/requests set → **warning** (causes noisy neighbor problems and node OOM in multi-tenant clusters)
  - Completed/Succeeded → info (skip)
- `resolve_controller_name(owner_ref: OwnerReference) -> str` — resolve the logical controller name. Different controllers use different suffix patterns:
  - **ReplicaSet** (Deployment pods): strip pod-template-hash suffix (e.g., `nginx-deployment-5c689d88b` → `nginx-deployment`)
  - **CronJob**: strip numeric timestamp suffix (e.g., `backup-1713180000` → `backup`)
  - **StatefulSet**: ordinal index (`web-0`, `web-1`) — no stripping needed, these are intentionally distinct
  - **DaemonSet**: no suffix on pod name — return as-is
  - Regex: `(-[a-z0-9]{8,10}$|-[0-9]+$)` — covers both hash and timestamp patterns. If no match, return raw `ownerReference.name` unchanged (safe fallback for StatefulSets, DaemonSets, and unknown controllers)
- `aggregate_issues(reports: list[PodReport]) -> list[AggregatedIssue]` — group identical errors by resolved controller name + error signature. Example: instead of 50 separate `ImagePullBackOff` reports, produce one: "50 pods from Deployment/nginx-deployment failing with ImagePullBackOff for image `nginx:latst`"
- `analyze_all(pods: list[Pod]) -> HealthReport` with summary stats and aggregated issues

### Step 4: AI Advisor (`ai_advisor.py`)
- `get_ai_analysis(report: HealthReport) -> str` — sends **sanitized, aggregated** issues to Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) by default — fast, cheap, sufficient for explaining known K8s issue patterns. `--model` CLI flag allows switching to Sonnet if deeper cross-issue reasoning is needed
- Input is the output of `sanitize_for_ai()` + `aggregate_issues()` — never raw pod JSON
- System prompt: "You are a Kubernetes expert. Given pod health issues, explain root causes and suggest specific kubectl/yaml fixes. Be concise. When you lack sufficient context to diagnose a root cause, suggest the specific kubectl commands the user should run next (e.g., `kubectl describe pod`, `kubectl logs`, `kubectl get events`)."
- Send only unhealthy pods (don't waste tokens on healthy ones)
- Handle: missing API key (graceful skip with warning), rate limits, timeouts
- `ANTHROPIC_API_KEY` env var

### Step 5: Renderer (`renderer.py`)
- Summary panel: total pods, healthy/warning/critical counts
- Pod table: name, namespace, status, restarts, age, issues (color-coded)
- AI analysis panel (if enabled): rich Markdown rendering of Claude's response
- Use `rich.console`, `rich.table`, `rich.panel`, `rich.markdown`

### Step 6: CLI (`cli.py`)
- `typer` app with main command
- Options: `--file PATH`, `--no-ai`, `--model` (default `haiku`, alternative `sonnet`), `--namespace` (filter), `--json` (raw JSON output)
- Stdin detection: `sys.stdin.isatty()` — if not a TTY, read from stdin
- Error if neither stdin nor --file provided
- Loading spinner while AI processes

### Step 7: Test fixtures + tests
- Create realistic fixture JSON files (from actual kubectl output structure)
- `test_parser.py`:
  - Parse valid JSON, handle PodList vs single pod, reject invalid JSON
  - **Sanitization assertion**: verify `sanitize_for_ai()` output contains zero dict keys named `env`, `envFrom`, `value`, `secretKeyRef`, `volumes`, `volumeMounts` — prevents future contributors from accidentally leaking secrets
  - Verify `managedFields` is not present in parsed models
- `test_analyzer.py`:
  - One test per issue type, verify severity and message
  - OOMKilled detection via `lastState` (current state `running`)
  - Init container failure detection (`Init:CrashLoopBackOff`)
  - Aggregation: 10 pods from same Deployment → single `AggregatedIssue`
  - ReplicaSet hash stripping: pods from `nginx-abc123` and `nginx-def456` aggregate under `nginx`

### Step 8: README.md
- Project title + one-line description
- Architecture diagram (the ASCII pipeline from this plan)
- Installation (source-based only, no PyPI/registry references):
  - Clone: `git clone <repo-url> && cd pod-health`
  - Run directly: `cat pods.json | uv run pod-health`
  - Or install as local tool: `uv tool install .`
- Usage examples:
  - `kubectl get pods -o json | uv run pod-health`
  - `uv run pod-health --file pods.json`
  - `uv run pod-health --file pods.json --no-ai`
  - `uv run pod-health --file pods.json --model sonnet`
- CLI options table (`--file`, `--no-ai`, `--model`, `--namespace`, `--json`)
- Environment variables: `ANTHROPIC_API_KEY`
- Example output screenshot placeholder (can paste after first run)
- Security note: tool sanitizes pod data before sending to AI — no secrets leak

### Step 9: GitHub Actions CI & Security
> **Note:** CD/Release pipeline is out of scope for now. Only CI and security scanning.

#### Dependabot (`.github/dependabot.yml`)
- Configure for `pip` ecosystem to auto-create PRs for dependency updates

#### CI Workflow (`.github/workflows/ci.yml`)
- **Trigger**: push to `main`, pull requests
- **Setup**: use `astral-sh/setup-uv` action for fast environment setup with caching
- **Python version matrix**: 3.11, 3.12
- **Jobs**:
  1. **lint** — `ruff check src/ tests/` and `ruff format --check src/ tests/`
  2. **type-check** — `mypy --strict src/`
  3. **test** — `uv run pytest` (AI tests use mocked API calls, no `ANTHROPIC_API_KEY` needed in CI)

#### Security Workflow (`.github/workflows/security.yml`)
- **Trigger**: push to `main`, pull requests, plus scheduled weekly run
- **Steps**:
  1. `aquasecurity/trivy-action` — scan repository (`fs,config` mode) for dependency CVEs and misconfigurations
  2. Set Trivy output format to `sarif`
  3. `github/codeql-action/upload-sarif` — push results to GitHub Security tab for centralized visibility

## Verification

1. `uv run pod-health --file examples/sick-cluster.json` — should show rich report
2. `cat examples/sick-cluster.json | uv run pod-health` — same via stdin
3. `uv run pod-health --file examples/sick-cluster.json --no-ai` — works without API key
4. `uv run pytest` — all tests pass
5. Demo flow: show help screen → run with sick cluster → show AI analysis
6. `ruff check src/` — no linting issues
7. Push to GitHub → CI workflow passes all jobs (lint + type-check + test)
8. Push to GitHub → Security workflow runs Trivy, results visible in GitHub Security tab
