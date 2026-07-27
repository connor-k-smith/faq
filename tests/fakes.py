from datetime import datetime

from app.domain.ports import AssistantDraft, IdentityClaims
from app.google_identity import GoogleIdentityError, GooglePrincipal


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


class DeterministicTokenGenerator:
    def __init__(self, token: str = "test-token") -> None:
        self.token = token

    def urlsafe(self, byte_count: int = 32) -> str:
        return f"{self.token}-{byte_count}"


class FakeIdentityVerifier:
    def __init__(self, claims: IdentityClaims) -> None:
        self.claims = claims

    async def verify(self, id_token: str) -> IdentityClaims:
        return self.claims


class FakeGoogleIdentityVerifier:
    def __init__(
        self, *, email: str = "operator@example.com", valid_token: str = "valid-token"
    ) -> None:
        self.email = email
        self.valid_token = valid_token
        self.calls: list[tuple[str, str]] = []

    def verify(self, bearer_token: str, audience: str) -> GooglePrincipal:
        self.calls.append((bearer_token, audience))
        if bearer_token != self.valid_token:
            raise GoogleIdentityError("invalid identity")
        return GooglePrincipal(email=self.email)


class FakeMetricsSink:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self.values[name] = self.values.get(name, 0) + value


class FakeAuthoringAssistant:
    def __init__(self, draft: AssistantDraft) -> None:
        self.draft = draft

    async def draft_questions(self, source_text: str) -> AssistantDraft:
        return self.draft
