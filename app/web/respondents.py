# ruff: noqa: E501
import hashlib
import hmac
import html
from dataclasses import dataclass
from datetime import datetime, timedelta
from ipaddress import ip_address
from typing import Annotated, NoReturn
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.auth.respondent_sessions import (
    InvalidInvitationSession,
    InvitationClaims,
    InvitationSessionCodec,
)
from app.config import Settings, get_settings
from app.domain.enums import (
    AskStatus,
    AssignmentState,
    DecisionState,
    QuestionPrimitive,
    QuestionState,
    ResponseDisposition,
)
from app.domain.ports import SystemClock
from app.domain.responding import ResponseSubmission, ResponseSubmissionError, submit_response
from app.domain.settlement import settle_ask
from app.domain.validation import DomainValidationError, parse_date_value, parse_number_value
from app.models.identity import Actor, Organization, Project
from app.models.outcomes import Decision, Response
from app.models.work import (
    Ask,
    AskQuestion,
    AskRecipient,
    Assignment,
    Question,
    QuestionOption,
)
from app.web.throttling import failed_exchange_limiter

router = APIRouter(tags=["respondents"])
RESPONDENT_COOKIE = "faq_invitation"
DatabaseSession = Annotated[Session, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
logger = structlog.get_logger()


@router.get("/r/{token}", include_in_schema=False, response_model=None)
def exchange_recipient_token(
    token: str,
    request: Request,
    session: DatabaseSession,
    settings: AppSettings,
) -> HTMLResponse | RedirectResponse:
    row = session.execute(
        select(AskRecipient, Ask, Project, Actor)
        .join(Ask, Ask.id == AskRecipient.ask_id)
        .join(Project, Project.id == Ask.project_id)
        .join(Actor, Actor.id == Ask.owner_id)
        .where(AskRecipient.token_hash == _token_hash(token))
    ).one_or_none()
    if row is None:
        _failed_exchange(request)
    recipient, ask, project, owner = row
    respondent = session.get(Actor, recipient.actor_id)
    if respondent is None or respondent.deleted_at is not None:
        _failed_exchange(request)
    if _is_crawler(request.headers.get("user-agent", "")):
        if not _eligible(recipient, ask, project):
            return _minimal_notice("This invitation is unavailable.", status_code=410)
        organization = session.get(Organization, 1)
        return _unfurl(
            organization.name if organization else settings.organization_name,
            owner.display_name,
            ask,
        )
    if not _eligible(recipient, ask, project):
        _failed_exchange(request)
    expires_at = recipient.access_expires_at
    if expires_at is None:
        _failed_exchange(request)
    claims = InvitationClaims(
        recipient_id=recipient.id,
        session_version=recipient.session_version,
        expires_at=int(expires_at.timestamp()),
    )
    encoded = InvitationSessionCodec(settings.session_secret.get_secret_value()).issue(claims)
    response = RedirectResponse(f"/r/i/{recipient.id}", status_code=303)
    response.set_cookie(
        RESPONDENT_COOKIE,
        encoded,
        max_age=max(0, int((expires_at - SystemClock().now()).total_seconds())),
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path="/r",
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/r/i/{recipient_id}", response_class=HTMLResponse, include_in_schema=False)
def respondent_invitation(
    recipient_id: UUID,
    session: DatabaseSession,
    settings: AppSettings,
    encoded: Annotated[str | None, Cookie(alias=RESPONDENT_COOKIE)] = None,
) -> HTMLResponse:
    try:
        context = _load_invitation(session, settings, recipient_id, encoded)
    except InvitationAccessError as error:
        return _minimal_notice(error.message, status_code=error.status_code)
    if settle_ask(session, SystemClock(), context.ask.id):
        session.commit()
    context = _load_invitation(session, settings, recipient_id, encoded)
    return _render_page(session, settings, context, encoded or "")


@router.post(
    "/r/i/{recipient_id}/questions/{assignment_id}",
    response_class=HTMLResponse,
    response_model=None,
    include_in_schema=False,
)
async def save_response(
    recipient_id: UUID,
    assignment_id: UUID,
    request: Request,
    session: DatabaseSession,
    settings: AppSettings,
    encoded: Annotated[str | None, Cookie(alias=RESPONDENT_COOKIE)] = None,
) -> HTMLResponse | RedirectResponse:
    try:
        context = _load_invitation(session, settings, recipient_id, encoded)
    except InvitationAccessError as error:
        return _minimal_notice(error.message, status_code=error.status_code)
    form = await request.form()
    posted = {key: str(value) for key, value in form.items()}
    submitted_values = form.getlist("value")
    assignment_question = session.scalar(
        select(Question)
        .join(Assignment, Assignment.question_id == Question.id)
        .where(Assignment.id == assignment_id)
    )
    if assignment_question and assignment_question.primitive == QuestionPrimitive.SELECT_MANY:
        posted["_values"] = "\x1f".join(str(value) for value in submitted_values)
    elif len(submitted_values) > 1:
        return _render_page(
            session,
            settings,
            context,
            encoded or "",
            error_assignment=assignment_id,
            error="Submit exactly one answer value.",
            posted=posted,
            status_code=422,
        )
    expected_csrf = _respondent_csrf(settings, encoded or "")
    if not hmac.compare_digest(posted.get("csrf_token", ""), expected_csrf):
        return _render_page(
            session,
            settings,
            context,
            encoded or "",
            error_assignment=assignment_id,
            error="This form expired. Reload the page and try again.",
            posted=posted,
            status_code=403,
        )
    try:
        disposition = ResponseDisposition(posted.get("disposition", "answered"))
        submission_id = UUID(posted["submission_id"])
        submitted_value: JsonValue = posted.get("value")
        if disposition == ResponseDisposition.ANSWERED:
            if assignment_question and assignment_question.primitive == QuestionPrimitive.NUMBER:
                submitted_value = parse_number_value(posted.get("value", ""))
            elif assignment_question and assignment_question.primitive == QuestionPrimitive.DATE:
                submitted_value = parse_date_value(posted.get("value", ""))
            elif (
                assignment_question
                and assignment_question.primitive == QuestionPrimitive.SELECT_MANY
            ):
                submitted_value = [str(value) for value in submitted_values]
        submit_response(
            session,
            SystemClock(),
            recipient_id=recipient_id,
            assignment_id=assignment_id,
            submission=ResponseSubmission(
                disposition=disposition,
                value=submitted_value,
                comment=(
                    posted.get("comment")
                ),
                submission_id=submission_id,
                source_ip=_source_ip(request),
                user_agent=request.headers.get("user-agent"),
                delegate_display_name=posted.get("delegate_display_name"),
                delegate_email=posted.get("delegate_email"),
            ),
            grace=timedelta(minutes=settings.all_responded_grace_minutes),
        )
        session.commit()
    except ResponseSubmissionError as error:
        # A rejected submission may still have lazily settled the Question.
        session.commit()
        return _render_page(
            session,
            settings,
            context,
            encoded or "",
            error_assignment=assignment_id,
            error=str(error),
            posted=posted,
            status_code=422,
        )
    except (KeyError, ValueError, DomainValidationError) as error:
        session.rollback()
        return _render_page(
            session,
            settings,
            context,
            encoded or "",
            error_assignment=assignment_id,
            error=str(error),
            posted=posted,
            status_code=422,
        )
    return RedirectResponse(f"/r/i/{recipient_id}#assignment-{assignment_id}", status_code=303)


@dataclass(frozen=True)
class InvitationContext:
    recipient: AskRecipient
    ask: Ask
    project: Project
    respondent: Actor
    owner: Actor


class InvitationAccessError(ValueError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _load_invitation(
    session: Session,
    settings: Settings,
    recipient_id: UUID,
    encoded: str | None,
) -> InvitationContext:
    if encoded is None:
        raise InvitationAccessError("Open your personal invitation link to continue.", 401)
    try:
        claims = InvitationSessionCodec(settings.session_secret.get_secret_value()).verify(encoded)
    except InvalidInvitationSession as error:
        raise InvitationAccessError("This invitation session is unavailable.", 401) from error
    if claims.recipient_id != recipient_id or claims.expires_at <= int(
        SystemClock().now().timestamp()
    ):
        raise InvitationAccessError("This invitation session has expired.", 401)
    row = session.execute(
        select(AskRecipient, Ask, Project, Actor)
        .join(Ask, Ask.id == AskRecipient.ask_id)
        .join(Project, Project.id == Ask.project_id)
        .join(Actor, Actor.id == AskRecipient.actor_id)
        .where(AskRecipient.id == recipient_id)
    ).one_or_none()
    if row is None:
        raise InvitationAccessError("This invitation is unavailable.", 404)
    recipient, ask, project, respondent = row
    owner = session.get(Actor, ask.owner_id)
    if owner is None:
        raise InvitationAccessError("This invitation is unavailable.", 404)
    if (
        claims.session_version != recipient.session_version
        or not _eligible(recipient, ask, project)
        or respondent.deleted_at is not None
    ):
        raise InvitationAccessError("This invitation is no longer active.", 410)
    return InvitationContext(recipient, ask, project, respondent, owner)


def _render_page(
    session: Session,
    settings: Settings,
    context: InvitationContext,
    encoded: str,
    *,
    error_assignment: UUID | None = None,
    error: str | None = None,
    posted: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    organization = session.get(Organization, 1)
    organization_name = organization.name if organization else settings.organization_name
    logo = (
        f"<img src='{_escape(organization.logo_url)}' alt=''>"
        if organization and _safe_image_url(organization.logo_url)
        else ""
    )
    owner_avatar = (
        f"<img class='avatar' src='{_escape(context.owner.avatar_url)}' alt=''>"
        if _safe_image_url(context.owner.avatar_url)
        else ""
    )
    rows = session.execute(
        select(Assignment, Question)
        .join(Question, Question.id == Assignment.question_id)
        .join(AskQuestion, AskQuestion.question_id == Question.id)
        .where(
            Assignment.ask_recipient_id == context.recipient.id,
            Assignment.ask_id == context.ask.id,
            AskQuestion.ask_id == context.ask.id,
            AskQuestion.superseded_at.is_(None),
            Assignment.state.not_in((AssignmentState.BLOCKED, AssignmentState.WITHDRAWN)),
        )
        .order_by(AskQuestion.ordinal)
    ).all()
    decisions = {
        decision.question_id: decision
        for decision in session.scalars(
            select(Decision).where(
                Decision.ask_id == context.ask.id,
                Decision.state.in_((DecisionState.COMMITTED, DecisionState.SUPERSEDED)),
                Decision.shared_with_recipients_at.is_not(None),
            )
        )
    }
    assignment_ids = [assignment.id for assignment, _question in rows]
    completed = (
        session.scalar(
            select(func.count(func.distinct(Response.assignment_id))).where(
                Response.assignment_id.in_(assignment_ids)
            )
        )
        if assignment_ids
        else 0
    ) or 0
    progress = (
        "All assigned questions are complete. You may revise an answer while this request is open."
        if rows and completed == len(rows)
        else f"{completed} of {len(rows)} questions answered."
    )
    cards = "".join(
        _question_card(
            session,
            context,
            assignment,
            question,
            decisions.get(question.id),
            _respondent_csrf(settings, encoded),
            error if error_assignment == assignment.id else None,
            posted if error_assignment == assignment.id else None,
        )
        for assignment, question in rows
    )
    overdue = bool(
        context.ask.status == AskStatus.SENT
        and context.ask.deadline
        and context.ask.deadline < SystemClock().now()
    )
    deadline = _local_deadline(context.ask, context.respondent.timezone)
    deadline_label = "Overdue since" if overdue else "Respond by"
    deadline_class = "deadline overdue" if overdue else "deadline"
    intro = f"<p class='intro'>{_escape(context.ask.intro)}</p>" if context.ask.intro else ""
    default_note = (
        f"<p class='default-note'>{_escape(context.ask.default_note)}</p>"
        if context.ask.default_note
        else ""
    )
    content = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(organization_name)} · {_escape(context.ask.title)}</title><link rel="stylesheet" href="/static/respondent.css"></head>
<body><header><div>{logo}<strong>{_escape(organization_name)}</strong></div><span>Private request</span></header><main>
<section class="ask-intro">{owner_avatar}<p class="kicker">{_escape(context.owner.display_name)} is asking you about {_escape(context.project.name)}</p><h1>{_escape(context.ask.title)}</h1>{intro}{default_note}<p class="{deadline_class}"><strong>{deadline_label}</strong> {deadline}</p><p class="progress" role="status">{progress}</p><p>This is a private request for your input. Each answer saves independently, and an overdue request remains open until the asker resolves it. Your link is intended for <strong>{_escape(context.recipient.display_name)}</strong>.</p><small>Not {_escape(context.recipient.display_name)}? Ask the sender for your own link.</small></section>
<section class="questions" aria-label="Questions">{cards or "<p>No Questions are assigned.</p>"}</section></main></body></html>"""
    return HTMLResponse(content, status_code=status_code, headers=_security_headers())


def _question_card(
    session: Session,
    context: InvitationContext,
    assignment: Assignment,
    question: Question,
    decision: Decision | None,
    csrf_token: str,
    error: str | None,
    posted: dict[str, str] | None,
) -> str:
    latest = session.scalar(
        select(Response)
        .where(Response.assignment_id == assignment.id)
        .order_by(Response.version.desc())
        .limit(1)
    )
    saved_value = latest.value if latest else None
    current_value: object | None = posted.get("value") if posted else saved_value
    if posted and question.primitive == QuestionPrimitive.SELECT_MANY:
        current_value = posted.get("_values", "").split("\x1f") if posted.get("_values") else []
    current_comment = posted.get("comment", "") if posted else (latest.comment if latest else "")
    disposition = (
        posted.get("disposition", "answered")
        if posted
        else (latest.disposition.value if latest else "answered")
    )
    options = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == question.id)
            .order_by(QuestionOption.ordinal)
        )
    )
    if question.primitive == QuestionPrimitive.SELECT_ONE:
        control = "".join(
            f"<label class='option'><input type='radio' name='value' value='{_escape(option.value)}' {'checked' if current_value == option.value else ''}><span><strong>{_escape(option.label)}</strong>{f'<small>{_escape(option.consequence)}</small>' if option.consequence else ''}</span></label>"
            for option in options
        )
    elif question.primitive == QuestionPrimitive.SELECT_MANY:
        selected = current_value if isinstance(current_value, list) else []
        control = "".join(
            f"<label class='option'><input type='checkbox' name='value' value='{_escape(option.value)}' {'checked' if option.value in selected else ''}><span><strong>{_escape(option.label)}</strong>{f'<small>{_escape(option.consequence)}</small>' if option.consequence else ''}</span></label>"
            for option in options
        )
    elif question.primitive == QuestionPrimitive.TEXT:
        control = f"<label><span>Your answer</span><textarea name='value' rows='5'>{_escape(current_value if isinstance(current_value, str) else '')}</textarea></label>"
    elif question.primitive == QuestionPrimitive.NUMBER:
        minimum = question.validation.get("min")
        maximum = question.validation.get("max")
        bounds = f"{' min=' + repr(minimum) if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) else ''}{' max=' + repr(maximum) if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) else ''}"
        control = f"<label><span>Your answer</span><input type='number' name='value' step='any'{bounds} value='{_escape(current_value)}'></label>"
    elif question.primitive == QuestionPrimitive.DATE:
        not_before = question.validation.get("not_before")
        not_after = question.validation.get("not_after")
        bounds = f"{' min=' + repr(not_before) if isinstance(not_before, str) else ''}{' max=' + repr(not_after) if isinstance(not_after, str) else ''}"
        control = f"<label><span>Your answer</span><input type='date' name='value'{bounds} value='{_escape(current_value)}'></label>"
    else:
        return f"<article class='question'><h2>{_escape(question.prompt)}</h2><p>This Question format is not available here.</p></article>"
    help_text = f"<p class='help'>{_escape(question.help_text)}</p>" if question.help_text else ""
    correction = (
        "<p class='correction'><strong>Corrected Question</strong> Please answer this revised version.</p>"
        if question.supersedes_question_id
        else ""
    )
    proposal = ""
    if question.proposed_value is not None:
        proposal = f"<aside><strong>Asker proposal</strong><p>{_escape(str(question.proposed_value))}</p><small>{_escape(question.proposed_rationale)}</small></aside>"
    error_html = f"<div class='error' role='alert'>{_escape(error)}</div>" if error else ""
    comment = (
        f"<label><span>Comment or delegation recommendation</span><textarea name='comment' rows='3'>{_escape(current_comment)}</textarea></label>"
        if question.allow_comment
        else ""
    )
    if latest:
        saved_answer = (
            _escape(latest.value) if latest.value is not None else latest.disposition.value
        )
        saved_comment = f"<small>{_escape(latest.comment)}</small>" if latest.comment else ""
        saved = (
            f"<div class='saved' role='status'><strong>Saved response, version {latest.version}</strong>"
            f"<p>{saved_answer}</p>{saved_comment}</div>"
        )
    else:
        saved = ""
    correction_window = ""
    if latest and question.close_eligible_at is not None:
        closes_at = question.close_eligible_at
        if context.ask.deadline is not None:
            closes_at = min(closes_at, context.ask.deadline)
        correction_window = (
            "<p class='deadline'><strong>You can revise until</strong> "
            f"{_local_time(closes_at, context.respondent.timezone)}.</p>"
        )
    outcome = (
        f"<aside class='outcome'><strong>Shared outcome</strong><p>{_escape(decision.statement)}</p></aside>"
        if decision
        else ""
    )
    if context.ask.status == AskStatus.CLOSED or question.state != QuestionState.OPEN:
        return f"<article class='question' id='assignment-{assignment.id}' tabindex='-1'><p class='number'>Question</p><h2>{_escape(question.prompt)}</h2>{help_text}{proposal}{saved}{outcome}<p>This Question is closed and responses are read only.</p></article>"
    disposition_options = "".join(
        f"<option value='{item.value}' {'selected' if disposition == item.value else ''}>{label}</option>"
        for item, label in (
            (ResponseDisposition.ANSWERED, "Answer the Question"),
            (ResponseDisposition.REJECTED_PREMISE, "This is the wrong Question"),
            (ResponseDisposition.DELEGATED, "Not my call - ask someone else"),
            (ResponseDisposition.NEED_CONTEXT, "I need more context"),
            (ResponseDisposition.ABSTAIN, "I abstain"),
        )
    )
    delegate_name = posted.get("delegate_display_name", "") if posted else ""
    delegate_email = posted.get("delegate_email", "") if posted else ""
    return f"""<article class="question" id="assignment-{assignment.id}" tabindex="-1"><p class="number">Question</p><h2>{_escape(question.prompt)}</h2>{correction}{help_text}{proposal}{saved}{correction_window}{error_html}<form method="post" action="/r/i/{context.recipient.id}/questions/{assignment.id}"><input type="hidden" name="csrf_token" value="{csrf_token}"><input type="hidden" name="submission_id" value="{uuid4()}"><fieldset><legend>Your response</legend>{control}</fieldset><label><span>Response type</span><select name="disposition">{disposition_options}</select><small>Choose &quot;Answer&quot; to use the answer above. Other response types preserve only the relevant comment.</small></label>{comment}<label><span>Delegate display name</span><input name="delegate_display_name" value="{_escape(delegate_name)}"><small>Required when you choose &quot;Not my call - ask someone else&quot;.</small></label><label><span>Delegate email <i>optional</i></span><input type="email" name="delegate_email" value="{_escape(delegate_email)}"><small>The asker will receive the handoff and share a new private invitation.</small></label><button type="submit">{"Save revision" if latest else "Save answer"}</button></form></article>"""


def _respondent_csrf(settings: Settings, encoded: str) -> str:
    return hmac.new(
        settings.session_secret.get_secret_value().encode(),
        f"respondent-csrf:{encoded}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _escape(value: object | None) -> str:
    return html.escape(str(value)) if value is not None else ""


def _source_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        return None


def _security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self' https:; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        ),
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }


def _eligible(recipient: AskRecipient, ask: Ask, project: Project) -> bool:
    now = SystemClock().now()
    return bool(
        recipient.revoked_at is None
        and recipient.access_expires_at is not None
        and recipient.access_expires_at > now
        and ask.status in (AskStatus.SENT, AskStatus.CLOSED)
        and (ask.status == AskStatus.CLOSED or project.archived_at is None)
    )


def _failed_exchange(request: Request) -> NoReturn:
    address = request.client.host if request.client else "unknown"
    allowed = failed_exchange_limiter.record_and_allow(address, SystemClock().now())
    logger.warning("respondent_exchange_failed", source_ip=address, throttled=not allowed)
    raise HTTPException(status_code=404 if allowed else 429, detail="invitation unavailable")


def _is_crawler(user_agent: str) -> bool:
    normalized = user_agent.lower()
    return any(value in normalized for value in ("slackbot", "discordbot", "twitterbot"))


def _unfurl(organization: str, owner: str, ask: Ask) -> HTMLResponse:
    deadline = ask.deadline.strftime("%Y-%m-%d") if ask.deadline else "No deadline"
    description = html.escape(f"From {owner} - {deadline}", quote=True)
    content = (
        "<!doctype html><html><head>"
        f"<title>{html.escape(ask.title)}</title>"
        f"<meta property='og:title' content='{html.escape(ask.title, quote=True)}'>"
        f"<meta property='og:site_name' content='{html.escape(organization, quote=True)}'>"
        f"<meta property='og:description' content='{description}'>"
        "</head><body></body></html>"
    )
    return HTMLResponse(
        content,
        headers={**_security_headers(), "Cache-Control": "private, no-store"},
    )


def _local_deadline(ask: Ask, timezone: str) -> str:
    if ask.deadline is None:
        return "No deadline"
    return _local_time(ask.deadline, timezone)


def _local_time(value: datetime, timezone: str) -> str:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return value.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z")


def _safe_image_url(value: str | None) -> bool:
    return bool(value and (value.startswith("/static/") or value.startswith("https://")))


def _minimal_notice(message: str, *, status_code: int) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(message)}</title><link rel='stylesheet' href='/static/respondent.css'>"
        f"</head><body><main class='notice'><h1>{html.escape(message)}</h1></main></body></html>",
        status_code=status_code,
        headers=_security_headers(),
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
