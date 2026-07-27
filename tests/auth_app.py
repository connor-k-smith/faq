from app.api.dependencies import get_identity_verifier
from app.domain.ports import IdentityClaims
from app.main import create_app


class PlaywrightIdentityVerifier:
    async def verify(self, id_token: str) -> IdentityClaims:
        parts = id_token.split(":", 2)
        if len(parts) != 3 or parts[0] != "playwright" or not parts[1]:
            raise ValueError("test identity token is invalid")
        return IdentityClaims(
            uid=f"playwright:{parts[1]}",
            email=parts[1],
            email_verified=True,
            display_name=parts[2] or None,
        )


app = create_app()
app.dependency_overrides[get_identity_verifier] = PlaywrightIdentityVerifier
