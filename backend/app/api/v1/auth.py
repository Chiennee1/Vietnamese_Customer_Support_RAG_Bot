from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_auth_service, get_current_user
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import AuthenticatedIdentity, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await service.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await service.login(email=payload.email, password=payload.password)


@router.get("/me", response_model=UserResponse)
async def me(
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse(
        id=identity.id,
        email=identity.email,
        full_name=identity.full_name,
        role=identity.role,
    )

