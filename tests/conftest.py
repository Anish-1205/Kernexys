from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import create_database_engine
from app.db_models import Base
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    database_path = (tmp_path / "test.db").as_posix()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{database_path}")
    engine = create_database_engine(settings)

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    with TestClient(create_app(settings, engine=engine)) as test_client:
        yield test_client
    asyncio.run(engine.dispose())
