"""Tests for analyzer.py: issue detection, controller resolution, aggregation."""

from __future__ import annotations

from pathlib import Path

from pod_health.analyzer import analyze_all, analyze_pod, resolve_controller_name
from pod_health.parser import OwnerReference, parse_pods

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def _issues(fixture: str) -> list[str]:
    pods = parse_pods(_load(fixture))
    report = analyze_all(pods)
    return [i.message for r in report.pod_reports for i in r.issues]


# ── Issue detection ───────────────────────────────────────────────────────────


def test_crashloop_detected() -> None:
    pods = parse_pods(_load("crashloop.json"))
    report = analyze_pod(pods[0])
    critical = [i for i in report.issues if i.severity == "critical"]
    assert any("CrashLoopBackOff" in i.message for i in critical)


def test_imagepull_detected() -> None:
    pods = parse_pods(_load("imagepull.json"))
    report = analyze_pod(pods[0])
    critical = [i for i in report.issues if i.severity == "critical"]
    assert any("ImagePullBackOff" in i.message for i in critical)


def test_oomkilled_via_last_state() -> None:
    """OOMKilled pod currently shows Running — must be detected via lastState."""
    pods = parse_pods(_load("oomkilled.json"))
    cs = pods[0].status.container_statuses[0]
    assert cs.state.waiting is None  # currently running
    assert cs.last_state.terminated is not None
    assert cs.last_state.terminated.reason == "OOMKilled"

    report = analyze_pod(pods[0])
    critical = [i for i in report.issues if i.severity == "critical"]
    assert any("OOMKilled" in i.message for i in critical)


def test_high_restart_count_warning() -> None:
    pods = parse_pods(_load("crashloop.json"))
    report = analyze_pod(pods[0])
    # restart count is 12 — should produce a warning
    warnings = [
        i for i in report.issues if i.severity == "warning" and "restart" in i.message.lower()
    ]
    assert warnings, "Expected high restart count warning"


def test_pending_detected() -> None:
    pods = parse_pods(_load("pending.json"))
    report = analyze_pod(pods[0])
    warnings = [i for i in report.issues if i.severity == "warning"]
    assert any("Pending" in i.message for i in warnings)


def test_init_container_crashloop() -> None:
    pods = parse_pods(_load("init_failure.json"))
    report = analyze_pod(pods[0])
    critical = [i for i in report.issues if i.severity == "critical"]
    assert any("CrashLoopBackOff" in i.message for i in critical)
    # container label should include init: prefix
    assert any("init:" in i.container for i in critical)


def test_no_resource_limits_warning() -> None:
    pods = parse_pods(_load("mixed.json"))
    report = analyze_all(pods)
    all_issues = [i for r in report.pod_reports for i in r.issues]
    assert any("resource limits" in i.message.lower() for i in all_issues)


def test_healthy_pods_no_critical_issues() -> None:
    pods = parse_pods(_load("healthy.json"))
    report = analyze_all(pods)
    assert report.critical == 0


def test_mixed_correct_counts() -> None:
    pods = parse_pods(_load("mixed.json"))
    report = analyze_all(pods)
    assert report.total == 3
    assert report.critical > 0  # the CrashLoopBackOff pod


# ── Controller name resolution ────────────────────────────────────────────────


def test_resolve_replicaset_hash_stripped() -> None:
    ref = OwnerReference(kind="ReplicaSet", name="nginx-deployment-5c689d88b")
    assert resolve_controller_name(ref) == "nginx-deployment"


def test_resolve_cronjob_timestamp_stripped() -> None:
    ref = OwnerReference(kind="Job", name="backup-1713180000")
    assert resolve_controller_name(ref) == "backup"


def test_resolve_statefulset_unchanged() -> None:
    ref = OwnerReference(kind="StatefulSet", name="redis-statefulset")
    assert resolve_controller_name(ref) == "redis-statefulset"


def test_resolve_daemonset_unchanged() -> None:
    ref = OwnerReference(kind="DaemonSet", name="fluentd-daemonset")
    assert resolve_controller_name(ref) == "fluentd-daemonset"


def test_resolve_two_rs_same_deployment() -> None:
    """Pods from two different ReplicaSets of same Deployment must resolve to same name."""
    ref1 = OwnerReference(kind="ReplicaSet", name="nginx-deployment-5c689d88b")
    ref2 = OwnerReference(kind="ReplicaSet", name="nginx-deployment-7f4d92a1c")
    assert resolve_controller_name(ref1) == resolve_controller_name(ref2) == "nginx-deployment"


# ── Aggregation ───────────────────────────────────────────────────────────────


def test_aggregation_groups_10_pods() -> None:
    """10 pods from same Deployment/RS with CrashLoopBackOff → single AggregatedIssue."""
    pods = parse_pods(_load("duplicate_errors.json"))
    report = analyze_all(pods)
    agg = report.aggregated_issues
    # All 10 pods should collapse into 1 aggregated issue
    assert len(agg) == 1
    assert agg[0].count == 10
    assert agg[0].severity == "critical"
    assert "CrashLoopBackOff" in agg[0].message


def test_aggregation_controller_name_resolved() -> None:
    pods = parse_pods(_load("duplicate_errors.json"))
    report = analyze_all(pods)
    agg = report.aggregated_issues[0]
    # RS suffix should be stripped — controller name is "api-deployment"
    assert agg.controller_name == "api-deployment"


def test_aggregation_caps_pod_names() -> None:
    """pod_names list exists and contains actual pod names."""
    pods = parse_pods(_load("duplicate_errors.json"))
    report = analyze_all(pods)
    agg = report.aggregated_issues[0]
    assert len(agg.pod_names) == 10
    assert all("api-deployment" in name for name in agg.pod_names)
