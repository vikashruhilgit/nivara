"""Auth API routes.

Exposes ``/api/auth/{register,login,refresh,logout,password,me}``.
All token responses use the bearer pattern (see schemas.auth.TokenPair).
"""

from __future__ import annotations

from backend.app.auth.dependencies import get_current_user
from backend.app.db import get_session
from backend.app.models.users import User
from backend.app.redis_client import get_redis
from backend.app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MessageResponse,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserPublic,
)
from backend.app.services.auth import AuthService
from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _service(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    return AuthService(session=session, redis=redis)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, svc: AuthService = Depends(_service)) -> TokenPair:
    return await svc.register(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        locale=payload.locale,
    )


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, svc: AuthService = Depends(_service)) -> TokenPair:
    return await svc.login(email=payload.email, password=payload.password)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, svc: AuthService = Depends(_service)) -> TokenPair:
    return await svc.refresh(refresh_token=payload.refresh_token)


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, svc: AuthService = Depends(_service)) -> MessageResponse:
    await svc.logout(refresh_token=payload.refresh_token)
    return MessageResponse(detail="ok")


@router.post("/password", response_model=MessageResponse)
async def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    svc: AuthService = Depends(_service),
) -> MessageResponse:
    await svc.change_password(
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return MessageResponse(detail="password changed")


@router.post("/password/forgot", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    svc: AuthService = Depends(_service),
) -> MessageResponse:
    ip = request.client.host if request.client else None
    await svc.request_password_reset(payload.email, ip=ip, background_tasks=background_tasks)
    return MessageResponse(detail="If that email exists, a reset link has been sent.")


@router.post("/password/reset", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    svc: AuthService = Depends(_service),
) -> MessageResponse:
    await svc.reset_password(payload.token, payload.new_password)
    return MessageResponse(detail="Password has been reset.")


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
