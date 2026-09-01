from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.config import Settings
from app.database import create_database_engine


def test_migrations_upgrade_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("KERNEXYS_DATABASE_URL", database_url)
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    async def table_names() -> set[str]:
        engine = create_database_engine(Settings(database_url=database_url))
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        await engine.dispose()
        return set(result.scalars())

    assert {"alembic_version", "models", "model_versions"} <= asyncio.run(table_names())

    command.downgrade(config, "base")
    assert "models" not in asyncio.run(table_names())
