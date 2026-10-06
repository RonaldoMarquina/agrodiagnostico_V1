"""Strict administrative inputs matching the closed catalog HTTP contracts."""
from datetime import datetime
import re
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, ValidationError, field_validator

Name = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]
Practice = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
Source = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=300)]


class ClosedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CropCreate(ClosedInput):
    code: str
    name: Name
    active: StrictBool = True


class ProblemCreate(CropCreate):
    crop_code: str
    problem_type: str


class ReviewEvidence(ClosedInput):
    source_refs: Annotated[list[Source], Field(min_length=1, max_length=20)]
    review_reference: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    reviewed_by: Name
    reviewed_at: str

    @field_validator('source_refs')
    @classmethod
    def sources_not_blank(cls, value):
        if any(not source.strip() for source in value):
            raise ValueError('Blank source')
        return value

    @field_validator('review_reference', 'reviewed_by')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('Blank review evidence')
        return value

    @field_validator('reviewed_at')
    @classmethod
    def utc_timestamp(cls, value):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', value):
            raise ValueError('UTC timestamp required')
        datetime.fromisoformat(value[:-1] + '+00:00')
        return value


class RecommendationCreate(ReviewEvidence):
    problem_code: Annotated[str, StringConstraints(pattern=r'^[A-Z][A-Z0-9_]+$', max_length=80)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    summary: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    cultural_practices: Annotated[list[Practice], Field(max_length=20)]
    biological_control: Annotated[list[Practice], Field(max_length=20)]
    preventive_measures: Annotated[list[Practice], Field(max_length=20)]
    active: StrictBool = True


def validate_catalog_input(model, data):
    if model is RecommendationCreate:
        try:
            ReviewEvidence.model_validate({key: data[key] for key in ReviewEvidence.model_fields if key in data})
        except ValidationError:
            raise HTTPException(400, detail={'code': 'CATALOG_REVIEW_REQUIRED', 'message': 'Evidencia de revisión inválida o ausente.'}) from None
    try:
        model.model_validate(data)
    except ValidationError:
        raise HTTPException(400, detail={'code': 'INVALID_REQUEST', 'message': 'Campos de catálogo inválidos o no permitidos.'}) from None
