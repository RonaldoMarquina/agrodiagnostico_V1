"""Application service for agricultural catalog (crops, problems, recommendations) and administrative management."""
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.catalog_input import CropCreate, ProblemCreate, RecommendationCreate, validate_catalog_input
from app.domain.models import Crop, DiagnosisAuditLog, Problem, Recommendation
from app.infrastructure.cursor import format_utc_iso, parse_utc_iso
from app.infrastructure.security import Principal

ALLOWED_V1_CROPS = {"POTATO", "MAIZE"}

ALLOWED_V1_PROBLEMS = {
    "POTATO_HEALTHY": ("POTATO", "HEALTHY"),
    "POTATO_EARLY_BLIGHT": ("POTATO", "DISEASE"),
    "POTATO_LATE_BLIGHT": ("POTATO", "DISEASE"),
    "MAIZE_HEALTHY": ("MAIZE", "HEALTHY"),
    "MAIZE_COMMON_RUST": ("MAIZE", "DISEASE"),
    "MAIZE_LEAF_BLIGHT": ("MAIZE", "DISEASE"),
    "MAIZE_GRAY_LEAF_SPOT": ("MAIZE", "DISEASE"),
}


def serialize_crop(crop: Crop) -> Dict[str, Any]:
    return {
        "code": crop.code,
        "name": crop.name,
        "active": crop.active,
        "created_at": format_utc_iso(crop.created_at),
        "updated_at": format_utc_iso(crop.updated_at),
    }


def serialize_problem(problem: Problem) -> Dict[str, Any]:
    return {
        "code": problem.code,
        "crop_code": problem.crop_code,
        "name": problem.name,
        "problem_type": problem.type,
        "model_supported": problem.model_supported,
        "active": problem.active,
        "created_at": format_utc_iso(problem.created_at),
        "updated_at": format_utc_iso(problem.updated_at),
    }


def serialize_recommendation(rec: Recommendation) -> Dict[str, Any]:
    return {
        "id": str(rec.id),
        "problem_code": rec.problem_code,
        "version": rec.version,
        "title": rec.title,
        "summary": rec.summary,
        "cultural_practices": rec.cultural_practices,
        "biological_control": rec.biological_control,
        "preventive_measures": rec.preventive_measures,
        "source_refs": rec.source_refs,
        "review_reference": rec.review_reference,
        "reviewed_by": rec.reviewed_by,
        "reviewed_at": format_utc_iso(rec.reviewed_at),
        "active": rec.active,
        "created_at": format_utc_iso(rec.created_at),
        "updated_at": format_utc_iso(rec.updated_at),
    }


# =============================================================================
# Public Catalog Services
# =============================================================================

def get_public_crops(db: Session) -> Dict[str, Any]:
    """Retrieve all active crops."""
    stmt = select(Crop).where(Crop.active.is_(True)).order_by(Crop.code.asc())
    crops = db.scalars(stmt).all()
    return {"items": [serialize_crop(c) for c in crops]}


def get_public_crop_problems(db: Session, crop_code: str) -> Dict[str, Any]:
    """Retrieve all active candidate problems for an active crop."""
    crop = db.get(Crop, crop_code)
    if crop is None or not crop.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Cultivo no encontrado o inactivo."},
        )

    stmt = (
        select(Problem)
        .where(Problem.crop_code == crop_code, Problem.active.is_(True))
        .order_by(Problem.code.asc())
    )
    problems = db.scalars(stmt).all()
    return {"items": [serialize_problem(p) for p in problems]}


def get_public_problem_recommendations(db: Session, problem_code: str) -> Dict[str, Any]:
    """Retrieve the latest approved active recommendation version for an active problem and active crop."""
    problem = db.get(Problem, problem_code)
    if problem is None or not problem.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Condición agrícola no encontrada o inactiva."},
        )

    crop = db.get(Crop, problem.crop_code)
    if crop is None or not crop.active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Cultivo no encontrado o inactivo."},
        )

    stmt = (
        select(Recommendation)
        .where(Recommendation.problem_code == problem_code, Recommendation.active.is_(True))
        .order_by(Recommendation.version.desc())
        .limit(1)
    )
    rec = db.scalars(stmt).first()
    items = [serialize_recommendation(rec)] if rec is not None else []
    return {"items": items}


# =============================================================================
# Admin Catalog Services: Crops
# =============================================================================

def get_admin_crops(db: Session) -> Dict[str, Any]:
    """List all crops (active and inactive) for admin."""
    stmt = select(Crop).order_by(Crop.code.asc())
    crops = db.scalars(stmt).all()
    return {"items": [serialize_crop(c) for c in crops]}


