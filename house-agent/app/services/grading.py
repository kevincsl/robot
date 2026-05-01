"""Gemini CLI subprocess wrapper for essay grading."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

GRADING_PROMPT_TEMPLATE = """你是台灣不動產經紀人考試的閱卷老師。請依下列評分維度批改考生申論題。

【題目】
{question}

【參考答案 / 法條重點】
{reference}

【考生作答】
{answer}

請以 JSON 格式回覆（純 JSON，不要加 markdown code fence），結構如下：
{{
  "score": <0-100 整數>,
  "dimensions": {{
    "structure": <0-25>,
    "argument": <0-25>,
    "law_citation": <0-25>,
    "conclusion": <0-25>
  }},
  "strengths": ["..."],
  "weaknesses": ["..."],
  "improved_answer": "建議的改進版本（200-400字）",
  "key_law_refs": ["相關法條"]
}}
"""


@dataclass
class GradingResult:
    score: int
    dimensions: dict
    strengths: list[str]
    weaknesses: list[str]
    improved_answer: str
    key_law_refs: list[str]
    raw: str


def grade_essay(question: str, answer: str, reference: str = "") -> GradingResult:
    prompt = GRADING_PROMPT_TEMPLATE.format(
        question=question.strip(),
        reference=reference.strip() or "（無，請依考試標準與相關法規評分）",
        answer=answer.strip(),
    )
    proc = subprocess.run(
        ["gemini", "-p", prompt],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        raise RuntimeError(f"gemini CLI failed: {proc.stderr}")

    json_text = _extract_json(out)
    data = json.loads(json_text)
    return GradingResult(
        score=int(data.get("score", 0)),
        dimensions=data.get("dimensions", {}),
        strengths=data.get("strengths", []),
        weaknesses=data.get("weaknesses", []),
        improved_answer=data.get("improved_answer", ""),
        key_law_refs=data.get("key_law_refs", []),
        raw=out,
    )


def _extract_json(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    brace = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if brace:
        return brace.group(0)
    return text
