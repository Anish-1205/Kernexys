"""Public API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

ResourceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$",
    ),
]
VersionName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=63,
        pattern=r"^[A-Za-z0-9](?:[-._A-Za-z0-9]*[A-Za-z0-9])?$",
    ),
]


class ModelUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=2_000)


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ModelList(BaseModel):
    items: list[ModelRead]
    limit: int
    offset: int


class VersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_image: str = Field(min_length=1, max_length=512)
    artifact_digest: str | None = Field(default=None, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_image")
    @classmethod
    def validate_runtime_image(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError("runtime_image must be a non-empty OCI image reference")
        return value

    @field_validator("artifact_digest")
    @classmethod
    def validate_artifact_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError("artifact_digest must be a sha256 digest")
        return value


class VersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_name: str
    version: str
    runtime_image: str
    artifact_digest: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime


class VersionList(BaseModel):
    items: list[VersionRead]
    limit: int
    offset: int


_RESOURCE_NAME_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?/)?[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$"
)
_RESOURCE_QUANTITY_PATTERN = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+|[numkKMGTPE]|[KMGTPE]i)?$"
)


class DeploymentResources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: dict[str, str] = Field(default_factory=dict)
    limits: dict[str, str] = Field(default_factory=dict)

    @field_validator("requests", "limits")
    @classmethod
    def validate_resources(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for name, quantity in values.items():
            quantity = quantity.strip()
            if len(name) > 253 or not _RESOURCE_NAME_PATTERN.fullmatch(name):
                raise ValueError(f"invalid Kubernetes resource name: {name}")
            if len(quantity) > 64 or not _RESOURCE_QUANTITY_PATTERN.fullmatch(quantity):
                raise ValueError(f"invalid Kubernetes resource quantity for {name}")
            normalized[name] = quantity
        return normalized


class DeploymentUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: ResourceName
    version: VersionName
    replicas: int = Field(default=1, ge=1, le=100)
    port: int = Field(default=8080, ge=1, le=65535)
    resources: DeploymentResources = Field(default_factory=DeploymentResources)


class DeploymentSpecRead(BaseModel):
    model: str
    version: str
    runtime_image: str
    replicas: int
    port: int
    resources: DeploymentResources


class DeploymentCondition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    status: str
    observed_generation: int = Field(default=0, alias="observedGeneration")
    reason: str = ""
    message: str = ""
    last_transition_time: datetime | None = Field(default=None, alias="lastTransitionTime")


class DeploymentStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    observed_generation: int = Field(default=0, alias="observedGeneration")
    desired_replicas: int = Field(default=0, alias="desiredReplicas")
    ready_replicas: int = Field(default=0, alias="readyReplicas")
    active_model: str = Field(default="", alias="activeModel")
    active_version: str = Field(default="", alias="activeVersion")
    endpoint: str = ""
    conditions: list[DeploymentCondition] = Field(default_factory=list)


class DeploymentRead(BaseModel):
    name: str
    namespace: str
    generation: int
    resource_version: str
    created_at: datetime | None
    spec: DeploymentSpecRead
    status: DeploymentStatus


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: VersionName


class AsyncInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4096)


class AsyncInferenceJob(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class DeploymentDeleteResponse(BaseModel):
    deleted: bool
    name: str
    namespace: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
