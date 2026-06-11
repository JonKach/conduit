import os
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
assert config.config_file_name is not None
fileConfig(config.config_file_name)

# add your model's MetaData object here
from app.models import SQLModel  # noqa
from app.core.config import settings # noqa

target_metadata = SQLModel.metadata


def get_url():
    return str(settings.SQLALCHEMY_DATABASE_URI)


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """
    Synchronous helper to configure the context and run migrations.
    This is called by the async connection.
    """
    context.configure(
        connection=connection, 
        target_metadata=target_metadata, 
        compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    """In this scenario we need to create an async Engine
    and associate a connection with the context.
    """
    configuration = config.get_section(config.config_ini_section)
    assert configuration is not None
    configuration["sqlalchemy.url"] = get_url()
    
    # Use the async engine creator
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # Run the synchronous migration context within the async connection
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online():
    """Run migrations in 'online' mode using asyncio."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()