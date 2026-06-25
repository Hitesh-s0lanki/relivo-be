"""Apply SQL migrations from the migrations directory."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
sys.path.append(str(ROOT))

from src.database import get_database_url  # noqa: E402


async def apply_migrations() -> None:
    """Apply all SQL migrations in filename order."""
    load_dotenv(ROOT / ".env")
    engine = create_async_engine(get_database_url(), pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                sql = path.read_text(encoding="utf-8").strip()
                if not sql:
                    continue
                for statement in split_sql_statements(sql):
                    await connection.exec_driver_sql(statement)
                print(f"applied {path.relative_to(ROOT)}")
    finally:
        await engine.dispose()


def main() -> None:
    """Run the migration CLI."""
    asyncio.run(apply_migrations())


def split_sql_statements(sql: str) -> list[str]:
    """Split a simple migration SQL file into executable statements."""
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


if __name__ == "__main__":
    main()
