"""Registry persistence operations and immutability rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import ModelVersion, RegisteredModel

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class WriteResult(Generic[T]):
    value: T
    created: bool


class RegistryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def put_model(self, name: str, description: str | None) -> WriteResult[RegisteredModel]:
        model = await self.session.get(RegisteredModel, name)
        if model is None:
            model = RegisteredModel(name=name, description=description)
            self.session.add(model)
            try:
                await self.session.commit()
                await self.session.refresh(model)
                return WriteResult(model, created=True)
            except IntegrityError:
                await self.session.rollback()
                model = await self.session.get(RegisteredModel, name)
                if model is None:
                    raise

        if model.description != description:
            model.description = description
            await self.session.commit()
            await self.session.refresh(model)
        return WriteResult(model, created=False)

    async def get_model(self, name: str) -> RegisteredModel | None:
        return await self.session.get(RegisteredModel, name)

    async def list_models(self, limit: int, offset: int) -> list[RegisteredModel]:
        result = await self.session.scalars(
            select(RegisteredModel).order_by(RegisteredModel.name).limit(limit).offset(offset)
        )
        return list(result)

    async def put_version(
        self,
        model_name: str,
        version: str,
        runtime_image: str,
        artifact_digest: str | None,
        metadata: dict[str, Any],
    ) -> WriteResult[ModelVersion]:
        existing = await self._get_version(model_name, version)
        if existing is not None:
            return WriteResult(existing, created=False)

        version_record = ModelVersion(
            model_name=model_name,
            version=version,
            runtime_image=runtime_image,
            artifact_digest=artifact_digest,
            metadata_json=metadata,
        )
        self.session.add(version_record)
        try:
            await self.session.commit()
            await self.session.refresh(version_record)
            return WriteResult(version_record, created=True)
        except IntegrityError:
            await self.session.rollback()
            existing = await self._get_version(model_name, version)
            if existing is None:
                raise
            return WriteResult(existing, created=False)

    async def get_version(self, model_name: str, version: str) -> ModelVersion | None:
        return await self._get_version(model_name, version)

    async def list_versions(self, model_name: str, limit: int, offset: int) -> list[ModelVersion]:
        result = await self.session.scalars(
            select(ModelVersion)
            .where(ModelVersion.model_name == model_name)
            .order_by(ModelVersion.version)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def _get_version(self, model_name: str, version: str) -> ModelVersion | None:
        result = await self.session.scalar(
            select(ModelVersion).where(
                ModelVersion.model_name == model_name,
                ModelVersion.version == version,
            )
        )
        return result


def version_matches(
    value: ModelVersion,
    runtime_image: str,
    artifact_digest: str | None,
    metadata: dict[str, Any],
) -> bool:
    return (
        value.runtime_image == runtime_image
        and value.artifact_digest == artifact_digest
        and value.metadata_json == metadata
    )
