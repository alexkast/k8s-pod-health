# K8s Pod Health Analyzer

AI-powered CLI that takes `kubectl get pods -o json` output and produces a rich, color-coded health report with Claude-powered root cause analysis.

## Architecture

```
stdin/file → [Parser] → [Sanitizer] → [Analyzer] → [Aggregator] → [AI Advisor] → [Renderer]
               │            │              │             │               │              │
          pydantic     strip env/      pure logic    group by        Claude API     rich tables
          models       secrets/volumes (issue detect) controller     (explain+fix)   + panels
```

**Security**: Pod data is sanitized before reaching the AI — `env`, `envFrom`, `volumes`, `volumeMounts`, and annotations are stripped to prevent secret leakage.

## Installation

Clone and run directly with `uv` (no global install needed):

```bash
git clone <repo-url> && cd pod-health
cat pods.json | uv run pod-health
```

Or install as a local tool:

```bash
uv tool install .
```

## Usage

```bash
# Pipe from kubectl
kubectl get pods -o json | uv run pod-health

# From a file
uv run pod-health --file pods.json

# Disable AI (no API key needed)
uv run pod-health --file pods.json --no-ai

# Use Claude Sonnet for deeper analysis
uv run pod-health --file pods.json --model sonnet

# Filter by namespace
uv run pod-health --file pods.json --namespace production

# JSON output for scripting
uv run pod-health --file pods.json --json
```

## CLI Options

| Flag | Description | Default |
|------|-------------|---------|
| `--file PATH` | Path to kubectl JSON output | stdin |
| `--no-ai` | Skip AI analysis (works offline) | false |
| `--model` | AI model: `haiku` or `sonnet` | `haiku` |
| `--namespace` | Filter pods by namespace | all |
| `--json` | Output raw JSON report | false |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Required for AI analysis. Get one at console.anthropic.com |

## Example Output

```
╭───────────── K8s Pod Health Report ──────────────╮
│ Total: 9   Healthy: 2   Warning: 2   Critical: 5 │
╰──────────────────────────────────────────────────╯

 POD                              NAMESPACE   PHASE    RESTARTS  ISSUES
 nginx-deployment-5c689d88b-…    production  Running         —  OK
 api-deployment-7f4d92a1c-…      production  Running        17  CrashLoopBackOff
 worker-deployment-d9e3f7a2b-…   production  Running         5  OOMKilled (last restart)
 frontend-deploy-abc12345b-…     staging     Pending         —  ImagePullBackOff

╭──────────────────────── Aggregated Issues ────────────────────────╮
│ [CRITICAL] ReplicaSet/api-deployment (production): CrashLoopBackOff — 3 pods │
│ [CRITICAL] ReplicaSet/worker-deployment (production): OOMKilled — 1 pod      │
╰───────────────────────────────────────────────────────────────────╯

╭──────────────────── AI Analysis (Claude) ──────────────────────╮
│ ## CrashLoopBackOff — api-deployment                           │
│ Container exits immediately after start. Check logs:          │
│ `kubectl logs <pod> --previous`                               │
│ ...                                                            │
╰────────────────────────────────────────────────────────────────╯
```

## Security Note

Pod specs contain plain-text secrets in `env` blocks, volume definitions, and annotations. This tool sanitizes all pod data before sending anything to the AI — only container names, images, statuses, restart counts, and resource limits are forwarded. No secrets leave your machine.
