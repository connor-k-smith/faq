from unittest.mock import MagicMock

from sqlalchemy.engine import Connection

from app.migrate import RUNTIME_GRANTS, alembic_url, grant_runtime_privileges


def test_runtime_grants_are_fixed_and_keep_events_immutable() -> None:
    statements = "\n".join(RUNTIME_GRANTS)

    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public" in statements
    assert "REVOKE UPDATE, DELETE ON TABLE public.event FROM faq_runtime" in statements
    assert statements.count("ALTER DEFAULT PRIVILEGES IN SCHEMA public") == 2
    assert "CREATE" not in statements
    assert "ALTER TABLE" not in statements


def test_runtime_grants_execute_in_order() -> None:
    connection = MagicMock(spec=Connection)

    grant_runtime_privileges(connection)

    assert [str(call.args[0]) for call in connection.execute.call_args_list] == list(RUNTIME_GRANTS)


def test_alembic_url_escapes_config_parser_interpolation() -> None:
    url = "postgresql+psycopg://user:password@/faq?host=%2Fcloudsql%2Fproject:region:instance"

    assert alembic_url(url) == (
        "postgresql+psycopg://user:password@/faq?host=%%2Fcloudsql%%2Fproject:region:instance"
    )
