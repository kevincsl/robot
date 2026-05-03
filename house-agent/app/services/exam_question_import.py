"""Parse downloaded exam PDFs into question records with law references."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import fitz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExamPaper, ExamPaperSubject, Law, Question, QuestionType, Subject
from app.services.law_links import backfill_question_law_refs
from app.services.question_text import sanitize_question_text

# Some downloaded PDFs use private-use glyphs for option bullets. Keep the parser
# tolerant by accepting both the private-use markers and common A/B/C/D forms.
OPTION_MARKERS = {
    "\ue18c": "A",
    "\ue18d": "B",
    "\ue18e": "C",
    "\ue18f": "D",
    "A.": "A",
    "B.": "B",
    "C.": "C",
    "D.": "D",
    "A、": "A",
    "B、": "B",
    "C、": "C",
    "D、": "D",
    "A ": "A",
    "B ": "B",
    "C ": "C",
    "D ": "D",
}
ESSAY_START_RE = re.compile(r"^([一二三四五六七八九十]+、)\s*(.*)")
CHOICE_START_INLINE_RE = re.compile(r"^(\d+)\s+(.+)")
CHOICE_NUMBER_RE = re.compile(r"^\d+$")
ARTICLE_REF_RE = re.compile(r"第\s*(\d+(?:-\d+)?)\s*條")
ANSWER_COUNT_RE = re.compile(r"(?:單選題數|題\s*數)[：:]\s*(\d+)\s*題")

SUBJECT_CODE_RULES = [
    ("民法", "civil_law"),
    ("不動產經紀", "broker_regulations"),
    ("估價", "appraisal"),
    ("土地", "land_law_tax"),
    ("稅", "land_law_tax"),
]

SUBJECT_FALLBACK_LAWS = {
    "civil_law": ["民法"],
    "broker_regulations": ["不動產經紀業管理條例", "公平交易法", "消費者保護法", "公寓大廈管理條例"],
    "appraisal": ["不動產估價師法", "不動產估價技術規則"],
    "land_law_tax": ["土地法", "土地登記規則", "平均地權條例", "土地稅法", "所得稅法", "契稅條例", "都市計畫法"],
}

SINGLE_LAW_SUBJECT = {
    "civil_law": "民法",
}

HEADER_PREFIXES = ("代號：", "頁次：", "※")
PRIVATE_SKIP_PREFIXES = ("\ue129", "\ue12a", "\ue12b")


@dataclass
class ParsedChoiceQuestion:
    number: int
    stem: str
    options: list[dict[str, str]]


@dataclass
class ParsedEssayQuestion:
    number: int
    body: str


@dataclass
class ParsedPaper:
    essays: list[ParsedEssayQuestion]
    choices: list[ParsedChoiceQuestion]


def _extract_text(path: Path) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def _clean_lines(text: str) -> list[str]:
    raw_lines = [line.strip() for line in text.splitlines()]
    return [line for line in raw_lines if line]


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _parse_question_paper(path: Path) -> ParsedPaper:
    lines = _clean_lines(_extract_text(path))
    essays: list[ParsedEssayQuestion] = []
    choices: list[ParsedChoiceQuestion] = []
    section = "head"
    current_essay: ParsedEssayQuestion | None = None
    current_choice: ParsedChoiceQuestion | None = None
    current_option_key: str | None = None

    def flush_essay() -> None:
        nonlocal current_essay
        if current_essay is not None:
            current_essay.body = re.sub(r"\s+", " ", current_essay.body).strip()
            essays.append(current_essay)
            current_essay = None

    def flush_choice() -> None:
        nonlocal current_choice
        if current_choice is not None:
            current_choice.stem = re.sub(r"\s+", " ", current_choice.stem).strip()
            for option in current_choice.options:
                option["text"] = re.sub(r"\s+", " ", option["text"]).strip()
            choices.append(current_choice)
            current_choice = None

    for line in lines:
        if "甲、申論題部分" in line:
            section = "essay"
            continue
        if "乙、測驗題部分" in line:
            flush_essay()
            section = "choice"
            continue
        if line.startswith(HEADER_PREFIXES) or line.startswith(PRIVATE_SKIP_PREFIXES):
            continue

        if section == "essay":
            match = ESSAY_START_RE.match(line)
            if match:
                flush_essay()
                current_essay = ParsedEssayQuestion(number=len(essays) + 1, body=match.group(2).strip())
                continue
            if current_essay is not None:
                current_essay.body += " " + line
            continue

        if section == "choice":
            inline = CHOICE_START_INLINE_RE.match(line)
            if CHOICE_NUMBER_RE.fullmatch(line):
                flush_choice()
                current_choice = ParsedChoiceQuestion(number=int(line), stem="", options=[])
                current_option_key = None
                continue
            if inline:
                flush_choice()
                current_choice = ParsedChoiceQuestion(number=int(inline.group(1)), stem=inline.group(2).strip(), options=[])
                current_option_key = None
                continue

            marker = next((symbol for symbol in OPTION_MARKERS if line.startswith(symbol)), None)
            if marker and current_choice is not None:
                current_option_key = OPTION_MARKERS[marker]
                current_choice.options.append({"key": current_option_key, "text": line[len(marker):].strip()})
                continue

            if current_choice is not None:
                if current_option_key and current_choice.options:
                    current_choice.options[-1]["text"] += " " + line
                else:
                    current_choice.stem += " " + line

    flush_essay()
    flush_choice()
    return ParsedPaper(essays=essays, choices=choices)


def _parse_answer_pdf(path: Path) -> tuple[dict[int, str], str | None]:
    text = _extract_text(path)
    count_match = ANSWER_COUNT_RE.search(text)
    if not count_match:
        return {}, None

    question_count = int(count_match.group(1))
    last_marker = max(text.rfind("第100題"), text.rfind(f"第{question_count}題"))
    if last_marker < 0:
        last_marker = text.find("標準答案")

    stop_candidates = [
        idx
        for idx in [
            text.find("複選題數"),
            text.find("備"),
            text.find("標準答案："),
        ]
        if idx > last_marker
    ]
    stop_at = min(stop_candidates) if stop_candidates else len(text)
    answer_zone = text[last_marker:stop_at]
    tokens = re.findall(r"[A-D]", answer_zone)
    answers = {idx: token for idx, token in enumerate(tokens[:question_count], start=1)}

    note = None
    note_match = re.search(r"備\s*註[：:]\s*(.+)", text, re.S)
    if note_match:
        note = re.sub(r"\s+", " ", note_match.group(1)).strip()
    return answers, note


def _classify_subject_files(subject_row: ExamPaperSubject) -> tuple[Path | None, Path | None, str | None]:
    question_file: Path | None = None
    answer_file: Path | None = None
    answer_note: str | None = None

    for file in subject_row.files:
        if not file.local_path:
            continue
        path = Path(file.local_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        if not path.exists():
            continue

        head_text = _extract_text(path)[:800]
        if "標準答案" in head_text:
            if "更正" in head_text:
                _, correction_note = _parse_answer_pdf(path)
                if correction_note:
                    answer_note = correction_note
            elif answer_file is None:
                answer_file = path
            continue
        if "試題" in head_text and question_file is None:
            question_file = path

    return question_file, answer_file, answer_note


def _subject_code_for_name(subject_name: str) -> str | None:
    for token, code in SUBJECT_CODE_RULES:
        if token in subject_name:
            return code
    return None


def _infer_law_refs(text: str, subject_code: str | None, laws: list[Law]) -> list[str]:
    refs: list[str] = []
    normalized = re.sub(r"\s+", "", _normalize_text(text))

    for law in laws:
        compact_name = re.sub(r"\s+", "", _normalize_text(law.name))
        if compact_name not in normalized:
            continue
        article_hits = []
        for match in re.finditer(re.escape(compact_name), normalized):
            window = normalized[max(0, match.start() - 24): match.end() + 48]
            article_hits.extend(ARTICLE_REF_RE.findall(window))
        if article_hits:
            for article_no in article_hits:
                label = f"{law.name} 第{article_no}條"
                if label not in refs:
                    refs.append(label)
        elif law.name not in refs:
            refs.append(law.name)

    if refs:
        return refs

    single_law_name = SINGLE_LAW_SUBJECT.get(subject_code or "")
    if single_law_name:
        article_hits = ARTICLE_REF_RE.findall(_normalize_text(text))
        for article_no in article_hits:
            label = f"{single_law_name} 第{article_no}條"
            if label not in refs:
                refs.append(label)
        if refs:
            return refs

    for law_name in SUBJECT_FALLBACK_LAWS.get(subject_code or "", []):
        if law_name not in refs:
            refs.append(law_name)
    return refs


def import_exam_questions(db: Session, *, source_prefix: str = "moex:") -> dict[str, int]:
    papers = list(
        db.execute(
            select(ExamPaper).order_by(ExamPaper.year, ExamPaper.exam_code).options()
        ).scalars()
    )
    subject_map = {item.code: item.id for item in db.execute(select(Subject)).scalars()}
    laws = list(db.execute(select(Law)).scalars())

    existing = db.query(Question).filter(Question.source.like(f"{source_prefix}%")).all()
    for question in existing:
        db.delete(question)
    db.commit()

    stats = {"papers": 0, "subjects": 0, "essays": 0, "choices": 0}
    created_questions: list[Question] = []

    for paper in papers:
        stats["papers"] += 1
        for subject_row in paper.subjects:
            stats["subjects"] += 1
            subject_code = _subject_code_for_name(subject_row.subject)
            subject_id = subject_map.get(subject_code or "")
            if subject_id is None:
                continue

            question_file, answer_file, answer_note = _classify_subject_files(subject_row)
            if question_file is None:
                continue

            parsed = _parse_question_paper(question_file)
            answers, _ = _parse_answer_pdf(answer_file) if answer_file else ({}, None)
            clean_answer_note = sanitize_question_text(answer_note)

            for essay in parsed.essays:
                essay_body = sanitize_question_text(essay.body) or ""
                q = Question(
                    subject_id=subject_id,
                    chapter_id=None,
                    type=QuestionType.ESSAY,
                    year=paper.roc_year,
                    source=f"{source_prefix}{paper.bundle_id}:subject:{subject_row.sort_order}:essay:{essay.number}",
                    body=essay_body,
                    options=None,
                    answer=None,
                    explanation=clean_answer_note,
                    law_refs=_infer_law_refs(essay_body, subject_code, laws),
                    difficulty=3,
                )
                db.add(q)
                created_questions.append(q)
                stats["essays"] += 1

            for choice in parsed.choices:
                clean_stem = sanitize_question_text(choice.stem) or ""
                clean_options = [
                    {"key": option["key"], "text": sanitize_question_text(option["text"]) or ""}
                    for option in choice.options
                ]
                composed = clean_stem + " " + " ".join(option["text"] for option in clean_options)
                q = Question(
                    subject_id=subject_id,
                    chapter_id=None,
                    type=QuestionType.CHOICE,
                    year=paper.roc_year,
                    source=f"{source_prefix}{paper.bundle_id}:subject:{subject_row.sort_order}:choice:{choice.number}",
                    body=clean_stem,
                    options=clean_options,
                    answer=answers.get(choice.number),
                    explanation=clean_answer_note,
                    law_refs=_infer_law_refs(composed, subject_code, laws),
                    difficulty=3,
                )
                db.add(q)
                created_questions.append(q)
                stats["choices"] += 1

    db.commit()
    backfill_question_law_refs(db, questions=created_questions, source="exam_import", confidence=0.85)
    return stats
