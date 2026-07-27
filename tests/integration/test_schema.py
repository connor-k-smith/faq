from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.models.session import get_engine

pytestmark = pytest.mark.integration


def test_initial_schema_and_templates_are_installed() -> None:
    engine = get_engine()

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        template_count = connection.scalar(text("SELECT count(*) FROM question_template"))

    assert {"project", "initiative", "ask", "question", "response", "decision", "event"} <= tables
    assert template_count == 9


def test_ask_cannot_reference_an_initiative_from_another_project() -> None:
    engine = get_engine()
    actor_id, project_one, project_two, foreign_initiative = (uuid4() for _ in range(4))

    with engine.connect() as connection, connection.begin():
        connection.execute(
            text("INSERT INTO actor (id, display_name) VALUES (:id, 'Casey')"),
            {"id": actor_id},
        )
        for project_id in (project_one, project_two):
            connection.execute(
                text("INSERT INTO project (id, name, created_by) VALUES (:id, :name, :actor_id)"),
                {"id": project_id, "name": f"Project {project_id}", "actor_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO membership (project_id, actor_id) "
                    "VALUES (:project_id, :actor_id)"
                ),
                {"project_id": project_id, "actor_id": actor_id},
            )
        connection.execute(
            text(
                "INSERT INTO initiative (id, project_id, name, kind, created_by) "
                "VALUES (:id, :project_id, 'Foreign', 'feature', :actor_id)"
            ),
            {"id": foreign_initiative, "project_id": project_two, "actor_id": actor_id},
        )

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO ask "
                    "(project_id, initiative_id, title, created_by, owner_id) "
                    "VALUES (:project_id, :initiative_id, 'Invalid Ask', :actor_id, :actor_id)"
                ),
                {
                    "project_id": project_one,
                    "initiative_id": foreign_initiative,
                    "actor_id": actor_id,
                },
            )
