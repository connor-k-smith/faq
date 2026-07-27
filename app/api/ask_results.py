from typing import cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.ask_contracts import EvidenceWrite
from app.api.ask_response_models import (
    AskResults,
    DecisionDto,
    OptionDto,
    ResolutionMetadataDto,
    ResponseRevisionDto,
    ResultAssignmentDto,
    ResultQuestionDto,
    StakeholderQuestionDto,
    StakeholderResultDto,
)
from app.api.ask_support import _is_overdue
from app.domain.enums import (
    AskStatus,
    AssignmentOrigin,
    DecisionBasis,
    DecisionResponseRole,
    DecisionState,
    QuestionClosePolicy,
    QuestionOpenTo,
    QuestionState,
    ResponseDisposition,
    ResponseVisibility,
)
from app.domain.events import EventName
from app.domain.ports import SystemClock
from app.models.identity import Actor, Initiative, Membership, Project
from app.models.outcomes import Decision, DecisionResponse, Event
from app.models.outcomes import Response as Answer
from app.models.work import Ask, AskQuestion, AskRecipient, Assignment, Question, QuestionOption


def _resolution_metadata(decision: Decision) -> ResolutionMetadataDto | None:
    computed = decision.provenance.get("computed")
    if not isinstance(computed, dict):
        return None
    vote_counts = computed.get("vote_counts", {})
    if not isinstance(vote_counts, dict):
        vote_counts = {}
    return ResolutionMetadataDto(
        computed_winner=bool(computed.get("has_winner")),
        computed_value=cast(JsonValue, computed.get("value")),
        computed_basis=DecisionBasis(str(computed.get("basis"))),
        eligible_count=int(computed.get("eligible_count", 0)),
        substantive_count=int(computed.get("substantive_count", 0)),
        quorum_met=bool(computed.get("quorum_met")),
        conflict=bool(computed.get("conflict")),
        vote_counts={str(value): int(count) for value, count in vote_counts.items()},
        proposal_state=decision.state,
    )


