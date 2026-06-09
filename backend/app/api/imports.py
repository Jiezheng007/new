"""CSV / JSON import API (Phase 3 / Issue 5).

Risk-control (and admin) users can upload CSV or JSON files for bulk
opinion-item loading. Imported rows go through the same
``ingest_records`` funnel as RSS / static-demo so dedup and persistence
behaviour is identical.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.datasource import DataSource
from app.models.role_codes import RoleCode
from app.models.user import User
from app.schemas.imports import ImportResultOut
from app.services.audit import get_client_ip, record_audit
from app.services.connectors import (
    SOURCE_TYPE_CSV,
    SOURCE_TYPE_JSON_IMPORT,
)
from app.services.ingestion import IngestionResult, ingest_records
from app.services.importers import ImportParseError, parse_csv, parse_json
from app.services.analysis import analyze_batch, opinions_by_ids


router = APIRouter(prefix="/api/import", tags=["import"])


_IMPORT_ROLES = {RoleCode.ADMIN, RoleCode.RISK_CONTROL}


def _require_importer(user: User = Depends(get_current_user)) -> User:
    if user.role.code not in _IMPORT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.code}' is not permitted to import data",
        )
    return user


def _load_import_source(db: Session, code: str, source_type: str) -> DataSource:
    source = db.query(DataSource).filter(DataSource.code == code).one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import sink '{code}' is missing. Run bootstrap to seed it.",
        )
    return source


async def _read_upload(file: UploadFile, max_bytes: int = 5 * 1024 * 1024) -> str:
    blob = await file.read(max_bytes + 1)
    if len(blob) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"上传文件超过 {max_bytes // 1024} KB 限制",
        )
    try:
        return blob.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件需要 UTF-8 编码: {e}",
        ) from e


@router.post("/csv", response_model=ImportResultOut)
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(_require_importer),
) -> ImportResultOut:
    ip = get_client_ip(request)
    text = await _read_upload(file)
    try:
        records, parse_errors = parse_csv(text)
    except ImportParseError as e:
        record_audit(
            db,
            actor=user,
            action="import.csv",
            target_type="import_batch",
            target_id=file.filename or "csv",
            result="failure",
            detail={"reason": "parse_fatal", "error": str(e)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": str(e), "errors": e.errors})

    source = _load_import_source(db, "import_csv", SOURCE_TYPE_CSV)
    result = ingest_records(db, source, records, origin="import_csv")
    result.errors = parse_errors + result.errors
    rejected_total = len(parse_errors) + result.rejected

    analyzed_count = 0
    if result.sample_ids:
        opinions = opinions_by_ids(db, result.sample_ids)
        analyzed = analyze_batch(db, opinions)
        analyzed_count = sum(1 for r in analyzed if r.status == "success")

    record_audit(
        db,
        actor=user,
        action="import.csv",
        target_type="import_batch",
        target_id=file.filename or "csv",
        result="success" if rejected_total == 0 and result.duplicate == 0 else "partial",
        detail={
            "filename": file.filename,
            "accepted": result.accepted,
            "rejected": rejected_total,
            "duplicate": result.duplicate,
            "analyzed": analyzed_count,
        },
        ip_address=ip,
    )
    db.commit()
    return ImportResultOut(
        format="csv",
        accepted=result.accepted,
        rejected=rejected_total,
        duplicate=result.duplicate,
        errors=result.errors,
        sample_ids=result.sample_ids,
        message=f"已接收 {result.accepted} 条,拒绝 {rejected_total} 条,重复 {result.duplicate} 条",
    )


@router.post("/json", response_model=ImportResultOut)
async def import_json(
    request: Request,
    file: Optional[UploadFile] = File(None),
    payload: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(_require_importer),
) -> ImportResultOut:
    ip = get_client_ip(request)
    if file is not None:
        text = await _read_upload(file)
        source_name = file.filename or "json-upload"
    elif payload:
        text = payload
        source_name = "json-body"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="需要上传 JSON 文件或在 payload 字段提供 JSON 内容")

    try:
        records, parse_errors = parse_json(text)
    except ImportParseError as e:
        record_audit(
            db,
            actor=user,
            action="import.json",
            target_type="import_batch",
            target_id=source_name,
            result="failure",
            detail={"reason": "parse_fatal", "error": str(e)},
            ip_address=ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": str(e), "errors": e.errors})

    source = _load_import_source(db, "import_json", SOURCE_TYPE_JSON_IMPORT)
    result = ingest_records(db, source, records, origin="import_json")
    result.errors = parse_errors + result.errors
    rejected_total = len(parse_errors) + result.rejected

    analyzed_count = 0
    if result.sample_ids:
        opinions = opinions_by_ids(db, result.sample_ids)
        analyzed = analyze_batch(db, opinions)
        analyzed_count = sum(1 for r in analyzed if r.status == "success")

    record_audit(
        db,
        actor=user,
        action="import.json",
        target_type="import_batch",
        target_id=source_name,
        result="success" if rejected_total == 0 and result.duplicate == 0 else "partial",
        detail={
            "source": source_name,
            "accepted": result.accepted,
            "rejected": rejected_total,
            "duplicate": result.duplicate,
            "analyzed": analyzed_count,
        },
        ip_address=ip,
    )
    db.commit()
    return ImportResultOut(
        format="json",
        accepted=result.accepted,
        rejected=rejected_total,
        duplicate=result.duplicate,
        errors=result.errors,
        sample_ids=result.sample_ids,
        message=f"已接收 {result.accepted} 条,拒绝 {rejected_total} 条,重复 {result.duplicate} 条",
    )


@router.post("/demo", response_model=ImportResultOut)
def import_demo(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_require_importer),
) -> ImportResultOut:
    """Load the bundled demo CSV/JSON samples - used by the demo happy path."""
    ip = get_client_ip(request)
    base = Path(__file__).resolve().parent.parent.parent / "static" / "demo"
    csv_path = base / "sample_opinions.csv"
    json_path = base / "sample_opinions.json"

    csv_text = csv_path.read_text(encoding="utf-8")
    json_text = json_path.read_text(encoding="utf-8")

    csv_records, csv_errors = parse_csv(csv_text)
    json_records, json_errors = parse_json(json_text)

    csv_source = _load_import_source(db, "import_csv", SOURCE_TYPE_CSV)
    json_source = _load_import_source(db, "import_json", SOURCE_TYPE_JSON_IMPORT)
    csv_result = ingest_records(db, csv_source, csv_records, origin="import_demo")
    json_result = ingest_records(db, json_source, json_records, origin="import_demo")
    csv_result.errors = csv_errors + csv_result.errors
    json_result.errors = json_errors + json_result.errors

    sample_ids = csv_result.sample_ids + json_result.sample_ids
    analyzed_count = 0
    if sample_ids:
        opinions = opinions_by_ids(db, sample_ids)
        analyzed = analyze_batch(db, opinions)
        analyzed_count = sum(1 for r in analyzed if r.status == "success")

    total = IngestionResult(
        accepted=csv_result.accepted + json_result.accepted,
        rejected=csv_result.rejected + json_result.rejected,
        duplicate=csv_result.duplicate + json_result.duplicate,
        errors=csv_result.errors + json_result.errors,
        sample_ids=csv_result.sample_ids + json_result.sample_ids,
    )

    record_audit(
        db,
        actor=user,
        action="import.demo",
        target_type="import_batch",
        target_id="bundled-demo",
        result="success" if total.rejected == 0 and not total.errors else "partial",
        detail={
            "csv_accepted": csv_result.accepted,
            "json_accepted": json_result.accepted,
            "csv_duplicate": csv_result.duplicate,
            "json_duplicate": json_result.duplicate,
            "analyzed": analyzed_count,
        },
        ip_address=ip,
    )
    db.commit()
    return ImportResultOut(
        format="demo",
        accepted=total.accepted,
        rejected=total.rejected,
        duplicate=total.duplicate,
        errors=total.errors,
        sample_ids=total.sample_ids,
        message=f"演示数据已加载:CSV {csv_result.accepted} 条,JSON {json_result.accepted} 条,重复 {total.duplicate} 条",
    )
