import asyncio

from a11y_core.models import Base
from a11y_core.settings import get_settings
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

target_metadata = Base.metadata


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run() -> None:
    # Migrations run as the table owner, never as the app role.
    engine = create_async_engine(get_settings().owner_database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_do_run)
    await engine.dispose()


asyncio.run(_run())
