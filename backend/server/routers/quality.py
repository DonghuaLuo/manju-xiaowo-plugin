"""Manual quality ratings and quality statistics routes."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from lib.app_data_dir import app_data_dir
from lib.project_manager import ProjectManager
from server.auth import CurrentUser
from server.services.quality_metrics import QualityMetricsService

router = APIRouter()

pm = ProjectManager(app_data_dir())


class QualityRatingRequest(BaseModel):
    resource_type: Literal["storyboards", "videos", "reference_videos", "characters", "scenes", "props"]
    resource_id: str
    version: int | None = None
    rating: int = Field(..., ge=1, le=5)
    dimensions: dict[str, int] | None = None
    note: str | None = None
    provider: str | None = None
    model: str | None = None
    generation_quality: str | None = None


def _service() -> QualityMetricsService:
    return QualityMetricsService(pm)


@router.post("/projects/{project_name}/quality-ratings")
async def upsert_quality_rating(
    project_name: str,
    req: QualityRatingRequest,
    _user: CurrentUser,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _service().upsert_rating,
            project_name=project_name,
            resource_type=req.resource_type,
            resource_id=req.resource_id,
            version=req.version,
            rating=req.rating,
            dimensions=req.dimensions,
            note=req.note,
            provider=req.provider,
            model=req.model,
            generation_quality=req.generation_quality,
            user_id=_user.id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/projects/{project_name}/quality-ratings")
async def list_quality_ratings(
    project_name: str,
    _user: CurrentUser,
    resource_type: str | None = Query(None),
    resource_id: str | None = Query(None),
    version: int | None = Query(None),
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _service().list_ratings,
            project_name=project_name,
            resource_type=resource_type,
            resource_id=resource_id,
            version=version,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/projects/{project_name}/quality-stats")
async def get_quality_stats(project_name: str, _user: CurrentUser) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_service().get_stats, project_name=project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/quality-analysis")
async def get_quality_analysis(_user: CurrentUser) -> dict[str, Any]:
    return await asyncio.to_thread(_service().get_global_analysis)
