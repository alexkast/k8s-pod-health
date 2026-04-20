"""Tests for parser.py: parsing, sanitization, and secret stripping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pod_health.parser import parse_pods, sanitize_for_ai

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_parse_podlist() -> None:
    pods = parse_pods(_load("healthy.json"))
    assert len(pods) == 2
    assert pods[0].metadata.name == "nginx-deployment-5c689d88b-xk2jt"


def test_parse_single_pod() -> None:
    pods = parse_pods(_load("single_pod.json"))
    assert len(pods) == 1
    assert pods[0].metadata.name == "standalone-pod"


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_pods("not json at all {{{")


def test_parse_rejects_unknown_kind() -> None:
    data = json.dumps({"kind": "Deployment", "metadata": {}})
    with pytest.raises(ValueError, match="Unrecognized"):
        parse_pods(data)


def test_parse_crashloop_container_status() -> None:
    pods = parse_pods(_load("crashloop.json"))
    cs = pods[0].status.container_statuses[0]
    assert cs.restart_count == 12
    assert cs.state.waiting is not None
    assert cs.state.waiting.reason == "CrashLoopBackOff"


def test_parse_oomkilled_last_state() -> None:
    pods = parse_pods(_load("oomkilled.json"))
    cs = pods[0].status.container_statuses[0]
    assert cs.last_state.terminated is not None
    assert cs.last_state.terminated.reason == "OOMKilled"
    assert cs.last_state.terminated.exit_code == 137


def test_parse_init_container_statuses() -> None:
    pods = parse_pods(_load("init_failure.json"))
    assert len(pods[0].status.init_container_statuses) == 1
    init_cs = pods[0].status.init_container_statuses[0]
    assert init_cs.name == "db-migrate"
    assert init_cs.state.waiting is not None
    assert init_cs.state.waiting.reason == "CrashLoopBackOff"


def test_parse_owner_references() -> None:
    pods = parse_pods(_load("crashloop.json"))
    assert len(pods[0].metadata.owner_references) == 1
    ref = pods[0].metadata.owner_references[0]
    assert ref.kind == "ReplicaSet"
    assert ref.name == "backend-deployment-7f4d92a1c"


# ── managedFields exclusion ──────────────────────────────────────────────────


def test_managed_fields_excluded() -> None:
    """managedFields must never appear in parsed models (it's massively bloated)."""
    pods = parse_pods(_load("healthy.json"))
    # Pydantic model has no managedFields attribute — model_config extra=ignore drops it
    pod_dict = pods[0].model_dump()
    assert "managedFields" not in pod_dict
    assert "managed_fields" not in pod_dict


# ── Sanitization ─────────────────────────────────────────────────────────────

_SECRET_KEYS = {"env", "envFrom", "value", "secretKeyRef", "volumes", "volumeMounts"}


def _has_secret_key(obj: object) -> bool:
    """Recursively check that no sensitive keys exist in the sanitized output."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SECRET_KEYS:
                return True
            if _has_secret_key(v):
                return True
    elif isinstance(obj, list):
        return any(_has_secret_key(item) for item in obj)
    return False


def test_sanitize_strips_secrets() -> None:
    """healthy.json has env + volumeMounts in spec — they must be stripped."""
    pods = parse_pods(_load("healthy.json"))
    sanitized = sanitize_for_ai(pods)
    assert not _has_secret_key(sanitized), "Sanitized output contains sensitive keys!"


def test_sanitize_retains_diagnostic_fields() -> None:
    pods = parse_pods(_load("crashloop.json"))
    sanitized = sanitize_for_ai(pods)
    pod = sanitized[0]
    assert pod["name"] == "backend-deployment-7f4d92a1c-abcde"
    assert pod["namespace"] == "production"
    assert pod["phase"] == "Running"
    containers = pod["containers"]
    assert len(containers) == 1
    assert containers[0]["restartCount"] == 12
    assert containers[0]["state"]["waiting"]["reason"] == "CrashLoopBackOff"


def test_sanitize_oomkilled_last_state_preserved() -> None:
    pods = parse_pods(_load("oomkilled.json"))
    sanitized = sanitize_for_ai(pods)
    last_state = sanitized[0]["containers"][0]["lastState"]
    assert last_state["terminated"]["reason"] == "OOMKilled"


def test_sanitize_includes_resource_limits() -> None:
    pods = parse_pods(_load("healthy.json"))
    sanitized = sanitize_for_ai(pods)
    limits = sanitized[0]["resourceLimits"]
    assert "nginx" in limits
    assert limits["nginx"]["limits"]["memory"] == "128Mi"


def test_sanitize_no_annotations() -> None:
    """Annotations must never be included (may contain tokens/credentials)."""
    pods = parse_pods(_load("healthy.json"))
    sanitized = sanitize_for_ai(pods)
    for pod in sanitized:
        assert "annotations" not in pod
