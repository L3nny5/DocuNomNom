"""/config/keywords endpoints.

CRUD against the single default ``ConfigProfile``. Keywords are scoped
to that profile in v1; multi-profile support is intentionally out of
scope for Phase 3.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.models import Keyword
from ...storage.db import SqlKeywordRepository
from ..deps import get_session
from ..schemas.config import KeywordCreate, KeywordOut, KeywordUpdate
from ..services.config_service import ConfigService

router = APIRouter(prefix="/config/keywords", tags=["keywords"])


def _to_out(k: Keyword) -> KeywordOut:
    assert k.id is not None
    return KeywordOut(
        id=k.id,
        term=k.term,
        locale=k.locale,
        enabled=k.enabled,
        weight=k.weight,
    )


def _ensure_profile_id(session: Session) -> int:
    profile = ConfigService(session).ensure_default_profile()
    if profile.id is None:
        raise HTTPException(
            status_code=500,
            detail={"code": "profile_failed", "message": "Could not create default profile"},
        )
    return profile.id


@router.get("", response_model=list[KeywordOut])
def list_keywords(session: Session = Depends(get_session)) -> list[KeywordOut]:
    profile_id = _ensure_profile_id(session)
    return [_to_out(k) for k in SqlKeywordRepository(session).list_for_profile(profile_id)]


@router.post("", response_model=KeywordOut, status_code=status.HTTP_201_CREATED)
def create_keyword(
    body: KeywordCreate,
    session: Session = Depends(get_session),
) -> KeywordOut:
    profile_id = _ensure_profile_id(session)
    created = SqlKeywordRepository(session).add(
        Keyword(
            profile_id=profile_id,
            term=body.term.strip(),
            locale=body.locale,
            enabled=body.enabled,
            weight=body.weight,
        )
    )
    return _to_out(created)


@router.put("/{keyword_id}", response_model=KeywordOut)
def update_keyword(
    keyword_id: int,
    body: KeywordUpdate,
    session: Session = Depends(get_session),
) -> KeywordOut:
    repo = SqlKeywordRepository(session)
    existing = repo.get(keyword_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Keyword not found"},
        )
    updated = repo.update(
        Keyword(
            id=keyword_id,
            profile_id=existing.profile_id,
            term=body.term.strip(),
            locale=body.locale,
            enabled=body.enabled,
            weight=body.weight,
        )
    )
    return _to_out(updated)


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_keyword(
    keyword_id: int,
    session: Session = Depends(get_session),
) -> None:
    deleted = SqlKeywordRepository(session).delete(keyword_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Keyword not found"},
        )
