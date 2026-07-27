from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class TokenGenerator(Protocol):
    def urlsafe(self, byte_count: int = 32) -> str: ...


@dataclass(frozen=True)
class IdentityClaims:
    uid: str
    email: str
    email_verified: bool
    display_name: str | None = None
    avatar_url: str | None = None


class IdentityVerifier(Protocol):
    async def verify(self, id_token: str) -> IdentityClaims: ...


@dataclass(frozen=True)
class DraftQuestion:
    template_id: str
    prompt: str


@dataclass(frozen=True)
class AssistantDraft:
    title: str
    questions: Sequence[DraftQuestion]


class AuthoringAssistant(Protocol):
    async def draft_questions(self, source_text: str) -> AssistantDraft: ...
