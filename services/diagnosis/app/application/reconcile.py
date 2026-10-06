"""Maintenance command for reconciling orphaned image upload intents with FOR UPDATE SKIP LOCKED."""
import logging
import sys
from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Diagnosis, ImageUploadIntent
from app.storage import S3StorageAdapter, StorageError

logger = logging.getLogger(__name__)


def reconcile_upload_intents(
    db: Session,
    storage: S3StorageAdapter,
    batch_size: int = 100,
) -> Dict[str, int]:
    """Reconcile orphaned image upload intents.
    
    Invariants:
    1. Uses FOR UPDATE SKIP LOCKED to skip active in-progress uploads.
    2. Checks if any diagnosis references the object_key or diagnosis_id.
    3. If referenced: preserves S3 object, deletes leftover intent.
    4. If unreferenced: deletes S3 object (absent counts as success), then deletes intent.
    5. If S3 delete fails: preserves intent in DB so it can be retried.
    """
    stmt = (
        select(ImageUploadIntent)
        .order_by(ImageUploadIntent.created_at.asc())
        .limit(batch_size)
    )
    if db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    else:
        stmt = stmt.with_for_update()

    intents = db.execute(stmt).scalars().all()

    reconciled = 0
    kept_referenced = 0
    failed = 0

    for intent in intents:
        # Check if any diagnosis references this object_key or diagnosis_id
        ref = db.execute(
            select(Diagnosis.id).where(
                (Diagnosis.object_key == intent.object_key) | (Diagnosis.id == intent.diagnosis_id)
            )
        ).scalar_one_or_none()

        if ref is not None:
            # Diagnosis exists! Keep object in S3, delete the leftover intent
            db.delete(intent)
            kept_referenced += 1
        else:
            # No diagnosis exists. Orphan upload. Delete object from S3
            try:
                storage.delete_object(intent.object_key)
                db.delete(intent)
                reconciled += 1
            except StorageError as exc:
                logger.error(
                    "Failed to delete orphaned object %s during reconciliation: %s",
                    intent.object_key,
                    exc,
                )
                failed += 1

    db.commit()
    return {
        "reconciled": reconciled,
        "kept_referenced": kept_referenced,
        "failed": failed,
    }


def reconcile_image_upload_intents(
    db: Session,
    storage: S3StorageAdapter,
    limit: int = 100,
    batch_size: int = 100,
) -> Dict[str, int]:
    """Compatibility alias for intent reconciliation."""
    res = reconcile_upload_intents(db, storage, batch_size=limit if limit is not None else batch_size)
    return {
        "processed": res["reconciled"] + res["kept_referenced"],
        "cleaned_orphans": res["reconciled"],
        "reconciled_valid": res["kept_referenced"],
        "failed": res["failed"],
        **res,
    }


def main():
    """CLI entry point for intent reconciliation."""
    logging.basicConfig(level=logging.INFO)
    from app.persistence import get_sessionmaker
    from app.storage import get_storage_adapter

    sm = get_sessionmaker()
    storage = get_storage_adapter()

    with sm() as session:
        stats = reconcile_upload_intents(session, storage)
        print(f"Reconciliation result: {stats}")
        if stats["failed"] > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
