"""Public API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
