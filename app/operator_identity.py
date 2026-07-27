from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.google_identity import (
    GoogleIdentityError,
    GoogleIdentityVerifier,
    GooglePrincipal,
    get_google_identity_verifier,
)


def require_operator_identity(
    settings: Annotated[Settings, Depends(get_settings)],
    verifier: Annotated[GoogleIdentityVerifier, Depends(get_google_identity_verifier)],
    authorization: Annotated[str | None, Header()] = None,
) -> GooglePrincipal:
    if settings.operator_audience is None or authorization is None:
        raise HTTPException(status_code=401, detail="valid operator identity required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="valid operator identity required")
    try:
        principal = verifier.verify(token.strip(), settings.operator_audience)
    except GoogleIdentityError as error:
        raise HTTPException(status_code=401, detail="valid operator identity required") from error
    if principal.email not in settings.operator_allowed_emails:
        raise HTTPException(status_code=403, detail="operator is not authorized")
    return principal


OperatorPrincipal = Annotated[GooglePrincipal, Depends(require_operator_identity)]
