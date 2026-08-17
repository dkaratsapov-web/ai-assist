"""Справочник ниш.

Открытый справочник без привязки к проекту: список ниш одинаков для всех и
меняется вместе с кодом, а не с данными. Отдаётся целиком — ниш десяток, и
разбивать это на страницы значило бы усложнять ради принципа.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...services import niches
from ...services.audit import BLOCKING_ISSUE_KEYS
from ..schemas import NicheList, NicheRead, NicheRequirementRead

router = APIRouter(tags=["niches"])


def to_read(niche: niches.Niche) -> NicheRead:
    """Шаблон ниши в виде, пригодном для интерфейса."""
    return NicheRead(
        key=niche.key,
        label=niche.label,
        # Общие минус-слова приходят вместе с нишевыми: разделять их в
        # интерфейсе незачем, добавлять всё равно будут одним списком.
        minus_words=list(niches.minus_words(niche)),
        requirements=[
            NicheRequirementRead(
                key=r.issue_key.value,
                title=r.title,
                hint=r.hint,
                blocking=r.issue_key in BLOCKING_ISSUE_KEYS,
            )
            for r in niche.requirements
        ],
        main_conversion=niche.main_conversion,
        notes=list(niche.notes),
    )


@router.get("/niches", response_model=NicheList, summary="Справочник ниш")
async def list_niches() -> NicheList:
    return NicheList(items=[to_read(n) for n in niches.NICHES])
