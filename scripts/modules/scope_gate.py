"""Project-wide post-extraction scope decision (§1 of ПРАВИЛА_ОТБОРА_источников.md).

Uncertain geography remains a candidate with needs_human=True. Callers persist
both kept and dropped records, together with the returned rule and reason.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class Verdict:
    keep: bool
    reason: str | None
    needs_human: bool
    rule: str
    evidence: str

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Policy:
    rules_sha256: str
    amendments: Mapping[str, tuple[str, ...]]


def load_policy(path: str | Path, *, expected_sha256: str | None = None) -> Policy:
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Selection rules changed; review and rebuild package")
    text = raw.decode("utf-8-sig")
    required = ("### 1.1 Предметный критерий", "### 1.2 Территориальный уровень",
                "### 1.3 Территориальная релевантность", "### 1.4 Хронология",
                "### 1.5 Тематические карты", "## 2. Региональные поправки")
    if any(token not in text for token in required):
        raise ValueError("Selection rules document has an unfamiliar structure")
    if not all(token in text for token in ("**Пермь**", "**Урал**", "**Пермский край**")):
        raise ValueError("Perm regional amendment is missing")
    return Policy(digest, {"permkrai_regions": ("урал", "пермский край"),
                           "permkrai_city_forms": ("перми", "пермь"),
                           "permkrai_target_stems": ("перм", "урал")})


def _value(record: Any, key: str) -> Any:
    if isinstance(record, Mapping):
        if "record" in record and isinstance(record["record"], Mapping):
            record = record["record"]
        return record.get(key)
    return getattr(record, key, None)


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold().replace("ё", "е")


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, flags=re.I))


def _amendments(source: str, amendments: Mapping[str, Any] | Policy | None) -> Mapping[str, Any]:
    if isinstance(amendments, Policy):
        if source == "permkrai":
            return {"equivalent_regions": amendments.amendments["permkrai_regions"],
                    "city_forms": amendments.amendments["permkrai_city_forms"],
                    "target_stems": amendments.amendments["permkrai_target_stems"]}
        return {}
    return amendments or {}


def check(record: Any, *, source: str, amendments: Mapping[str, Any] | Policy | None = None) -> Verdict:
    """Classify a parsed card; no year-based exclusion and no silent drops."""
    amend = _amendments(source, amendments)
    title = _text(_value(record, "title"))
    description = _text(_value(record, "description") or _value(record, "bibliography"))
    if not title:
        return Verdict(True, None, True, "1.1", "missing_title")

    # The subject is a document plan even when a search/rubric uses "план".
    nonmap_plan = (
        r"\b(?:план\s+(?:работ[ыа]?|счетов|мероприятий|занятий|хозяйства|кампании|"
        r"распространения|улучшения)|"
        r"учебн\w*\s+план|пятилетн\w*\s+план|тематическ\w*\s+план|"
        r"народнохозяйственн\w*\s+план)\b"
    )
    if _has(nonmap_plan, title):
        return Verdict(False, "not_cartographic", False, "1.1", "document_plan_title")

    regional = _has(
        r"\b(?:губерни(?:я|и|ю|ей|ями|ях)|наместничеств\w*|уезд\w*|"
        r"волост\w*|край|края|краем|крае|област\w*|регион\w*|урал\w*)\b",
        title,
    ) or any(_text(x) in title for x in amend.get("equivalent_regions", ()))

    # An explicit region is the territorial subject, regardless of a city stem.
    explicit_city_subject = _has(r"\b(?:карта|план|схема)\s+(?:г\.|город\w*)(?=\s|$)", title)
    city = _has(r"\b(?:г\.|город(?:а|у|ом|е|ской|ских|ские|ск\w*))\b", title)
    city = city or _has(r"\b(?:город(?:а|у|ом|е)|г\.)\b", description)
    city = city or any(_has(r"\b" + re.escape(_text(x)) + r"\b", title)
                       for x in amend.get("city_forms", ()))
    if explicit_city_subject or (city and not regional):
        return Verdict(False, "city_level", False, "1.2", "city_territorial_subject")

    # A lone natural/industrial feature is below the administrative unit.
    if not regional and _has(r"\b(?:пещер\w*|шахт\w*|рудник\w*|водопад\w*)\b", title):
        if not _has(r"\b(?:систем\w*|бассейн\w*|уезд\w*|регион\w*)\b", title):
            return Verdict(False, "non_admin_object", False, "1.2", "single_feature_subject")

    # Explicit world, celestial or non-geographic thematic scopes.
    if _has(r"\b(?:universel|всемир\w*|мир(?:а|овой|овая)|неб[ао]|"
            r"кристаллограф\w*|геометрическ\w*\s+кристаллограф\w*)\b", title):
        if not regional:
            return Verdict(False, "out_of_region", False, "1.3", "outside_project_geography")
    if _has(r"театр\w*\s+военн\w*\s+действ", title) and not regional:
        return Verdict(False, "out_of_region", False, "1.3", "foreign_theater_no_target_region")
    if _has(r"\b(?:дагестан\w*|зарубежн\w*|иностранн\w*)\b", title) and not regional:
        return Verdict(False, "out_of_region", False, "1.3", "other_region_or_country")

    marker = False
    extra = _value(record, "extra_json") or {}
    if isinstance(extra, Mapping):
        marker = _text(extra.get("card_type")) in ("карта", "географический атлас")
    cartographic = marker or _has(
        r"\b(?:карт\w*|картограмм\w*|атлас\w*|схем\w*|чертеж\w*|"
        r"план\w*|топограф\w*)\b", title,
    ) or _has(r"\b(?:карта|атлас|план|схема)\b", description)
    if not cartographic:
        return Verdict(True, None, True, "1.1", "cartographic_identity_unconfirmed")

    if regional:
        project_stems = tuple(_text(stem) for stem in amend.get("target_stems", ()))
        if any(stem in title for stem in project_stems):
            return Verdict(True, None, False, "1.2", "regional_subject")
        return Verdict(True, None, True, "1.3", "regional_relevance_needs_review")
    if _has(r"\b(?:рек\w*|водн\w*\s+систем\w*|бассейн\w*)\b", title):
        return Verdict(True, None, True, "1.3", "regional_extent_needs_review")
    return Verdict(True, None, True, "1.3", "territory_not_resolved")
