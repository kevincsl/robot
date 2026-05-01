"""Central law catalog for the real-estate broker exam scope."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LawCatalogEntry:
    code: str
    name: str
    subject_codes: tuple[str, ...]
    scope: str = "core"

    @property
    def source_url(self) -> str:
        return f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={self.code}"


LAW_CATALOG: tuple[LawCatalogEntry, ...] = (
    LawCatalogEntry("B0000001", "民法", ("civil_law",)),
    LawCatalogEntry("D0060066", "不動產經紀業管理條例", ("broker_regulations",)),
    LawCatalogEntry("D0060068", "不動產經紀業管理條例施行細則", ("broker_regulations",), scope="extended"),
    LawCatalogEntry("J0150002", "公平交易法", ("broker_regulations",)),
    LawCatalogEntry("J0170001", "消費者保護法", ("broker_regulations",)),
    LawCatalogEntry("D0070118", "公寓大廈管理條例", ("broker_regulations",), scope="extended"),
    LawCatalogEntry("D0060076", "不動產估價師法", ("appraisal",)),
    LawCatalogEntry("D0060077", "不動產估價技術規則", ("appraisal",)),
    LawCatalogEntry("D0060001", "土地法", ("land_law_tax",)),
    LawCatalogEntry("D0060003", "土地登記規則", ("land_law_tax",)),
    LawCatalogEntry("D0060009", "平均地權條例", ("land_law_tax",)),
    LawCatalogEntry("G0340096", "土地稅法", ("land_law_tax",)),
    LawCatalogEntry("G0340003", "所得稅法", ("land_law_tax",)),
    LawCatalogEntry("G0340105", "契稅條例", ("land_law_tax",)),
    LawCatalogEntry("D0070001", "都市計畫法", ("land_law_tax",)),
)


LAW_CATALOG_BY_CODE = {entry.code: entry for entry in LAW_CATALOG}
LAW_CATALOG_BY_NAME = {entry.name: entry for entry in LAW_CATALOG}


def expected_law_names(*, scope: str | None = None) -> set[str]:
    entries = LAW_CATALOG if scope is None else [entry for entry in LAW_CATALOG if entry.scope == scope]
    return {entry.name for entry in entries}
