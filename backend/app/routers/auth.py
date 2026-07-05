from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import ConflictError, AuthError
from ..database import get_db
from ..deps import get_current_user
from ..models import Organization, User
from ..models.enums import UserRole
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from ..security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing:
        raise ConflictError("Email already registered")

    slug_base = _slugify(body.organization_name)
    slug = slug_base
    n = 1
    while db.execute(select(Organization).where(Organization.slug == slug)).scalar_one_or_none():
        n += 1
        slug = f"{slug_base}-{n}"

    org = Organization(name=body.organization_name, slug=slug)
    db.add(org)
    db.flush()

    user = User(
        organization_id=org.id,
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id, {"org": org.id}))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise AuthError("Invalid credentials")
    return TokenResponse(access_token=create_access_token(user.id, {"org": user.organization_id}))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
