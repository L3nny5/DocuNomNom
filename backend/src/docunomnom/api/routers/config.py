"""/config endpoints.

GET /config returns the current effective Settings projection plus the
persisted UI overrides. PUT /config replaces the persisted overrides
(see ConfigService for the Phase 3 wire-through caveat).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...config import Settings
from ..deps import get_app_settings, get_session
from ..schemas.config import ConfigOverridesIn, ConfigResponse
from ..services.config_service import ConfigService, current_settings_view

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
def get_config(
    settings: Settings = Depends(get_app_settings),
    session: Session = Depends(get_session),
) -> ConfigResponse:
    overrides, overrides_hash = ConfigService(session).get_overrides()
    return ConfigResponse(
        settings=current_settings_view(settings),
        overrides=overrides,
        overrides_hash=overrides_hash,
    )


@router.put("", response_model=ConfigResponse)
def put_config(
    body: ConfigOverridesIn,
    settings: Settings = Depends(get_app_settings),
    session: Session = Depends(get_session),
) -> ConfigResponse:
    overrides, overrides_hash = ConfigService(session).set_overrides(
        body.model_dump(mode="json", exclude_none=True),
    )
    return ConfigResponse(
        settings=current_settings_view(settings),
        overrides=overrides,
        overrides_hash=overrides_hash,
    )
