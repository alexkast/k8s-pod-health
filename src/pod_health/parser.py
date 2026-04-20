"""Pydantic models for K8s pod JSON parsing and sanitization before AI."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResourceRequirements(BaseModel):
    model_config = ConfigDict(extra="ignore")
    limits: dict[str, str] = Field(default_factory=dict)
    requests: dict[str, str] = Field(default_factory=dict)


class ContainerStateTerminated(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = ""
    exit_code: int = Field(0, alias="exitCode")
    message: str = ""


class ContainerStateWaiting(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = ""
    message: str = ""


class ContainerState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    terminated: ContainerStateTerminated | None = None
    waiting: ContainerStateWaiting | None = None


class ContainerStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    image: str = ""
    ready: bool = False
    restart_count: int = Field(0, alias="restartCount")
    state: ContainerState = Field(default_factory=ContainerState)
    last_state: ContainerState = Field(default_factory=ContainerState, alias="lastState")


class ContainerSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    image: str = ""
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    # explicitly NOT modeling: env, envFrom, volumeMounts, command, args, securityContext


class PodSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    containers: list[ContainerSpec] = Field(default_factory=list)
    init_containers: list[ContainerSpec] = Field(default_factory=list, alias="initContainers")
    # explicitly NOT modeling: volumes, serviceAccountName, imagePullSecrets, nodeSelector


class PodCondition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str
    status: str
    reason: str = ""
    message: str = ""


class OwnerReference(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: str
    name: str
    api_version: str = Field("", alias="apiVersion")


class PodMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    namespace: str = "default"
    creation_timestamp: str = Field("", alias="creationTimestamp")
    owner_references: list[OwnerReference] = Field(default_factory=list, alias="ownerReferences")
    # explicitly NOT modeling: annotations, labels (may contain secrets/tokens)


class PodStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    phase: str = ""
    conditions: list[PodCondition] = Field(default_factory=list)
    container_statuses: list[ContainerStatus] = Field(
        default_factory=list, alias="containerStatuses"
    )
    init_container_statuses: list[ContainerStatus] = Field(
        default_factory=list, alias="initContainerStatuses"
    )
    message: str = ""
    reason: str = ""


class Pod(BaseModel):
    model_config = ConfigDict(extra="ignore")
    metadata: PodMetadata
    spec: PodSpec = Field(default_factory=PodSpec)
    status: PodStatus = Field(default_factory=PodStatus)


class PodList(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[Pod] = Field(default_factory=list)


def parse_pods(json_str: str) -> list[Pod]:
    """Parse kubectl JSON output — handles both PodList and single Pod."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    kind = data.get("kind", "")
    if kind == "PodList" or (not kind and "items" in data):
        return PodList.model_validate(data).items
    elif kind == "Pod" or (not kind and "metadata" in data):
        return [Pod.model_validate(data)]
    else:
        raise ValueError(f"Unrecognized kubectl output kind: '{kind}'. Expected 'PodList' or 'Pod'.")


def sanitize_for_ai(pods: list[Pod]) -> list[dict[str, Any]]:
    """Build a minimal, secret-free representation safe to send to the LLM.

    Strips all sensitive fields: env, envFrom, volumes, volumeMounts,
    annotations, labels, and anything not needed for diagnosis.
    """
    result = []
    for pod in pods:
        owner = None
        if pod.metadata.owner_references:
            ref = pod.metadata.owner_references[0]
            owner = {"kind": ref.kind, "name": ref.name}

        containers = [
            {
                "name": cs.name,
                "image": cs.image,
                "ready": cs.ready,
                "restartCount": cs.restart_count,
                "state": _serialize_state(cs.state),
                "lastState": _serialize_state(cs.last_state),
            }
            for cs in pod.status.container_statuses
        ]

        init_containers = [
            {
                "name": cs.name,
                "image": cs.image,
                "ready": cs.ready,
                "restartCount": cs.restart_count,
                "state": _serialize_state(cs.state),
                "lastState": _serialize_state(cs.last_state),
            }
            for cs in pod.status.init_container_statuses
        ]

        resource_limits = {
            c.name: {"limits": c.resources.limits, "requests": c.resources.requests}
            for c in pod.spec.containers
            if c.resources.limits or c.resources.requests
        }

        conditions = [
            {"type": cond.type, "status": cond.status, "reason": cond.reason}
            for cond in pod.status.conditions
        ]

        result.append(
            {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "owner": owner,
                "containers": containers,
                "initContainers": init_containers,
                "resourceLimits": resource_limits,
                "conditions": conditions,
            }
        )
    return result


def _serialize_state(state: ContainerState) -> dict[str, Any]:
    if state.terminated:
        return {
            "terminated": {
                "reason": state.terminated.reason,
                "exitCode": state.terminated.exit_code,
            }
        }
    if state.waiting:
        return {"waiting": {"reason": state.waiting.reason}}
    return {"running": {}}
