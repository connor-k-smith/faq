from sqlalchemy import Enum

from app.models import Actor, Base


def test_all_phase_one_tables_have_explicit_mappings() -> None:
    assert set(Base.metadata.tables) == {
        "actor",
        "ask",
        "ask_question",
        "ask_recipient",
        "assignment",
        "authoring_session",
        "contact_method",
        "decision",
        "decision_response",
        "event",
        "initiative",
        "login_invitation",
        "membership",
        "organization",
        "project",
        "question",
        "question_option",
        "question_template",
        "response",
    }


def test_python_enum_members_persist_using_database_values() -> None:
    kind_type = Actor.__table__.c.kind.type

    assert isinstance(kind_type, Enum)
    assert kind_type.enums == ["human", "agent"]
