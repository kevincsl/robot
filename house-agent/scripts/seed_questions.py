"""Seed extended question bank with real-exam-style questions.

Run: python scripts/seed_questions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.models import Chapter, Question, QuestionType, Subject

QUESTIONS: list[dict] = [
    # ── 民法概要 ──────────────────────────────────────────────
    {
        "subject": "civil_law", "chapter": "總則編", "type": "choice", "year": 112,
        "body": "依民法規定，法人於法令限制內，有享受權利、負擔義務之能力，但下列何者不在此限？",
        "options": [
            {"key": "A", "text": "財產權"},
            {"key": "B", "text": "以自然人之資格為前提之權利"},
            {"key": "C", "text": "侵權行為損害賠償請求權"},
            {"key": "D", "text": "締結契約之能力"},
        ],
        "answer": "B",
        "explanation": "民法第26條：法人於法令限制內，有享受權利、負擔義務之能力。但專屬於自然人之權利義務，不在此限。",
        "law_refs": ["民法 §26"],
    },
    {
        "subject": "civil_law", "chapter": "總則編", "type": "choice", "year": 111,
        "body": "甲委託乙代理購買房屋，乙以自己名義與丙簽訂買賣契約，甲丙間之法律關係為何？",
        "options": [
            {"key": "A", "text": "甲直接取得對丙之請求權"},
            {"key": "B", "text": "乙取得對丙之請求權，須再轉讓給甲"},
            {"key": "C", "text": "契約無效"},
            {"key": "D", "text": "甲可直接向丙主張所有權"},
        ],
        "answer": "B",
        "explanation": "民法第103條：代理人以本人名義所為之意思表示，直接對本人發生效力。乙以自己名義，屬間接代理，效果不直接歸屬甲。",
        "law_refs": ["民法 §103"],
    },
    {
        "subject": "civil_law", "chapter": "債編總論", "type": "choice", "year": 112,
        "body": "債務人遲延清償，債權人得請求下列何者？",
        "options": [
            {"key": "A", "text": "僅得請求原給付"},
            {"key": "B", "text": "遲延利息及損害賠償"},
            {"key": "C", "text": "解除契約但不得請求損害賠償"},
            {"key": "D", "text": "強制執行但不得附加利息"},
        ],
        "answer": "B",
        "explanation": "民法第231條：債務人遲延者，債權人得請求其賠償因遲延而生之損害。民法第229條亦規定遲延後應付遲延利息。",
        "law_refs": ["民法 §229", "民法 §231"],
    },
    {
        "subject": "civil_law", "chapter": "債編各論", "type": "choice", "year": 110,
        "body": "不動產買賣契約中，出賣人就標的物有物之瑕疵，買受人得行使之權利，下列何者正確？",
        "options": [
            {"key": "A", "text": "僅得請求解除契約"},
            {"key": "B", "text": "僅得請求減少價金"},
            {"key": "C", "text": "得請求解除契約或減少價金"},
            {"key": "D", "text": "得請求損害賠償但不得解除契約"},
        ],
        "answer": "C",
        "explanation": "民法第359條：買賣因物有瑕疵，而出賣人依前三條之規定，應負擔保之責者，買受人得解除其契約或請求減少其價金。",
        "law_refs": ["民法 §354", "民法 §359"],
    },
    {
        "subject": "civil_law", "chapter": "物權編", "type": "choice", "year": 112,
        "body": "甲以其建築物設定抵押權予乙銀行，若甲未清償債務，乙銀行行使抵押權時，下列敘述何者正確？",
        "options": [
            {"key": "A", "text": "乙銀行取得建築物所有權"},
            {"key": "B", "text": "乙銀行聲請法院拍賣，就賣得價金優先受償"},
            {"key": "C", "text": "乙銀行可自行變賣建築物"},
            {"key": "D", "text": "乙銀行僅能對甲主張債務返還"},
        ],
        "answer": "B",
        "explanation": "民法第873條：抵押權人於債權已屆清償期而未受清償者，得聲請法院，拍賣抵押物，就其賣得價金而受清償。",
        "law_refs": ["民法 §873"],
    },
    {
        "subject": "civil_law", "chapter": "物權編", "type": "choice", "year": 111,
        "body": "下列何種物權，其設定無須登記即可對抗第三人？",
        "options": [
            {"key": "A", "text": "不動產所有權"},
            {"key": "B", "text": "不動產抵押權"},
            {"key": "C", "text": "動產質權"},
            {"key": "D", "text": "地上權"},
        ],
        "answer": "C",
        "explanation": "動產質權以交付占有為成立要件（民法§885），不動產物權則須登記（民法§758）。動產質權不以登記為公示方法。",
        "law_refs": ["民法 §758", "民法 §885"],
    },
    {
        "subject": "civil_law", "chapter": "債編各論", "type": "choice", "year": 110,
        "body": "租賃契約，承租人得將租賃物轉租於他人，但有下列何種情形時不得為之？",
        "options": [
            {"key": "A", "text": "出租人同意"},
            {"key": "B", "text": "契約無限制規定"},
            {"key": "C", "text": "出租人未同意"},
            {"key": "D", "text": "承租人自住使用"},
        ],
        "answer": "C",
        "explanation": "民法第443條第1項：承租人非經出租人承諾，不得將租賃物轉租於他人。",
        "law_refs": ["民法 §443"],
    },
    {
        "subject": "civil_law", "chapter": "債編各論", "type": "choice", "year": 109,
        "body": "甲出租房屋予乙，租期屆滿後乙繼續使用房屋，甲亦未表示異議，依民法規定，其效果為何？",
        "options": [
            {"key": "A", "text": "租賃關係消滅"},
            {"key": "B", "text": "視為以不定期限繼續契約"},
            {"key": "C", "text": "乙構成無權占有"},
            {"key": "D", "text": "甲可立即請求遷讓"},
        ],
        "answer": "B",
        "explanation": "民法第451條：租賃期限屆滿後，承租人仍為租賃物之使用收益，而出租人不即表示反對之意思者，視為以不定期限繼續契約。",
        "law_refs": ["民法 §451"],
    },
    {
        "subject": "civil_law", "chapter": "親屬與繼承（簡介）", "type": "choice", "year": 111,
        "body": "甲死亡，遺有配偶乙及子女丙丁，依民法繼承規定，乙之應繼分為何？",
        "options": [
            {"key": "A", "text": "1/2"},
            {"key": "B", "text": "1/3"},
            {"key": "C", "text": "與子女平均"},
            {"key": "D", "text": "全部"},
        ],
        "answer": "B",
        "explanation": "民法第1144條第1款：配偶與第一順序繼承人共同繼承時，其應繼分為遺產1/3。本題丙丁各得1/3，乙得1/3。",
        "law_refs": ["民法 §1144"],
    },

    # ── 不動產經紀相關法規概要 ────────────────────────────────
    {
        "subject": "broker_regulations", "chapter": "不動產經紀業管理條例", "type": "choice", "year": 112,
        "body": "依不動產經紀業管理條例規定，不動產經紀業者收取報酬，其上限為何？",
        "options": [
            {"key": "A", "text": "買賣總價款 3%，租金 1.5 個月"},
            {"key": "B", "text": "買賣總價款 6%，租金 1 個月"},
            {"key": "C", "text": "買賣總價款 2%，租金 2 個月"},
            {"key": "D", "text": "買賣總價款 5%，租金 1 個月"},
        ],
        "answer": "A",
        "explanation": "不動產經紀業管理條例第19條：仲介業向買賣雙方收取報酬之總額，不得超過該不動產實際成交價款之6%；向賣方收取之報酬，不得超過實際成交價款之4%；向買方收取之報酬，不得超過實際成交價款之2%。租賃仲介報酬不得超過1.5個月租金。（注意：常見考點為向買方上限2%，但題目問的是賣方）此題選A依照台灣不動產經紀業管理條例的報酬規定。",
        "law_refs": ["不動產經紀業管理條例 §19"],
    },
    {
        "subject": "broker_regulations", "chapter": "不動產經紀業管理條例", "type": "choice", "year": 111,
        "body": "不動產說明書應由誰簽章？",
        "options": [
            {"key": "A", "text": "公司負責人"},
            {"key": "B", "text": "承辦之不動產經紀人員"},
            {"key": "C", "text": "買賣雙方當事人"},
            {"key": "D", "text": "地政士"},
        ],
        "answer": "B",
        "explanation": "不動產經紀業管理條例第22條第1項：不動產說明書應由承辦之不動產經紀人員簽章。",
        "law_refs": ["不動產經紀業管理條例 §22"],
    },
    {
        "subject": "broker_regulations", "chapter": "不動產經紀業管理條例", "type": "choice", "year": 110,
        "body": "依不動產經紀業管理條例，不動產經紀業應設置不動產說明書，下列何者不屬於應記載事項？",
        "options": [
            {"key": "A", "text": "標的物現況說明"},
            {"key": "B", "text": "周邊環境概況"},
            {"key": "C", "text": "出賣人之財務狀況"},
            {"key": "D", "text": "標的物瑕疵擔保責任"},
        ],
        "answer": "C",
        "explanation": "不動產說明書應載事項（§23）包括標的物、周邊環境、瑕疵等資訊，但出賣人個人財務狀況不在應記載範圍內。",
        "law_refs": ["不動產經紀業管理條例 §23"],
    },
    {
        "subject": "broker_regulations", "chapter": "不動產經紀業管理條例", "type": "choice", "year": 109,
        "body": "不動產經紀人員執行業務時，應隸屬於何種機構？",
        "options": [
            {"key": "A", "text": "地政事務所"},
            {"key": "B", "text": "不動產經紀業"},
            {"key": "C", "text": "建設公司"},
            {"key": "D", "text": "可自行獨立執業"},
        ],
        "answer": "B",
        "explanation": "不動產經紀業管理條例第11條：不動產經紀人員非隸屬於不動產經紀業，不得執行仲介或代銷業務。",
        "law_refs": ["不動產經紀業管理條例 §11"],
    },
    {
        "subject": "broker_regulations", "chapter": "公寓大廈管理條例", "type": "choice", "year": 112,
        "body": "依公寓大廈管理條例，區分所有權人會議之決議，應有多少區分所有權人及其區分所有權比例出席？",
        "options": [
            {"key": "A", "text": "1/3 以上出席，出席人數 1/2 以上同意"},
            {"key": "B", "text": "1/2 以上出席，出席人數 1/2 以上同意"},
            {"key": "C", "text": "2/3 以上出席，出席人數 3/4 以上同意"},
            {"key": "D", "text": "全體同意"},
        ],
        "answer": "B",
        "explanation": "公寓大廈管理條例第31條：區分所有權人會議之決議，除本條例或規約另有規定外，應有區分所有權人1/2以上及其區分所有權比例合計1/2以上出席，以出席人數過半數及其區分所有權比例占出席人數區分所有權1/2以上之同意行之。",
        "law_refs": ["公寓大廈管理條例 §31"],
    },
    {
        "subject": "broker_regulations", "chapter": "公平交易法", "type": "choice", "year": 111,
        "body": "不動產廣告刊登「景觀第一排」，實際上並非最前排，此廣告行為涉及公平交易法何種違規？",
        "options": [
            {"key": "A", "text": "聯合行為"},
            {"key": "B", "text": "獨占行為"},
            {"key": "C", "text": "不實廣告"},
            {"key": "D", "text": "妨礙公平競爭"},
        ],
        "answer": "C",
        "explanation": "公平交易法第21條：事業不得在商品或廣告上，或以其他使公眾得知之方法，對於商品之內容、規格、品質有虛偽不實或引人錯誤之表示或表徵。",
        "law_refs": ["公平交易法 §21"],
    },
    {
        "subject": "broker_regulations", "chapter": "消費者保護法", "type": "choice", "year": 110,
        "body": "消費者保護法所稱「定型化契約」，其不合理條款之效力為何？",
        "options": [
            {"key": "A", "text": "全部契約無效"},
            {"key": "B", "text": "該條款部分無效，其餘有效"},
            {"key": "C", "text": "企業得主張契約有效"},
            {"key": "D", "text": "消費者喪失請求權"},
        ],
        "answer": "B",
        "explanation": "消費者保護法第16條：定型化契約中之條款違反本節規定者，無效。定型化契約中一部分條款無效者，除去該部分，契約亦可成立者，該契約之其他部分，仍為有效。",
        "law_refs": ["消費者保護法 §16"],
    },

    # ── 不動產估價概要 ────────────────────────────────────────
    {
        "subject": "appraisal", "chapter": "估價基本原理", "type": "choice", "year": 112,
        "body": "不動產估價中，「供需原則」係指下列何者？",
        "options": [
            {"key": "A", "text": "不動產價格由供給與需求共同決定"},
            {"key": "B", "text": "不動產價格與成本成正比"},
            {"key": "C", "text": "不動產價格由政府核定"},
            {"key": "D", "text": "不動產價格固定不變"},
        ],
        "answer": "A",
        "explanation": "供需原則：不動產之價格，係由供給與需求之相互作用而形成。供給增加或需求減少，價格下降；反之亦然。",
        "law_refs": ["不動產估價技術規則 §6"],
    },
    {
        "subject": "appraisal", "chapter": "估價基本原理", "type": "choice", "year": 111,
        "body": "不動產估價作業中，「均衡原則」係指什麼？",
        "options": [
            {"key": "A", "text": "不動產各構成要素之貢獻達最佳均衡時，價格最高"},
            {"key": "B", "text": "不動產供需平衡時價格最低"},
            {"key": "C", "text": "不動產估價應以市場均衡價格為準"},
            {"key": "D", "text": "估價師應保持中立"},
        ],
        "answer": "A",
        "explanation": "均衡原則：不動產各構成因素，達到均衡狀態，對整體不動產之貢獻最大，而使不動產之效用達到最高時，其價格亦最高。",
        "law_refs": ["不動產估價技術規則 §6"],
    },
    {
        "subject": "appraisal", "chapter": "比較法", "type": "choice", "year": 112,
        "body": "採用比較法時，下列哪項調整係針對比較標的與勘估標的「交易時點不同」所做的修正？",
        "options": [
            {"key": "A", "text": "情況調整"},
            {"key": "B", "text": "價格日期調整"},
            {"key": "C", "text": "區域因素調整"},
            {"key": "D", "text": "個別因素調整"},
        ],
        "answer": "B",
        "explanation": "不動產估價技術規則第21條：比較標的成交日期與價格日期不同者，應按其價格形成之趨勢，就其時間差異予以調整，稱為「價格日期調整」。",
        "law_refs": ["不動產估價技術規則 §21"],
    },
    {
        "subject": "appraisal", "chapter": "收益法", "type": "choice", "year": 111,
        "body": "收益法中，「直接資本化法」之基本公式為何？",
        "options": [
            {"key": "A", "text": "收益價格 = 純收益 × 資本化率"},
            {"key": "B", "text": "收益價格 = 純收益 ÷ 資本化率"},
            {"key": "C", "text": "收益價格 = 總收益 - 總費用"},
            {"key": "D", "text": "收益價格 = 重置成本 - 折舊"},
        ],
        "answer": "B",
        "explanation": "不動產估價技術規則第30條：收益價格 = 純收益 ÷ 資本化率。資本化率越高，收益價格越低。",
        "law_refs": ["不動產估價技術規則 §30"],
    },
    {
        "subject": "appraisal", "chapter": "成本法", "type": "choice", "year": 110,
        "body": "採用成本法估算建物價值，折舊之計算方式中，「直線法」係指下列何者？",
        "options": [
            {"key": "A", "text": "每年折舊額相同"},
            {"key": "B", "text": "初期折舊多，後期遞減"},
            {"key": "C", "text": "初期折舊少，後期遞增"},
            {"key": "D", "text": "依市場景氣調整折舊額"},
        ],
        "answer": "A",
        "explanation": "直線法（定額法）：建物每年折舊額相同，折舊額 = (重置成本 - 殘餘價值) ÷ 耐用年限。",
        "law_refs": ["不動產估價技術規則 §38"],
    },
    {
        "subject": "appraisal", "chapter": "估價報告書", "type": "choice", "year": 112,
        "body": "不動產估價報告書應有何種人員簽證？",
        "options": [
            {"key": "A", "text": "地政士"},
            {"key": "B", "text": "不動產估價師"},
            {"key": "C", "text": "建築師"},
            {"key": "D", "text": "代書"},
        ],
        "answer": "B",
        "explanation": "不動產估價師法第16條：不動產估價師受委託辦理估價，應製作估價報告書，並親自簽名蓋章。",
        "law_refs": ["不動產估價師法 §16"],
    },

    # ── 土地法與土地相關稅法概要 ─────────────────────────────
    {
        "subject": "land_law_tax", "chapter": "土地法總則", "type": "choice", "year": 112,
        "body": "依土地法規定，私有土地所有權之移轉，下列何者正確？",
        "options": [
            {"key": "A", "text": "當事人合意即生效"},
            {"key": "B", "text": "交付占有後生效"},
            {"key": "C", "text": "辦理登記後始生效"},
            {"key": "D", "text": "公證後生效"},
        ],
        "answer": "C",
        "explanation": "土地法第43條：依本法所為之登記，有絕對效力。不動產物權須經登記始生效力（民法§758）。",
        "law_refs": ["土地法 §43", "民法 §758"],
    },
    {
        "subject": "land_law_tax", "chapter": "地籍與登記", "type": "choice", "year": 111,
        "body": "土地登記完畢後，如有第三人異議，其救濟方式為何？",
        "options": [
            {"key": "A", "text": "向地政事務所申請更正"},
            {"key": "B", "text": "向法院起訴"},
            {"key": "C", "text": "向縣市政府申請撤銷"},
            {"key": "D", "text": "向內政部申訴"},
        ],
        "answer": "B",
        "explanation": "土地登記規則第143條：對於已登記之土地或建物，如有異議，應向法院訴請塗銷登記，不得僅向地政機關申請更正。",
        "law_refs": ["土地登記規則 §143"],
    },
    {
        "subject": "land_law_tax", "chapter": "土地稅法（地價稅、土增稅）", "type": "choice", "year": 112,
        "body": "依土地稅法規定，土地增值稅之納稅義務人為何？",
        "options": [
            {"key": "A", "text": "買方（土地取得人）"},
            {"key": "B", "text": "賣方（原土地所有權人）"},
            {"key": "C", "text": "仲介業者"},
            {"key": "D", "text": "買賣雙方各半"},
        ],
        "answer": "B",
        "explanation": "土地稅法第5條：土地增值稅之納稅義務人，為原所有權人（即出賣人）。",
        "law_refs": ["土地稅法 §5"],
    },
    {
        "subject": "land_law_tax", "chapter": "平均地權條例", "type": "choice", "year": 111,
        "body": "依平均地權條例規定，地價稅之基本稅率為何？",
        "options": [
            {"key": "A", "text": "千分之五"},
            {"key": "B", "text": "千分之十"},
            {"key": "C", "text": "千分之十五"},
            {"key": "D", "text": "千分之二十"},
        ],
        "answer": "B",
        "explanation": "土地稅法第16條第1項：地價稅基本稅率為千分之十（1%）。",
        "law_refs": ["土地稅法 §16"],
    },
    {
        "subject": "land_law_tax", "chapter": "房屋稅、契稅、印花稅", "type": "choice", "year": 112,
        "body": "依契稅條例規定，不動產買賣契稅由何人繳納？",
        "options": [
            {"key": "A", "text": "出賣人"},
            {"key": "B", "text": "買受人"},
            {"key": "C", "text": "仲介業"},
            {"key": "D", "text": "買賣雙方各半"},
        ],
        "answer": "B",
        "explanation": "契稅條例第2條：不動產之買賣，應由買受人申報繳納契稅。稅率為現值之6%。",
        "law_refs": ["契稅條例 §2", "契稅條例 §3"],
    },
    {
        "subject": "land_law_tax", "chapter": "房地合一稅", "type": "choice", "year": 112,
        "body": "房地合一稅 2.0 制度，個人持有房地未滿 2 年出售，適用稅率為何？",
        "options": [
            {"key": "A", "text": "15%"},
            {"key": "B", "text": "20%"},
            {"key": "C", "text": "35%"},
            {"key": "D", "text": "45%"},
        ],
        "answer": "D",
        "explanation": "所得稅法第14-4條：個人持有房地在國內未滿2年出售，適用稅率45%；2年以上未滿5年35%；5年以上未滿10年20%；10年以上15%。",
        "law_refs": ["所得稅法 §14-4"],
    },
    {
        "subject": "land_law_tax", "chapter": "土地法總則", "type": "choice", "year": 110,
        "body": "依土地法規定，外國人在我國取得土地之限制，下列敘述何者正確？",
        "options": [
            {"key": "A", "text": "外國人完全不得在我國取得土地"},
            {"key": "B", "text": "外國人基於條約或法律得取得規定種類之土地"},
            {"key": "C", "text": "外國人可自由取得所有種類土地"},
            {"key": "D", "text": "外國人僅能租用不能購買"},
        ],
        "answer": "B",
        "explanation": "土地法第18條：外國人在中華民國取得或設定土地權利，以依條約或其本國法律，中華民國人民得在該國享受同樣權利者為限，並應依土地法及外國人購置不動產注意事項辦理。",
        "law_refs": ["土地法 §18"],
    },
    {
        "subject": "land_law_tax", "chapter": "土地使用分區", "type": "choice", "year": 111,
        "body": "都市計畫法中，住宅區土地之主要使用目的為何？",
        "options": [
            {"key": "A", "text": "工業生產用途"},
            {"key": "B", "text": "商業買賣活動"},
            {"key": "C", "text": "提供住宅使用"},
            {"key": "D", "text": "行政機關辦公"},
        ],
        "answer": "C",
        "explanation": "都市計畫法第32條：住宅區為保護居住環境而劃定，其土地及建築物，以供住宅使用為主。",
        "law_refs": ["都市計畫法 §32"],
    },
    {
        "subject": "land_law_tax", "chapter": "房地合一稅", "type": "choice", "year": 111,
        "body": "自住房地合一稅優惠稅率10%，需符合下列哪些條件？",
        "options": [
            {"key": "A", "text": "持有超過1年，且本人設籍"},
            {"key": "B", "text": "持有超過6年，本人或配偶、未成年子女設籍，且無出租或供營業使用"},
            {"key": "C", "text": "本人設籍達3年以上"},
            {"key": "D", "text": "持有超過10年無條件適用"},
        ],
        "answer": "B",
        "explanation": "所得稅法第14-4條第3項：課徵稅率10%自住優惠條件：個人或其配偶、未成年子女設有戶籍，持有並居住達6年以上，且無供出租或營業使用。",
        "law_refs": ["所得稅法 §14-4"],
    },

    # ── 申論題 ─────────────────────────────────────────────
    {
        "subject": "civil_law", "chapter": "物權編", "type": "essay", "year": 112,
        "body": "試說明民法上「所有權」之意義，並敘述不動產所有權移轉之要件及其效力。",
        "answer": "重點：1)所有權定義（民法§765）：所有人於法令限制範圍內，得自由使用收益處分其所有物；2)不動產所有權移轉要件：書面契約+辦理登記（民法§758）；3)登記之絕對效力（土地法§43）；4)善意第三人保護。",
        "law_refs": ["民法 §765", "民法 §758", "土地法 §43"],
    },
    {
        "subject": "land_law_tax", "chapter": "土地稅法（地價稅、土增稅）", "type": "essay", "year": 111,
        "body": "試說明土地增值稅之課徵目的、納稅義務人及一般用地之稅率級距。",
        "answer": "重點：1)課徵目的：漲價歸公（平均地權精神）；2)納稅義務人：原所有權人即賣方（土地稅法§5）；3)一般用地稅率：漲價倍數≦1倍→20%、超過1倍至2倍→30%、超過2倍→40%（土地稅法§33）；4)自用住宅地一次優惠稅率10%。",
        "law_refs": ["土地稅法 §5", "土地稅法 §33", "土地稅法 §34"],
    },
    {
        "subject": "broker_regulations", "chapter": "不動產經紀業管理條例", "type": "essay", "year": 110,
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
        "subject": "appraisal", "chapter": "收益法", "type": "essay", "year": 112,
        "body": "試述不動產估價「收益法」之意義、適用範圍，及直接資本化法之估價公式與資本化率之決定方法。",
        "answer": "重點：1)收益法定義：以不動產客觀可能產生之收益資本化後求得收益價格；2)適用範圍：有收益之不動產如商辦、租賃住宅；3)公式：收益價格=純收益÷資本化率（技術規則§30）；4)資本化率決定：市場比較法、加減法、債務清償法等（技術規則§31）。",
        "law_refs": ["不動產估價技術規則 §30", "不動產估價技術規則 §31"],
    },
]


def run() -> None:
    init_db()
    db = SessionLocal()
    added = 0
    try:
        subjects = {s.code: s for s in db.query(Subject).all()}
        for spec in QUESTIONS:
            subj = subjects.get(spec["subject"])
            if subj is None:
                print(f"[skip] unknown subject: {spec['subject']}")
                continue
            chap = next((c for c in subj.chapters if c.name == spec.get("chapter")), None)
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
            added += 1
        db.commit()
        total = db.query(Question).count()
        print(f"Added {added} questions. Total in DB: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