def _results(session: Session, ask_id: UUID, actor_id: UUID) -> AskResults:
    row = session.execute(
        select(Ask, Project, Initiative)
        .join(Project, Project.id == Ask.project_id)
        .join(Initiative, Initiative.id == Ask.initiative_id)
        .join(
            Membership,
            (Membership.project_id == Ask.project_id)
            & (Membership.actor_id == actor_id)
            & Membership.revoked_at.is_(None),
        )
        .where(Ask.id == ask_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Ask not found")
    ask, project, initiative = row
    now = SystemClock().now()
    end = ask.closed_at or now
    elapsed = max(0, int((end - (ask.sent_at or ask.created_at)).total_seconds()))
    question_rows = session.execute(
        select(Question, AskQuestion.ordinal)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(AskQuestion.ask_id == ask.id, AskQuestion.superseded_at.is_(None))
        .order_by(AskQuestion.ordinal, Question.id)
    ).all()
    result_questions: list[ResultQuestionDto] = []
    stakeholder_map: dict[UUID, StakeholderResultDto] = {}
    for question, ordinal in question_rows:
        own_response_exists = bool(
            session.scalar(
                select(func.count())
                .select_from(Answer)
                .join(Assignment, Assignment.id == Answer.assignment_id)
                .where(
                    Assignment.question_id == question.id,
                    Assignment.actor_id == actor_id,
                )
            )
        )
        responses_visible = (
            ask.owner_id == actor_id
            or question.state != QuestionState.OPEN
            or question.response_visibility == ResponseVisibility.IMMEDIATE
            or (
                question.response_visibility == ResponseVisibility.AFTER_OWN_RESPONSE
                and own_response_exists
            )
        )
        options = list(
            session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id == question.id)
                .order_by(QuestionOption.ordinal, QuestionOption.id)
            )
        )
        assignment_rows = session.execute(
            select(Assignment, AskRecipient, Actor)
            .outerjoin(AskRecipient, AskRecipient.id == Assignment.ask_recipient_id)
            .join(Actor, Actor.id == Assignment.actor_id)
            .where(Assignment.ask_id == ask.id, Assignment.question_id == question.id)
            .order_by(Assignment.created_at, Assignment.id)
        ).all()
        assignments: list[ResultAssignmentDto] = []
        advisory_latest: list[Answer] = []
        actor_assignment_origin: AssignmentOrigin | None = None
        for assignment, recipient, respondent in assignment_rows:
            if assignment.actor_id == actor_id:
                actor_assignment_origin = assignment.origin
            revisions = list(
                session.scalars(
                    select(Answer)
                    .where(Answer.assignment_id == assignment.id)
                    .order_by(Answer.version)
                )
            )
            assignment_visible = responses_visible or assignment.actor_id == actor_id
            revision_dtos = [
                ResponseRevisionDto(
                    id=response.id,
                    version=response.version,
                    disposition=response.disposition.value,
                    value=response.value,
                    comment=response.comment,
                    created_at=response.created_at,
                )
                for response in revisions
                if assignment_visible
            ]
            first_response_at = revisions[0].created_at if revisions else end
            response_elapsed = max(
                0, int((first_response_at - assignment.created_at).total_seconds())
            )
            distinct_ips = int(
                session.scalar(
                    select(func.count(func.distinct(Event.ip))).where(
                        Event.assignment_id == assignment.id,
                        Event.type == EventName.RESPONSE_SUBMITTED.value,
                        Event.ip.is_not(None),
                    )
                )
                or 0
            )
            assignments.append(
                ResultAssignmentDto(
                    id=assignment.id,
                    recipient_id=recipient.id if recipient else None,
                    actor_id=assignment.actor_id,
                    delegated_to_actor_id=assignment.delegated_to_actor_id,
                    child_ask_id=assignment.child_ask_id,
                    display_name=recipient.display_name if recipient else respondent.display_name,
                    origin=assignment.origin,
                    advisory=assignment.origin == AssignmentOrigin.UNSOLICITED,
                    late=bool(
                        revisions
                        and assignment.origin == AssignmentOrigin.UNSOLICITED
                        and revisions[-1].provenance.get("late")
                    ),
                    state=assignment.state,
                    elapsed_seconds=response_elapsed,
                    distinct_ip_count=distinct_ips,
                    latest_response=revision_dtos[-1] if revision_dtos else None,
                    revisions=revision_dtos,
                    response_visible=assignment_visible,
                )
            )
            if (
                assignment.origin == AssignmentOrigin.UNSOLICITED
                and revisions
                and revisions[-1].disposition == ResponseDisposition.ANSWERED
            ):
                advisory_latest.append(revisions[-1])
            if recipient is None:
                continue
            stakeholder = stakeholder_map.setdefault(
                recipient.id,
                StakeholderResultDto(
                    recipient_id=recipient.id,
                    display_name=recipient.display_name,
                    distinct_ip_count=distinct_ips,
                    questions=[],
                ),
            )
            stakeholder.questions.append(
                StakeholderQuestionDto(question_id=question.id, assignment_id=assignment.id)
            )
        decision = session.scalar(
            select(Decision).where(
                Decision.question_id == question.id,
                Decision.state.in_(
                    (DecisionState.PROPOSED, DecisionState.COMMITTED, DecisionState.SUPERSEDED)
                ),
            )
        )
        decision_dto = None
        if decision is not None:
            evidence_rows = list(
                session.execute(
                    select(
                        DecisionResponse.response_id,
                        DecisionResponse.role,
                        Answer.disposition,
                    )
                    .join(Answer, Answer.id == DecisionResponse.response_id)
                    .where(DecisionResponse.decision_id == decision.id)
                )
            )
            if decision.state in (DecisionState.COMMITTED, DecisionState.SUPERSEDED) and (
                decision.statement is None
                or decision.statement_source is None
                or decision.committed_at is None
            ):
                raise RuntimeError("committed Decision is missing required fields")
            decision_dto = DecisionDto(
                id=decision.id,
                state=decision.state,
                basis=decision.basis,
                value=decision.value,
                statement=decision.statement,
                statement_source=decision.statement_source,
                committed_at=decision.committed_at,
                shared_with_recipients_at=decision.shared_with_recipients_at,
                substantive_evidence_count=sum(
                    role == DecisionResponseRole.DETERMINING and disposition.value == "answered"
                    for _, role, disposition in evidence_rows
                ),
                evidence=[
                    EvidenceWrite(response_id=response_id, role=role)
                    for response_id, role, _ in evidence_rows
                ],
                resolution=_resolution_metadata(decision),
                advisory_disagreement=bool(
                    decision.state in (DecisionState.COMMITTED, DecisionState.SUPERSEDED)
                    and decision.value is not None
                    and any(response.value != decision.value for response in advisory_latest)
                ),
                supersedes_decision_id=decision.supersedes_decision_id,
                successor_decision_id=session.scalar(
                    select(Decision.id).where(Decision.supersedes_decision_id == decision.id)
                ),
                historical=decision.state == DecisionState.SUPERSEDED,
            )
        result_questions.append(
            ResultQuestionDto(
                id=question.id,
                ordinal=ordinal,
                prompt=question.prompt,
                primitive=question.primitive,
                state=question.state,
                open_to=question.open_to,
                close_policy=question.close_policy,
                can_contribute_advisory=(
                    question.open_to == QuestionOpenTo.PROJECT_MEMBERS
                    and project.archived_at is None
                    and initiative.archived_at is None
                    and ask.status != AskStatus.CANCELLED
                    and actor_assignment_origin in (None, AssignmentOrigin.UNSOLICITED)
                ),
                version=question.version,
                supersedes_question_id=question.supersedes_question_id,
                copied_from_question_id=question.copied_from_question_id,
                overdue=(
                    _is_overdue(ask)
                    and question.close_policy
                    in (QuestionClosePolicy.DEADLINE, QuestionClosePolicy.EITHER)
                ),
                options=[
                    OptionDto(
                        id=option.id,
                        ordinal=option.ordinal,
                        value=option.value,
                        label=option.label,
                        consequence=option.consequence,
                        triggers=option.triggers,
                    )
                    for option in options
                ],
                outcome_effect=question.outcome_effect,
                outcome_effect_note=question.outcome_effect_note,
                decision=decision_dto,
                assignments=assignments,
            )
        )
    return AskResults(
        id=ask.id,
        title=ask.title,
        parent_ask_id=ask.parent_ask_id,
        status=ask.status,
        owner_id=ask.owner_id,
        sent_at=ask.sent_at,
        closed_at=ask.closed_at,
        deadline=ask.deadline,
        overdue=_is_overdue(ask),
        elapsed_seconds=elapsed,
        can_decide=(
            ask.owner_id == actor_id
            and ask.status == AskStatus.SENT
            and project.archived_at is None
            and initiative.archived_at is None
        ),
        questions=result_questions,
        stakeholders=list(stakeholder_map.values()),
    )