def create_admin_crop(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new crop strictly restricted to V1 taxonomy."""
    validate_catalog_input(CropCreate, data)
    code = data.get("code")
    name = data.get("name")
    active = data.get("active", True)

    if not code or code not in ALLOWED_V1_CROPS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Código de cultivo no permitido en la taxonomía V1."},
        )

    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 100):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Nombre de cultivo inválido (1..100 caracteres)."},
        )

    if not isinstance(active, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "El campo active debe ser booleano."},
        )

    existing = db.get(Crop, code)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CATALOG_CONFLICT", "message": "El cultivo ya existe."},
        )

    now = datetime.now(timezone.utc)
    new_crop = Crop(
        code=code,
        name=name.strip(),
        active=active,
        created_at=now,
        updated_at=now,
    )
    db.add(new_crop)

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_CREATE_CROP",
        target_type="crop",
        target_id=code,
        correlation_id=correlation_id,
        details={"name": name.strip(), "active": active},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_crop(new_crop)


def patch_admin_crop(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    code: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Update mutable crop fields (name, active). Code is immutable."""
    disallowed_fields = set(data.keys()) - {"name", "active"}
    if disallowed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": f"Campos no permitidos para edición: {sorted(list(disallowed_fields))}"},
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Debe especificar al menos un campo a modificar."},
        )

    crop = db.get(Crop, code)
    if crop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Cultivo no encontrado."},
        )

    changes: Dict[str, Any] = {}
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 100):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Nombre de cultivo inválido (1..100 caracteres)."},
            )
        crop.name = name.strip()
        changes["name"] = crop.name

    if "active" in data:
        active = data["active"]
        if not isinstance(active, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "El campo active debe ser booleano."},
            )
        crop.active = active
        changes["active"] = crop.active

    now = datetime.now(timezone.utc)
    crop.updated_at = now

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_PATCH_CROP",
        target_type="crop",
        target_id=code,
        correlation_id=correlation_id,
        details={"changes": changes},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_crop(crop)


# =============================================================================
# Admin Catalog Services: Problems
# =============================================================================

def get_admin_problems(db: Session) -> Dict[str, Any]:
    """List all problems (active and inactive) for admin."""
    stmt = select(Problem).order_by(Problem.crop_code.asc(), Problem.code.asc())
    problems = db.scalars(stmt).all()
    return {"items": [serialize_problem(p) for p in problems]}


def create_admin_problem(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new problem condition strictly restricted to V1 taxonomy."""
    validate_catalog_input(ProblemCreate, data)
    code = data.get("code")
    crop_code = data.get("crop_code")
    name = data.get("name")
    problem_type = data.get("problem_type")
    active = data.get("active", True)

    if not code or code not in ALLOWED_V1_PROBLEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Código de condición no permitido en la taxonomía V1."},
        )

    expected_crop, expected_type = ALLOWED_V1_PROBLEMS[code]
    if crop_code != expected_crop or problem_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Inconsistencia con la taxonomía V1 para este problema."},
        )

    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 100):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Nombre de condición inválido (1..100 caracteres)."},
        )

    if not isinstance(active, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "El campo active debe ser booleano."},
        )

    crop = db.get(Crop, crop_code)
    if crop is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Cultivo padre no existe."},
        )

    existing = db.get(Problem, code)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CATALOG_CONFLICT", "message": "La condición agrícola ya existe."},
        )

    now = datetime.now(timezone.utc)
    new_problem = Problem(
        code=code,
        crop_code=crop_code,
        name=name.strip(),
        type=problem_type,
        model_supported=False,  # Initially unsupported
        active=active,
        created_at=now,
        updated_at=now,
    )
    db.add(new_problem)

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_CREATE_PROBLEM",
        target_type="problem",
        target_id=code,
        correlation_id=correlation_id,
        details={"crop_code": crop_code, "name": name.strip(), "problem_type": problem_type, "active": active},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_problem(new_problem)


def patch_admin_problem(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    code: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Update mutable problem fields (name, active). Code, crop_code, problem_type, and model_supported are immutable."""
    disallowed_fields = set(data.keys()) - {"name", "active"}
    if disallowed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": f"Campos no permitidos para edición: {sorted(list(disallowed_fields))}"},
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Debe especificar al menos un campo a modificar."},
        )

    problem = db.get(Problem, code)
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Condición agrícola no encontrada."},
        )

    changes: Dict[str, Any] = {}
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 100):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "Nombre de condición inválido (1..100 caracteres)."},
            )
        problem.name = name.strip()
        changes["name"] = problem.name

    if "active" in data:
        active = data["active"]
        if not isinstance(active, bool):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_REQUEST", "message": "El campo active debe ser booleano."},
            )
        problem.active = active
        changes["active"] = problem.active

    now = datetime.now(timezone.utc)
    problem.updated_at = now

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_PATCH_PROBLEM",
        target_type="problem",
        target_id=code,
        correlation_id=correlation_id,
        details={"changes": changes},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_problem(problem)


