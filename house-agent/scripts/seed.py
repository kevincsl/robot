"""Seed initial data: subjects, chapters, sample questions.

Run: python scripts/seed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db
from app.models import Chapter, Question, QuestionType, Subject

SUBJECTS = [
    {
        "code": "civil_law",
        "name": "民法概要",
        "chapters": [
            "總則編", "債編總論", "債編各論", "物權編", "親屬與繼承（簡介）",
        ],
    },
    {
        "code": "broker_regulations",
        "name": "不動產經紀相關法規概要",
        "chapters": [
            "不動產經紀業管理條例", "公平交易法", "消費者保護法", "公寓大廈管理條例",
        ],
    },
    {
        "code": "appraisal",
        "name": "不動產估價概要",
        "chapters": [
            "估價基本原理", "比較法", "收益法", "成本法", "估價報告書",
        ],
    },
    {
        "code": "land_law_tax",
        "name": "土地法與土地相關稅法概要",
        "chapters": [
            "土地法總則", "地籍與登記", "土地使用分區", "平均地權條例",
            "土地稅法（地價稅、土增稅）", "房屋稅、契稅、印花稅", "房地合一稅",
        ],
    },
]

SAMPLE_QUESTIONS = [
    {
        "subject": "civil_law",
        "chapter": "物權編",
        "type": "choice",
        "year": 112,
        "body": "甲將其不動產出賣予乙，於完成所有權移轉登記前，下列敘述何者正確？",
        "options": [
            {"key": "A", "text": "乙已取得所有權"},
            {"key": "B", "text": "乙僅取得債權，須登記後始取得所有權"},
            {"key": "C", "text": "甲乙合意即生物權變動"},
            {"key": "D", "text": "交付占有即生所有權移轉"},
        ],
        "answer": "B",
        "explanation": "民法第758條第1項：不動產物權，依法律行為而取得、設定、喪失及變更者，非經登記，不生效力。",
        "law_refs": ["民法 §758"],
    },
    {
        "subject": "broker_regulations",
        "chapter": "不動產經紀業管理條例",
        "type": "choice",
        "year": 111,
        "body": "依不動產經紀業管理條例規定，經紀人員應於下列何種文件簽章？",
        "options": [
            {"key": "A", "text": "不動產說明書"},
            {"key": "B", "text": "委託銷售契約書"},
            {"key": "C", "text": "要約書或斡旋金收據"},
            {"key": "D", "text": "以上皆是"},
        ],
        "answer": "D",
        "explanation": "不動產經紀業管理條例第22條規定，仲介或代銷之相關文件均須由經紀人員簽章。",
        "law_refs": ["不動產經紀業管理條例 §22"],
    },
    {
        "subject": "broker_regulations",
        "chapter": "不動產經紀業管理條例",
        "type": "essay",
        "year": 110,
        "body": "試述不動產經紀業管理條例對「不動產說明書」之規範，並說明經紀人員之責任。",
        "answer": "重點：1) §23 不動產說明書應記載事項；2) §22 經紀人員簽章責任；3) §26 損害賠償；4) §29 罰則。",
        "law_refs": [
            "不動產經紀業管理條例 §22",
            "不動產經紀業管理條例 §23",
            "不動產經紀業管理條例 §26",
            "不動產經紀業管理條例 §29",
        ],
    },
    {
        "subject": "land_law_tax",
        "chapter": "房地合一稅",
        "type": "choice",
        "year": 112,
        "body": "個人 113 年出售自住房地，持有期間 8 年，依房地合一稅 2.0 規定，適用稅率為何？",
        "options": [
            {"key": "A", "text": "45%"},
            {"key": "B", "text": "35%"},
            {"key": "C", "text": "20%"},
            {"key": "D", "text": "10%（自住優惠）"},
        ],
        "answer": "C",
        "explanation": "持有 5 年以上未滿 10 年適用 20%；自住優惠（10%）須符合本人或配偶、未成年子女設籍且持有並居住滿 6 年等條件。",
        "law_refs": ["所得稅法 §4-4", "§14-4"],
    },
    {
        "subject": "appraisal",
        "chapter": "比較法",
        "type": "choice",
        "year": 111,
        "body": "估價作業中，採用比較法時最關鍵的步驟為何？",
        "options": [
            {"key": "A", "text": "選定具替代性之比較標的並進行情況、價格日期、區域與個別因素之調整"},
            {"key": "B", "text": "計算重置成本後扣除折舊"},
            {"key": "C", "text": "推估未來純收益並以收益資本化率折現"},
            {"key": "D", "text": "以政府公告地價作為唯一依據"},
        ],
        "answer": "A",
        "explanation": "比較法依不動產估價技術規則 §18 起，須蒐集比較標的並進行四大調整。",
        "law_refs": ["不動產估價技術規則 §18-§24"],
    },
]


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        subj_map: dict[str, Subject] = {}
        for spec in SUBJECTS:
            subj = db.query(Subject).filter_by(code=spec["code"]).first()
            if subj is None:
                subj = Subject(code=spec["code"], name=spec["name"])
                db.add(subj)
                db.flush()
            subj_map[spec["code"]] = subj
            existing = {c.name for c in subj.chapters}
            for ch_name in spec["chapters"]:
                if ch_name not in existing:
                    db.add(Chapter(subject_id=subj.id, code=ch_name, name=ch_name))
        db.commit()

        for spec in SAMPLE_QUESTIONS:
            subj = subj_map[spec["subject"]]
            chap = next((c for c in subj.chapters if c.name == spec["chapter"]), None)
            exists = (
                db.query(Question)
                .filter(Question.subject_id == subj.id, Question.body == spec["body"])
                .first()
            )
            if exists:
                continue
            db.add(
                Question(
                    subject_id=subj.id,
                    chapter_id=chap.id if chap else None,
                    type=QuestionType(spec["type"]),
                    year=spec.get("year"),
                    body=spec["body"],
                    options=spec.get("options"),
                    answer=spec.get("answer"),
                    explanation=spec.get("explanation"),
                    law_refs=spec.get("law_refs", []),
                )
            )
        db.commit()
        print(f"Seeded {len(SUBJECTS)} subjects, {len(SAMPLE_QUESTIONS)} sample questions.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
