"""Authenticated preference and route-review collection APIs.

Only reviews with explicit training consent may enter future global training sets.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import FacilityReport, RouteImpression, RouteReview, User, UserPreference, database_session
from .auth import _preference_dict, current_user

router = APIRouter(prefix="/api", tags=["feedback"])

Profile = Literal["general", "elderly", "child", "disabled"]
IssueType = Literal["stairs", "elevator", "low_floor_bus", "walking_distance", "safety", "weather", "other"]
FacilityIssueType = Literal["missing", "relocated", "closed", "inaccessible", "information_incorrect", "other"]


class PreferenceInput(BaseModel):
    profile: Profile | None = None
    uses_wheelchair: bool | None = None
    avoid_stairs_required: bool | None = None
    max_walk_distance_m: int | None = Field(default=None, ge=100, le=10000)
    training_consent: bool | None = None


class ImpressionInput(BaseModel):
    route_id: str = Field(min_length=1, max_length=120)
    rank: int = Field(ge=1, le=20)
    model_version: str = Field(default="rules-v1", max_length=64)
    feature_snapshot: str = Field(min_length=2, max_length=20000)


class ReviewInput(BaseModel):
    route_id: str = Field(min_length=1, max_length=120)
    impression_id: str | None = None
    was_usable: bool
    rating: int = Field(ge=1, le=5)
    issue_type: IssueType | None = None
    comment: str | None = Field(default=None, max_length=2000)
    training_consent: bool = False


class FacilityReportInput(BaseModel):
    facility_name: str = Field(min_length=2, max_length=200)
    facility_type: str = Field(min_length=2, max_length=64)
    issue_type: FacilityIssueType
    reported_lat: float | None = Field(default=None, ge=33, le=39)
    reported_lng: float | None = Field(default=None, ge=124, le=132)
    description: str | None = Field(default=None, max_length=2000)


@router.put("/me/preferences")
def save_preferences(
    payload: PreferenceInput,
    user: User = Depends(current_user),
    db: Session = Depends(database_session),
) -> dict:
    pref = user.preference
    if pref is None:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(pref, field, value)
    db.flush()
    return _preference_dict(pref)


@router.post("/route-impressions", status_code=201)
def record_impression(
    payload: ImpressionInput,
    user: User = Depends(current_user),
    db: Session = Depends(database_session),
) -> dict:
    impression = RouteImpression(
        user_id=user.id,
        route_id=payload.route_id,
        rank=payload.rank,
        model_version=payload.model_version,
        feature_snapshot=payload.feature_snapshot,
    )
    db.add(impression)
    db.flush()
    return {"id": impression.id}


@router.post("/route-reviews", status_code=201)
def record_review(
    payload: ReviewInput,
    user: User = Depends(current_user),
    db: Session = Depends(database_session),
) -> dict:
    if payload.impression_id:
        impression = db.get(RouteImpression, payload.impression_id)
        if impression is None or impression.user_id != user.id or impression.route_id != payload.route_id:
            raise HTTPException(status_code=400, detail="The review must reference this user's displayed route.")
    review = RouteReview(user_id=user.id, **payload.model_dump())
    db.add(review)
    db.flush()
    return {"id": review.id, "acceptedForTraining": review.training_consent}


@router.post("/facility-reports", status_code=201)
def report_facility(
    payload: FacilityReportInput,
    user: User = Depends(current_user),
    db: Session = Depends(database_session),
) -> dict:
    report = FacilityReport(user_id=user.id, **payload.model_dump())
    db.add(report)
    db.flush()
    return {"id": report.id, "status": report.status}
