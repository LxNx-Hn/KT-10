"""Authenticated preference and route-review collection APIs.

Only reviews with explicit training consent may enter future global training sets.
"""
from __future__ import annotations

import json
from typing import Literal

from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import FacilityReport, RouteImpression, RouteReview, User, UserPreference, database_session
from ..feedback_tokens import verify_feedback_token
from ..personalization import parse_state, reward_target, update_state
from ..settings import settings
from .auth import _preference_dict, current_user

router = APIRouter(prefix="/api", tags=["feedback"])

Profile = Literal[
    "general", "elderly", "child", "youth", "disabled", "pregnant"
]
PROFILE_IDS = {
    "general", "elderly", "child", "youth", "disabled", "pregnant"
}
IssueType = Literal["stairs", "slope", "elevator", "low_floor_bus", "walking_distance", "transfer", "duration", "safety", "weather", "other"]
FacilityIssueType = Literal["missing", "relocated", "closed", "inaccessible", "information_incorrect", "other"]


class ApiInput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PreferenceInput(ApiInput):
    profile: Profile | None = None
    uses_wheelchair: bool | None = None
    uses_walking_aid: bool | None = None
    visual_support_required: bool | None = None
    hearing_support_required: bool | None = None
    avoid_stairs_required: bool | None = None
    max_walk_distance_m: int | None = Field(default=None, ge=100, le=10000)
    training_consent: bool | None = None


class ImpressionInput(ApiInput):
    route_id: str = Field(min_length=1, max_length=120)
    rank: int = Field(ge=1, le=20)
    feedback_token: str = Field(min_length=20, max_length=50000)


class ReviewInput(ApiInput):
    route_id: str = Field(min_length=1, max_length=120)
    impression_id: str
    was_usable: bool
    rating: int = Field(ge=1, le=5)
    issue_type: IssueType | None = None
    stairs_difficulty: int | None = Field(default=None, ge=1, le=5)
    slope_difficulty: int | None = Field(default=None, ge=1, le=5)
    transfer_difficulty: int | None = Field(default=None, ge=1, le=5)
    crowding_difficulty: int | None = Field(default=None, ge=1, le=5)
    transfer_information_difficulty: int | None = Field(default=None, ge=1, le=5)
    accessibility_facility_difficulty: int | None = Field(
        default=None,
        ge=1,
        le=5,
    )
    actual_duration_min: int | None = Field(default=None, ge=1, le=1440)
    would_reuse: bool | None = None
    information_accurate: bool | None = None
    comment: str | None = Field(default=None, max_length=2000)
    training_consent: bool = False


class FacilityReportInput(ApiInput):
    facility_name: str = Field(min_length=2, max_length=200)
    facility_type: str = Field(min_length=2, max_length=64)
    issue_type: FacilityIssueType
    reported_lat: float | None = Field(default=None, ge=34.8, le=35.5)
    reported_lng: float | None = Field(default=None, ge=128.7, le=129.4)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_reported_location(self):
        if (self.reported_lat is None) != (self.reported_lng is None):
            raise ValueError("reportedLat and reportedLng must be provided together.")
        return self


class FacilityModerationInput(ApiInput):
    status: Literal["pending", "verified", "rejected", "resolved"]
    resolution_note: str = Field(min_length=2, max_length=2000)


def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator permission required.")
    return user


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
    try:
        snapshot = verify_feedback_token(payload.feedback_token)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if snapshot.get("route_id") != payload.route_id:
        raise HTTPException(status_code=400, detail="Feedback token route does not match.")
    if snapshot["displayed_rank"] != payload.rank:
        raise HTTPException(
            status_code=400,
            detail="Feedback token displayed rank does not match.",
        )
    profile = snapshot["features"].get("profile")
    if profile not in PROFILE_IDS:
        raise HTTPException(
            status_code=400,
            detail="Feedback token profile is invalid.",
        )

    impression = RouteImpression(
        user_id=user.id,
        route_id=payload.route_id,
        rank=payload.rank,
        model_version=snapshot["model_version"],
        profile=profile,
        feature_snapshot=json.dumps(snapshot["features"], ensure_ascii=False, separators=(",", ":")),
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
    if not settings.personalization_configured:
        raise HTTPException(status_code=503, detail="Personalization policy is not configured.")
    learning_rate = settings.personalization_learning_rate
    regularization = settings.personalization_regularization
    usable_weight = settings.personalization_usable_weight
    rating_weight = settings.personalization_rating_weight
    reuse_weight = settings.personalization_reuse_weight
    if any(
        value is None
        for value in (
            learning_rate,
            regularization,
            usable_weight,
            rating_weight,
            reuse_weight,
        )
    ):
        raise HTTPException(
            status_code=503,
            detail="Personalization policy is incomplete.",
        )
    impression = db.get(RouteImpression, payload.impression_id)
    if impression is None or impression.user_id != user.id or impression.route_id != payload.route_id:
        raise HTTPException(status_code=400, detail="The review must reference this user's displayed route.")
    existing_review = (
        db.query(RouteReview)
        .filter(
            RouteReview.user_id == user.id,
            RouteReview.impression_id == payload.impression_id,
        )
        .first()
    )
    if existing_review is not None:
        raise HTTPException(
            status_code=409,
            detail="This displayed route already has a review.",
        )
    # 동일 사용자의 서로 다른 후기가 동시에 도착해도 마지막 커밋이 이전
    # 온라인 학습 갱신을 덮어쓰지 않도록 상태 행을 직렬화한다.
    preference = db.scalar(
        select(UserPreference)
        .where(UserPreference.user_id == user.id)
        .with_for_update()
    )
    if preference is None:
        preference = UserPreference(user_id=user.id)
        db.add(preference)
        db.flush()
    review = RouteReview(user_id=user.id, **payload.model_dump())
    db.add(review)
    features = json.loads(impression.feature_snapshot)
    target = reward_target(
        was_usable=payload.was_usable,
        rating=payload.rating,
        would_reuse=payload.would_reuse,
        usable_weight=usable_weight,
        rating_weight=rating_weight,
        reuse_weight=reuse_weight,
    )
    preference.personalization_state = json.dumps(
        update_state(
            parse_state(preference.personalization_state),
            features,
            target,
            learning_rate_base=learning_rate,
            regularization=regularization,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="This displayed route already has a review.",
        ) from exc
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


@router.get("/admin/facility-reports")
def list_facility_reports(
    status_filter: Literal[
        "pending", "verified", "rejected", "resolved"
    ] | None = Query(default=None, alias="status"),
    _: User = Depends(current_admin),
    db: Session = Depends(database_session),
) -> list[dict]:
    query = db.query(FacilityReport).order_by(FacilityReport.created_at.desc())
    if status_filter:
        query = query.filter(FacilityReport.status == status_filter)
    return [
        {
            "id": report.id,
            "facilityName": report.facility_name,
            "facilityType": report.facility_type,
            "issueType": report.issue_type,
            "reportedLat": report.reported_lat,
            "reportedLng": report.reported_lng,
            "description": report.description,
            "status": report.status,
            "resolutionNote": report.resolution_note,
            "createdAt": report.created_at.isoformat(),
        }
        for report in query.all()
    ]


@router.patch("/admin/facility-reports/{report_id}")
def moderate_facility_report(
    report_id: str,
    payload: FacilityModerationInput,
    admin: User = Depends(current_admin),
    db: Session = Depends(database_session),
) -> dict:
    report = db.get(FacilityReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Facility report not found.")
    report.status = payload.status
    report.resolution_note = payload.resolution_note
    report.reviewed_by = admin.id
    report.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    return {"id": report.id, "status": report.status}
