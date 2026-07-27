from collections.abc import Sequence

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.config import get_settings

RUNTIME_ROLE = "faq_runtime"
SCHEMA = "public"
DATABASE = "faq"
EVENT_TABLE = "event"

RUNTIME_GRANTS: Sequence[str] = (
    f"GRANT CONNECT ON DATABASE {DATABASE} TO {RUNTIME_ROLE}",
    f"GRANT USAGE ON SCHEMA {SCHEMA} TO {RUNTIME_ROLE}",
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO {RUNTIME_ROLE}",
    f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {RUNTIME_ROLE}",
    f"REVOKE UPDATE, DELETE ON TABLE {SCHEMA}.{EVENT_TABLE} FROM {RUNTIME_ROLE}",
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
    f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {RUNTIME_ROLE}",
    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {SCHEMA} "
    f"GRANT USAGE, SELECT ON SEQUENCES TO {RUNTIME_ROLE}",
)


def grant_runtime_privileges(connection: Connection) -> None:
    for statement in RUNTIME_GRANTS:
        connection.execute(text(statement))


def alembic_url(database_url: str) -> str:
    return database_url.replace("%", "%%")


def main() -> None:
    settings = get_settings()
    settings.validate_migration_startup()
    alembic_config = Config("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", alembic_url(settings.database_url))
    command.upgrade(alembic_config, "head")
    engine = create_engine(settings.database_url)
    try:
        with engine.begin() as connection:
            grant_runtime_privileges(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
