from typing import Any, cast

from anyio import to_thread
from firebase_admin import auth, get_app, initialize_app
from firebase_admin.credentials import ApplicationDefault
from firebase_admin.exceptions import FirebaseError

from app.domain.ports import IdentityClaims


class FirebaseIdentityVerifier:
    def __init__(self, project_id: str | None) -> None:
        self.project_id = project_id

    async def verify(self, id_token: str) -> IdentityClaims:
        try:
            decoded = await to_thread.run_sync(_verify_token, id_token, self.project_id)
        except (FirebaseError, ValueError) as error:
            raise ValueError("Firebase identity token is invalid") from error
        email = decoded.get("email")
        if not isinstance(email, str):
            raise ValueError("Firebase identity has no email claim")
        return IdentityClaims(
            uid=str(decoded["uid"]),
            email=email,
            email_verified=decoded.get("email_verified") is True,
            display_name=_optional_string(decoded.get("name")),
            avatar_url=_optional_string(decoded.get("picture")),
        )


def _verify_token(id_token: str, project_id: str | None) -> dict[str, Any]:
    try:
        app = get_app()
    except ValueError:
        options = {"projectId": project_id} if project_id else None
        app = initialize_app(ApplicationDefault(), options=options)
    return cast(dict[str, Any], auth.verify_id_token(id_token, app=app, check_revoked=True))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
