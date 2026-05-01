"""Helpers for syncing and browsing downloaded MOEX exam-paper bundles."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import ExamPaper, ExamPaperFile, ExamPaperSubject

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw" / "exam_papers" / "moex"
BROKER_KEYWORD = "不動產經紀人"
MIN_ROC_YEAR = 91
MAX_ROC_YEAR = 115


@dataclass
class ManifestFile:
    label: str
    href: str
    local_path: str | None
    file_name: str | None


@dataclass
class ManifestItem:
    category: str
    subject: str
    files: list[ManifestFile]


@dataclass
class ManifestBundle:
    bundle_id: str
    year: int
    roc_year: int
    exam_code: str
    exam_name: str
    exam_title: str
    stats: str
    overall_files: list[ManifestFile]
    items: list[ManifestItem]


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_file(spec: dict[str, Any]) -> ManifestFile:
    local_path = spec.get("path")
    file_name = Path(local_path).name if local_path else None
    return ManifestFile(
        label=str(spec.get("kind") or ""),
        href=str(spec.get("href") or ""),
        local_path=str(local_path) if local_path else None,
        file_name=file_name,
    )


def iter_manifest_bundles() -> list[ManifestBundle]:
    if not RAW_DIR.exists():
        return []

    bundles: list[ManifestBundle] = []
    for manifest_path in sorted(RAW_DIR.glob("*/manifest.json"), reverse=True):
        data = _load_manifest(manifest_path)
        bundle_dir = manifest_path.parent
        items = [
            ManifestItem(
                category=str(item.get("category") or ""),
                subject=str(item.get("subject") or ""),
                files=[_as_file(file_spec) for file_spec in item.get("files", [])],
            )
            for item in data.get("items", [])
        ]
        items = [
            item
            for item in items
            if BROKER_KEYWORD in f"{item.category} {item.subject}"
        ]
        if not items:
            continue
        overall_files = [_as_file(item) for item in data.get("overall_links", [])]
        year = int(data.get("year") or 0)
        roc_year = year - 1911 if year else 0
        if roc_year < MIN_ROC_YEAR or roc_year > MAX_ROC_YEAR:
            continue
        bundles.append(
            ManifestBundle(
                bundle_id=bundle_dir.name,
                year=year,
                roc_year=roc_year,
                exam_code=str(data.get("exam_code") or ""),
                exam_name=str(data.get("exam_name") or ""),
                exam_title=str(data.get("exam_title") or ""),
                stats=str(data.get("stats") or ""),
                overall_files=overall_files,
                items=items,
            )
        )

    bundles.sort(key=lambda item: (item.year, item.exam_code), reverse=True)
    return bundles


def _display_source_dir(bundle_id: str) -> str:
    target = (RAW_DIR / bundle_id).resolve()
    try:
        return str(target.relative_to(ROOT))
    except ValueError:
        return str(target)


def sync_exam_paper_index(db: Session) -> dict[str, int]:
    bundles = iter_manifest_bundles()
    seen_bundle_ids = {bundle.bundle_id for bundle in bundles}
    stats = {"bundles_seen": len(bundles), "created": 0, "updated": 0, "deleted": 0}

    existing = {row.bundle_id: row for row in db.execute(select(ExamPaper)).scalars()}

    for bundle in bundles:
        row = existing.get(bundle.bundle_id)
        created = row is None
        if row is None:
            row = ExamPaper(bundle_id=bundle.bundle_id)
            db.add(row)

        row.year = bundle.year
        row.roc_year = bundle.roc_year
        row.exam_code = bundle.exam_code
        row.exam_name = bundle.exam_name
        row.exam_title = bundle.exam_title
        row.stats = bundle.stats
        row.source_dir = _display_source_dir(bundle.bundle_id)

        row.subjects.clear()
        row.files.clear()

        for idx, file in enumerate(bundle.overall_files, start=1):
            row.files.append(
                ExamPaperFile(
                    label=file.label,
                    href=file.href,
                    local_path=file.local_path,
                    file_name=file.file_name,
                    is_overall=True,
                    sort_order=idx,
                )
            )

        for subject_index, item in enumerate(bundle.items, start=1):
            subject_row = ExamPaperSubject(
                category=item.category,
                subject=item.subject,
                sort_order=subject_index,
            )
            for file_index, file in enumerate(item.files, start=1):
                subject_row.files.append(
                    ExamPaperFile(
                        exam_paper=row,
                        label=file.label,
                        href=file.href,
                        local_path=file.local_path,
                        file_name=file.file_name,
                        is_overall=False,
                        sort_order=file_index,
                    )
                )
            row.subjects.append(subject_row)

        stats["created" if created else "updated"] += 1

    stale_stmt = select(ExamPaper)
    if seen_bundle_ids:
        stale_stmt = stale_stmt.where(ExamPaper.bundle_id.not_in(seen_bundle_ids))
    for stale in db.execute(stale_stmt).scalars():
        if stale.bundle_id in seen_bundle_ids:
            continue
        db.delete(stale)
        stats["deleted"] += 1

    db.commit()
    return stats


def query_exam_papers(
    db: Session,
    *,
    roc_year: int | None = None,
    subject_query: str | None = None,
) -> list[ExamPaper]:
    stmt = (
        select(ExamPaper)
        .options(
            selectinload(ExamPaper.files),
            selectinload(ExamPaper.subjects).selectinload(ExamPaperSubject.files),
        )
        .order_by(ExamPaper.year.desc(), ExamPaper.exam_code.desc())
    )

    if roc_year is not None:
        stmt = stmt.where(ExamPaper.roc_year == roc_year)

    text = (subject_query or "").strip()
    if text:
        like = f"%{text}%"
        stmt = (
            stmt.join(ExamPaperSubject, ExamPaperSubject.exam_paper_id == ExamPaper.id)
            .where(
                or_(
                    ExamPaper.exam_title.like(like),
                    ExamPaper.exam_name.like(like),
                    ExamPaperSubject.category.like(like),
                    ExamPaperSubject.subject.like(like),
                )
            )
            .distinct()
        )

    return list(db.execute(stmt).scalars())


def available_roc_years(db: Session) -> list[int]:
    stmt = select(ExamPaper.roc_year).distinct().order_by(ExamPaper.roc_year.desc())
    return [int(value) for value in db.execute(stmt).scalars() if value is not None]


def resolve_bundle_file(bundle_id: str, file_name: str) -> Path | None:
    if "/" in bundle_id or "\\" in bundle_id or "/" in file_name or "\\" in file_name:
        return None
    candidate = (RAW_DIR / bundle_id / file_name).resolve()
    bundle_dir = (RAW_DIR / bundle_id).resolve()
    try:
        candidate.relative_to(bundle_dir)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
