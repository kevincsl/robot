"""Helpers for normalizing imported question text for display and storage."""
from __future__ import annotations

import re
from typing import Any

PRIVATE_REPLACEMENTS = {
    "\ue000": "(1)",
    "\ue001": "(2)",
    "\ue002": "(3)",
    "\ue003": "(4)",
    "\ue004": "(5)",
    "\ue129": "(一)",
    "\ue12a": "(二)",
    "\ue12b": "(三)",
    "\ue18c": "A.",
    "\ue18d": "B.",
    "\ue18e": "C.",
    "\ue18f": "D.",
}

_INLINE_MARKER_RE = re.compile(r"(\(\d\)|\([一二三]\)|[A-D]\.)(?=\S)")


def sanitize_question_text(text: str | None) -> str | None:
    if text is None:
        return None

    cleaned_chars: list[str] = []
    for char in text:
        replacement = PRIVATE_REPLACEMENTS.get(char)
        if replacement is not None:
            cleaned_chars.append(replacement)
            continue
        if 0xE000 <= ord(char) <= 0xF8FF:
            cleaned_chars.append(" ")
            continue
        cleaned_chars.append(char)

    cleaned = "".join(cleaned_chars)
    cleaned = cleaned.replace("\u3000", " ")
    cleaned = _INLINE_MARKER_RE.sub(r"\1 ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    return cleaned.strip()


def sanitize_question_record(question: Any) -> bool:
    changed = False

    body = sanitize_question_text(getattr(question, "body", None))
    if body != getattr(question, "body", None):
        question.body = body
        changed = True

    explanation = sanitize_question_text(getattr(question, "explanation", None))
    if explanation != getattr(question, "explanation", None):
        question.explanation = explanation
        changed = True

    raw_refs = getattr(question, "law_refs", None) or []
    clean_refs = [sanitize_question_text(ref) or "" for ref in raw_refs]
    clean_refs = [ref for ref in clean_refs if ref]
    if clean_refs != raw_refs:
        question.law_refs = clean_refs
        changed = True

    raw_options = getattr(question, "options", None) or []
    clean_options: list[dict[str, Any]] = []
    options_changed = False
    for option in raw_options:
        clean_option = dict(option)
        clean_text = sanitize_question_text(str(clean_option.get("text", ""))) or ""
        if clean_text != clean_option.get("text"):
            clean_option["text"] = clean_text
            options_changed = True
        clean_options.append(clean_option)
    if options_changed:
        question.options = clean_options
        changed = True

    return changed
