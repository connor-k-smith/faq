import json
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_actor, get_db_session
from app.domain.enums import AssignmentOrigin, DecisionState, ResponseDisposition
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision, DecisionResponse
from app.models.outcomes import Response as Answer
from app.models.work import Ask, AskRecipient, Assignment, Question, QuestionOption

router = APIRouter(tags=["decisions"])
CurrentActor = Annotated[Actor, Depends(get_current_actor)]
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.get("/d/{decision_id}.md", response_class=Response)
def export_decision(decision_id: UUID, actor: CurrentActor, session: DatabaseSession) -> Response:
    row = session.execute(
        select(Decision, Question, Ask, Initiative, Project, Actor)
        .join(Question, Question.id == Decision.question_id)
        .join(Ask, Ask.id == Decision.ask_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(Project, Project.id == Decision.project_id)
        .join(Actor, Actor.id == Decision.decided_by)
        .join(
            Membership,
            (Membership.project_id == Decision.project_id)
            & (Membership.actor_id == actor.id)
            & Membership.revoked_at.is_(None),
        )
        .where(
            Decision.id == decision_id,
            Decision.state.in_([DecisionState.COMMITTED, DecisionState.SUPERSEDED]),
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    decision, question, ask, initiative, project, decider = row
    options = {
        option.value: option.label
        for option in session.scalars(
            select(QuestionOption).where(QuestionOption.question_id == question.id)
        )
    }
    evidence = session.execute(
        select(DecisionResponse, Answer, Assignment, AskRecipient)
        .join(Answer, Answer.id == DecisionResponse.response_id)
        .join(Assignment, Assignment.id == DecisionResponse.assignment_id)
        .outerjoin(AskRecipient, AskRecipient.id == Assignment.ask_recipient_id)
        .where(DecisionResponse.decision_id == decision.id)
        .order_by(AskRecipient.display_name, Answer.created_at, Answer.id)
    ).all()
    advisory = session.execute(
        select(Answer, Assignment, Actor)
        .join(Assignment, Assignment.id == Answer.assignment_id)
        .join(Actor, Actor.id == Assignment.actor_id)
        .where(
            Assignment.question_id == question.id,
            Assignment.origin == AssignmentOrigin.UNSOLICITED,
            Answer.version
            == select(func.max(Answer.version))
            .where(Answer.assignment_id == Assignment.id)
            .correlate(Assignment)
            .scalar_subquery(),
        )
        .order_by(Actor.display_name, Answer.created_at, Answer.id)
    ).all()
    statement_source = (
        decision.statement_source.value if decision.statement_source else "unknown"
    ).replace("_", " ").title()
    successor_id = session.scalar(
        select(Decision.id).where(Decision.supersedes_decision_id == decision.id)
    )
    lines = [
        f"# Decision: {_plain(ask.title)}",
        "",
        f"> Status: {decision.state.value.title()}",
        "",
        "## Decision",
        "",
        _quote(decision.statement or ""),
        "",
        f"- **Outcome:** {_value(decision.value, options)}",
        f"- **Basis:** {decision.basis.value.replace('_', ' ').title()}",
        f"- **Statement source:** {statement_source}",
        f"- **Committed:** {(decision.committed_at or decision.created_at).isoformat()}",
        f"- **Decided by:** {_plain(decider.display_name)}",
        f"- **Decision ID:** `{decision.id}`",
        f"- **Supersedes Decision ID:** `{decision.supersedes_decision_id}`"
        if decision.supersedes_decision_id
        else "- **Supersedes Decision ID:** None",
        f"- **Successor Decision ID:** `{successor_id}`"
        if successor_id
        else "- **Successor Decision ID:** None",
        "",
        "## Context",
        "",
        f"- **Project:** {_plain(project.name)}",
        f"- **Initiative:** {_plain(initiative.name)}",
        f"- **Ask:** {_plain(ask.title)}",
        f"- **Ask ID:** `{ask.id}`",
        f"- **Question:** {_plain(question.prompt)}",
        f"- **Question ID:** `{question.id}`",
        f"- **Question version:** {question.version}",
        f"- **Primitive:** {question.primitive.value.replace('_', ' ').title()}",
        "",
        "## Responses",
        "",
    ]
    if not evidence:
        lines.append("No Responses were attached as evidence.")
    for link, response, assignment, recipient in evidence:
        name = recipient.display_name if recipient else str(assignment.actor_id)
        lines.extend(
            [
                f"### {_plain(name)} - {link.role.value.title()} evidence",
                "",
                f"- **Disposition:** {response.disposition.value.replace('_', ' ').title()}",
                f"- **Answer:** {_value(response.value, options)}",
                f"- **Response version:** {response.version}",
                f"- **Submitted:** {response.created_at.isoformat()}",
            ]
        )
        if response.comment:
            lines.extend(["", _quote(response.comment)])
        revisions = list(
            session.scalars(
                select(Answer)
                .where(
                    Answer.assignment_id == assignment.id,
                    Answer.version < response.version,
                )
                .order_by(Answer.version)
            )
        )
        if revisions:
            lines.extend(["", "#### Earlier revisions", ""])
            lines.extend(
                f"- **Version {item.version}:** {_value(item.value, options)}" for item in revisions
            )
        lines.append("")
    lines.extend(["## Advisory Responses", ""])
    if not advisory:
        lines.append("No advisory Responses were submitted.")
    for response, _assignment, respondent in advisory:
        labels = ["Advisory"]
        if response.provenance.get("late"):
            labels.append("Late")
        lines.extend(
            [
                f"### {_plain(respondent.display_name)} - {' / '.join(labels)}",
                "",
                f"- **Disposition:** {response.disposition.value.replace('_', ' ').title()}",
                f"- **Answer:** {_value(response.value, options)}",
                f"- **Response version:** {response.version}",
                f"- **Submitted:** {response.created_at.isoformat()}",
            ]
        )
        if (
            response.disposition == ResponseDisposition.ANSWERED
            and decision.value is not None
            and response.value != decision.value
        ):
            lines.append("- **Advisory disagreement:** Yes")
        if response.comment:
            lines.extend(["", _quote(response.comment)])
        lines.append("")
    if question.outcome_effect:
        lines.extend(
            [
                "## Outcome assessment",
                "",
                f"- **Effect:** {question.outcome_effect.value.title()}",
                f"- **Note:** {_plain(question.outcome_effect_note or 'None recorded')}",
                "",
            ]
        )
    lines.append(f"Generated from Decision `{decision.id}`.")
    filename = f"{_slug(ask.title)}-decision-{str(decision.id)[:8]}.md"
    return Response(
        "\n".join(lines).rstrip() + "\n",
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _plain(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).replace("<", "&lt;").replace(">", "&gt;")


def _quote(value: str) -> str:
    return "\n".join(f"> {line}" for line in value.replace("<", "&lt;").splitlines())


def _value(value: object, options: dict[str, str]) -> str:
    if isinstance(value, str):
        return _plain(options.get(value, value))
    if isinstance(value, list):
        return ", ".join(_plain(options.get(str(item), str(item))) for item in value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "decision"
