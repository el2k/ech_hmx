"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.models.base import BaseModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = BaseModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.



def include_object(object, name, type_, reflected, compare_to):
    """Limit autogenerate scope to ai_* tables only."""
    if type_ == "table":
        return name.startswith("ai_")
    # for other object types (indexes, constraints), defer to Alembic defaults
    return True


def include_name(name, type_, parent_names):
    """Filter DB reflection by object name during autogenerate.
    Only include ai_* tables for comparison to avoid touching other services.
    """
    if type_ == "table":
        return name.startswith("ai_")
    return True


# Prune autogenerate ops that try to drop non-ai_* tables
try:
    from alembic.operations import ops as _alembic_ops
except Exception:  # pragma: no cover
    _alembic_ops = None


def process_revision_directives(context, revision, directives):
    if not getattr(context.config, "cmd_opts", None):
        return
    if not getattr(context.config.cmd_opts, "autogenerate", False):
        return
    if not directives:
        return
    script = directives[0]
    if not hasattr(script, "upgrade_ops"):
        return
    if _alembic_ops is None:
        return

    def _keep(op):
        # Keep everything related to ai_* tables; drop others from autogenerate
        try:
            if isinstance(op, _alembic_ops.DropTableOp):
                return op.table_name.startswith("ai_")
            if isinstance(op, _alembic_ops.DropIndexOp):
                tname = getattr(op, "table_name", None)
                return not tname or tname.startswith("ai_")
        except Exception:
            return True
        return True

    try:
        script.upgrade_ops.ops = [op for op in script.upgrade_ops.ops if _keep(op)]
    except Exception:
        pass



def get_url() -> str:
    """Get database URL from settings."""
    return settings.get_database_url(sync=False)  # Use async URL for async engine


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # For offline mode, use sync URL since no actual connection is made
    url = settings.get_database_url(sync=True)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="ai_alembic_version",
        include_object=include_object,
        include_name=include_name,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with database connection."""
    context.configure(connection=connection, target_metadata=target_metadata, version_table="ai_alembic_version", include_object=include_object, include_name=include_name, process_revision_directives=process_revision_directives)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
