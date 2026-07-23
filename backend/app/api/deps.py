from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.services.auth import AuthenticatedIdentity, AuthService

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth_service)


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code="AUTH_REQUIRED",
            message="Vui lòng đăng nhập để tiếp tục.",
            status_code=401,
        )
    return await service.authenticate(credentials.credentials)
