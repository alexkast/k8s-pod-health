"""Claude AI integration for explaining pod issues and suggesting fixes."""

from __future__ import annotations

import json
import os
from typing import Any

from pod_health.analyzer import HealthReport

_SYSTEM_PROMPT = """\
You are a Kubernetes expert. Given pod health issues, explain root causes and suggest specific \
kubectl/yaml fixes. Be concise and actionable.

When you lack sufficient context to diagnose a root cause, suggest the specific kubectl commands \
the user should run next (e.g., `kubectl describe pod <name>`, `kubectl logs <name>`, \
`kubectl get events --field-selector involvedObject.name=<name>`).

Format your response with clear sections per issue type. Use markdown."""

_MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
}


def get_ai_analysis(report: HealthReport, model: str = "haiku") -> str:
    """Send sanitized, aggregated issues to Claude and return markdown analysis.

    Returns empty string if API key is missing or on error (caller shows warning).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")

    # Only send unhealthy pods
    unhealthy_pods = [
        p for p in report.pod_reports if any(i.severity in ("critical", "warning") for i in p.issues)
    ]
    if not unhealthy_pods:
        return ""

    payload = _build_payload(report, unhealthy_pods)

    import anthropic  # lazy import to avoid startup cost when --no-ai

    client = anthropic.Anthropic(api_key=api_key)
    model_id = _MODEL_MAP.get(model, _MODEL_MAP["haiku"])

    try:
        message = client.messages.create(
            model=model_id,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        return str(message.content[0].text)  # type: ignore[union-attr]
    except anthropic.AuthenticationError as e:
        raise RuntimeError(f"Invalid API key: {e}") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError(f"Rate limit exceeded: {e}") from e
    except anthropic.APITimeoutError as e:
        raise RuntimeError(f"API timeout: {e}") from e
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic API error: {e}") from e


def _build_payload(report: HealthReport, unhealthy_pods: Any) -> dict[str, Any]:
    """Build a compact, sanitized payload for the LLM."""
    aggregated = [
        {
            "controller": f"{a.controller_kind}/{a.controller_name}" if a.controller_kind else "standalone",
            "namespace": a.namespace,
            "affectedPods": a.count,
            "severity": a.severity,
            "issue": a.message,
            "podNames": a.pod_names[:3],  # cap to 3 examples to save tokens
        }
        for a in report.aggregated_issues
    ]

    return {
        "summary": {
            "totalPods": report.total,
            "critical": report.critical,
            "warning": report.warning,
            "healthy": report.healthy,
        },
        "issues": aggregated,
    }