# =============================================================================
# Admin Catalog Services: Recommendations
# =============================================================================

def get_admin_recommendations(db: Session, problem_code: Optional[str] = None) -> Dict[str, Any]:
    """List recommendation versions for admin, optionally filtered by problem_code."""
    stmt = select(Recommendation)
    if problem_code:
        stmt = stmt.where(Recommendation.problem_code == problem_code)
    stmt = stmt.order_by(Recommendation.problem_code.asc(), Recommendation.version.desc())
    recs = db.scalars(stmt).all()
    return {"items": [serialize_recommendation(r) for r in recs]}


def create_admin_recommendation(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new incremental recommendation version requiring formal review and sources."""
    validate_catalog_input(RecommendationCreate, data)
    problem_code = data.get("problem_code")
    title = data.get("title")
    summary = data.get("summary")
    cultural_practices = data.get("cultural_practices")
    biological_control = data.get("biological_control")
    preventive_measures = data.get("preventive_measures")
    source_refs = data.get("source_refs")
    review_reference = data.get("review_reference")
    reviewed_by = data.get("reviewed_by")
    reviewed_at_str = data.get("reviewed_at")
    active = data.get("active", True)

    # Validate review evidence presence
    if (
        not source_refs
        or not isinstance(source_refs, list)
        or len(source_refs) < 1
        or not review_reference
        or not isinstance(review_reference, str)
        or not review_reference.strip()
        or not reviewed_by
        or not isinstance(reviewed_by, str)
        or not reviewed_by.strip()
        or not reviewed_at_str
        or not isinstance(reviewed_at_str, str)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CATALOG_REVIEW_REQUIRED",
                "message": "Se requiere evidencia y fuentes de revisión agronómica aprobadas.",
            },
        )

    try:
        reviewed_at = parse_utc_iso(reviewed_at_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "CATALOG_REVIEW_REQUIRED",
                "message": "Fecha de revisión reviewed_at inválida.",
            },
        )

    # Validate text content
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 200):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Título de recomendación inválido (1..200 caracteres)."},
        )
    if not isinstance(summary, str) or not (1 <= len(summary.strip()) <= 1000):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Resumen de recomendación inválido (1..1000 caracteres)."},
        )
    if not isinstance(cultural_practices, list) or not isinstance(biological_control, list) or not isinstance(preventive_measures, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Las prácticas culturales, control biológico y medidas preventivas deben ser listas."},
        )

    # Lock problem row and compute incremental version
    stmt = select(Problem).where(Problem.code == problem_code)
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    problem = db.scalars(stmt).first()
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Condición agrícola no encontrada."},
        )

    max_ver = db.execute(
        select(func.max(Recommendation.version)).where(Recommendation.problem_code == problem_code)
    ).scalar() or 0
    new_version = max_ver + 1

    rec_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    new_rec = Recommendation(
        id=rec_id,
        problem_code=problem_code,
        version=new_version,
        title=title.strip(),
        summary=summary.strip(),
        cultural_practices=cultural_practices,
        biological_control=biological_control,
        preventive_measures=preventive_measures,
        source_refs=source_refs,
        review_reference=review_reference.strip(),
        reviewed_by=reviewed_by.strip(),
        reviewed_at=reviewed_at,
        active=active,
        created_at=now,
        updated_at=now,
    )
    db.add(new_rec)

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_CREATE_RECOMMENDATION",
        target_type="recommendation",
        target_id=str(rec_id),
        correlation_id=correlation_id,
        details={"problem_code": problem_code, "version": new_version, "title": title.strip()},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_recommendation(new_rec)


def patch_admin_recommendation(
    db: Session,
    principal: Principal,
    correlation_id: uuid.UUID,
    rec_id: uuid.UUID,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Update only the 'active' status of a recommendation version. All content and version are immutable."""
    disallowed_fields = set(data.keys()) - {"active"}
    if disallowed_fields or "active" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "Solo se permite modificar el campo active de una recomendación."},
        )

    active = data["active"]
    if not isinstance(active, bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_REQUEST", "message": "El campo active debe ser booleano."},
        )

    rec = db.get(Recommendation, rec_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Recomendación no encontrada."},
        )

    rec.active = active
    now = datetime.now(timezone.utc)
    rec.updated_at = now

    audit_entry = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_PATCH_RECOMMENDATION",
        target_type="recommendation",
        target_id=str(rec_id),
        correlation_id=correlation_id,
        details={"active": active},
        created_at=now,
    )
    db.add(audit_entry)
    db.commit()

    return serialize_recommendation(rec)
