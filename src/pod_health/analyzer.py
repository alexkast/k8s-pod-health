"""Rule-based pod issue detection, aggregation, and controller name resolution."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from pod_health.parser import ContainerStatus, OwnerReference, Pod

Severity = Literal["critical", "warning", "info"]

_RS_SUFFIX_RE = re.compile(r"(-[a-z0-9]{8,10}$|-[0-9]+$)")


@dataclass
class Issue:
    severity: Severity
    message: str
    container: str = ""  # empty = pod-level issue


@dataclass
class PodReport:
    pod_name: str
    namespace: str
    phase: str
    issues: list[Issue] = field(default_factory=list)
    controller_kind: str = ""
    controller_name: str = ""  # resolved (suffix stripped)
    restart_count: int = 0


@dataclass
class AggregatedIssue:
    severity: Severity
    controller_kind: str
    controller_name: str
    namespace: str
    count: int
    message: str
    pod_names: list[str] = field(default_factory=list)


@dataclass
class HealthReport:
    total: int
    healthy: int
    warning: int
    critical: int
    pod_reports: list[PodReport]
    aggregated_issues: list[AggregatedIssue]


def resolve_controller_name(owner_ref: OwnerReference) -> str:
    """Strip suffix to get logical controller name — only for kinds that use suffixes.

    - ReplicaSet (Deployment pods): strip hash suffix e.g. -5c689d88b
    - Job (CronJob pods): strip timestamp suffix e.g. -1713180000
    - StatefulSet, DaemonSet, and all others: return name unchanged
      (their names are intentionally stable/meaningful)
    """
    if owner_ref.kind in ("ReplicaSet", "Job"):
        return _RS_SUFFIX_RE.sub("", owner_ref.name)
    return owner_ref.name


def _check_container(cs: ContainerStatus, prefix: str = "") -> list[Issue]:
    """Detect issues for a single container status (works for init containers too)."""
    issues: list[Issue] = []
    label = f"{prefix}{cs.name}" if prefix else cs.name

    # Check waiting state
    waiting = cs.state.waiting
    if waiting and waiting.reason:
        reason = waiting.reason
        if reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
            issues.append(Issue(severity="critical", message=f"{reason}", container=label))
        elif reason not in ("ContainerCreating", "PodInitializing"):
            issues.append(Issue(severity="warning", message=f"Waiting: {reason}", container=label))

    # Check terminated state (current)
    terminated = cs.state.terminated
    if terminated and terminated.reason == "OOMKilled":
        issues.append(Issue(severity="critical", message="OOMKilled", container=label))

    # Check last state for OOMKilled (pod restarted after OOM)
    last_terminated = cs.last_state.terminated
    if last_terminated and last_terminated.reason == "OOMKilled":
        issues.append(
            Issue(
                severity="critical",
                message=f"OOMKilled (last restart, exit {last_terminated.exit_code})",
                container=label,
            )
        )

    # High restart count
    if cs.restart_count > 5:
        issues.append(
            Issue(
                severity="warning",
                message=f"High restart count: {cs.restart_count}",
                container=label,
            )
        )

    # Not ready (only for non-terminated, non-completed containers)
    if not cs.ready and not (terminated and terminated.reason in ("Completed", "Error")):
        if not issues:  # avoid double-reporting when waiting reason already captured
            issues.append(Issue(severity="warning", message="Container not ready", container=label))

    return issues


def analyze_pod(pod: Pod) -> PodReport:
    """Detect all issues for a single pod."""
    # Skip completed/succeeded pods
    if pod.status.phase in ("Succeeded",):
        owner_ref = pod.metadata.owner_references[0] if pod.metadata.owner_references else None
        return PodReport(
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            phase=pod.status.phase,
            issues=[Issue(severity="info", message="Pod completed successfully")],
            controller_kind=owner_ref.kind if owner_ref else "",
            controller_name=resolve_controller_name(owner_ref) if owner_ref else "",
        )

    issues: list[Issue] = []

    # Init container issues
    for cs in pod.status.init_container_statuses:
        issues.extend(_check_container(cs, prefix="init:"))

    # Main container issues
    for cs in pod.status.container_statuses:
        issues.extend(_check_container(cs))

    # Pending phase
    if pod.status.phase == "Pending":
        msg = pod.status.reason or pod.status.message or "Pod is stuck in Pending"
        issues.append(Issue(severity="warning", message=f"Pending: {msg}"))

    # Missing resource limits/requests (check spec containers)
    for c in pod.spec.containers:
        if not c.resources.limits and not c.resources.requests:
            issues.append(
                Issue(
                    severity="warning",
                    message="No resource limits/requests set",
                    container=c.name,
                )
            )

    owner_ref = pod.metadata.owner_references[0] if pod.metadata.owner_references else None
    total_restarts = sum(cs.restart_count for cs in pod.status.container_statuses)

    return PodReport(
        pod_name=pod.metadata.name,
        namespace=pod.metadata.namespace,
        phase=pod.status.phase,
        issues=issues,
        controller_kind=owner_ref.kind if owner_ref else "",
        controller_name=resolve_controller_name(owner_ref) if owner_ref else "",
        restart_count=total_restarts,
    )


def aggregate_issues(reports: list[PodReport]) -> list[AggregatedIssue]:
    """Group identical issues by controller + error signature to reduce noise."""
    # Key: (namespace, controller_kind, controller_name, severity, message)
    groups: dict[tuple[str, ...], list[PodReport]] = defaultdict(list)

    for report in reports:
        if not report.issues:
            continue
        # Use the most severe issue as the group key
        critical = [i for i in report.issues if i.severity == "critical"]
        warnings = [i for i in report.issues if i.severity == "warning"]
        representative = (critical or warnings or report.issues)[0]

        key = (
            report.namespace,
            report.controller_kind,
            report.controller_name,
            representative.severity,
            representative.message,
        )
        groups[key].append(report)

    aggregated: list[AggregatedIssue] = []
    for (namespace, c_kind, c_name, severity, message), group_reports in groups.items():
        aggregated.append(
            AggregatedIssue(
                severity=severity,  # type: ignore[arg-type]
                controller_kind=c_kind,
                controller_name=c_name,
                namespace=namespace,
                count=len(group_reports),
                message=message,
                pod_names=[r.pod_name for r in group_reports],
            )
        )

    # Sort: critical first, then by count desc
    aggregated.sort(key=lambda x: (0 if x.severity == "critical" else 1, -x.count))
    return aggregated


def analyze_all(pods: list[Pod]) -> HealthReport:
    """Analyze all pods, return aggregated health report."""
    reports = [analyze_pod(p) for p in pods]

    critical_count = sum(1 for r in reports if any(i.severity == "critical" for i in r.issues))
    warning_count = sum(
        1
        for r in reports
        if any(i.severity == "warning" for i in r.issues)
        and not any(i.severity == "critical" for i in r.issues)
    )
    healthy_count = len(reports) - critical_count - warning_count

    return HealthReport(
        total=len(pods),
        healthy=healthy_count,
        warning=warning_count,
        critical=critical_count,
        pod_reports=reports,
        aggregated_issues=aggregate_issues(reports),
    )
