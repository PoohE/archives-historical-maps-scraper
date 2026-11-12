"""Единственный разрешённый способ читать «ненадёжные» поля каталога.

Зачем: поле «Масштаб (знаменатель)» у 42 615 записей (37 % каталога) заполнено
ЭВРИСТИКОЙ по типу источника, а не измерением, и подсчёты её молча использовали —
так в разборе серии 24 возник ложный вывод «доминирует 1:8 400» (1 588 записей
из 2 068 при 44 реально указанных). Память:
`feedback_guess-in-numeric-field-poisons-analysis`.

Правило проекта с 09.11.2026: **числовое поле масштаба не читается напрямую**.
Любой скрипт, которому нужен масштаб, зовёт `scale_of()` и сам решает, годится ли
ему значение такого происхождения. То же для года: `year_of()` отличает год дела
от года, взятого по крайним датам описи (1 847 записей).

    from catalog_fields import scale_of, year_of, TRUSTED_SCALE

    val, prov = scale_of(fields)
    if prov in TRUSTED_SCALE:
        ...  # можно считать
"""

import re

SCALE_PROP = "Масштаб: источник значения"
SCALE_NUM = "Масштаб (знаменатель)"
SCALE_TEXT = "Оригинальный масштаб"

#: происхождения, пригодные для количественного анализа
TRUSTED_SCALE = frozenset({"с листа", "из заголовка описи"})
#: происхождение-догадка: в анализ не брать, только как грубую подсказку
GUESSED_SCALE = frozenset({"по типу источника"})

_HEUR = re.compile(r"приближ|по типу", re.IGNORECASE)
_SCALE_IN_TITLE = re.compile(
    r"\d{1,4}\s*саж(?:ен\w*|\.)|\d{1,3}\s*(?:верст\w*|в\.)\s*(?:в\s*дюйм|/\s*дюйм)"
    r"|\bм-\s*\d{1,3}\s*в\b|1\s*:\s*\d{3,9}",
    re.IGNORECASE,
)
_YEAR_BY_OPIS = re.compile(
    r"крайни\w*\s+дат\w*\s+описи|по\s+крайним\s+датам", re.IGNORECASE
)


def scale_provenance(fields: dict) -> str:
    """Происхождение значения масштаба.

    Читает готовый признак, если он уже выставлен в карточке; иначе выводит его
    тем же детерминированным правилом, что и `scale_provenance.py`, — чтобы
    скрипты работали одинаково и до, и после заливки признака.
    """
    stored = fields.get(SCALE_PROP)
    if isinstance(stored, str) and stored:
        return stored
    text_scale = str(fields.get(SCALE_TEXT) or "").strip()
    if text_scale:
        return "по типу источника" if _HEUR.search(text_scale) else "с листа"
    if fields.get(SCALE_NUM):
        blob = f"{fields.get('Название источника') or ''} {fields.get('Описание') or ''}"
        return "из заголовка описи" if _SCALE_IN_TITLE.search(blob) else "не установлен"
    return "не установлен"


def scale_of(fields: dict) -> tuple[int | None, str]:
    """(знаменатель, происхождение). Знаменатель отдаётся КАК ЕСТЬ —
    решение «можно ли считать» принимает вызывающий по происхождению."""
    num = fields.get(SCALE_NUM)
    try:
        val = int(num) if num is not None else None
    except (TypeError, ValueError):
        val = None
    return val, scale_provenance(fields)


def trusted_scale(fields: dict) -> int | None:
    """Знаменатель, пригодный для количественного анализа, иначе None."""
    val, prov = scale_of(fields)
    return val if prov in TRUSTED_SCALE else None


def year_of(fields: dict) -> tuple[int | None, str]:
    """(нижний год, происхождение).

    Происхождение: «по описи» — год взят по крайним датам описи, к документу не
    относится; «из записи» — стоит без такой оговорки; «нет» — года нет.
    """
    y = fields.get("Год создания (нижняя)")
    try:
        val = int(y) if y is not None else None
    except (TypeError, ValueError):
        val = None
    if val is None:
        return None, "нет"
    if _YEAR_BY_OPIS.search(str(fields.get("Примечания") or "")):
        return val, "по описи"
    return val, "из записи"


def trusted_year(fields: dict) -> int | None:
    """Год, пригодный для хронологических выводов, иначе None."""
    val, prov = year_of(fields)
    return val if prov == "из записи" else None


def selftest() -> int:
    cases = [
        ({SCALE_TEXT: "приближённо по типу «межевой план дачи» (~1:8 400)",
          SCALE_NUM: 8400}, "по типу источника", None),
        ({SCALE_TEXT: "100 саж. в дюйме", SCALE_NUM: 8400}, "с листа", 8400),
        ({SCALE_NUM: 42000, "Название источника": "План уезда. Масштаб 1 верста в дюйме"},
         "из заголовка описи", 42000),
        ({SCALE_NUM: 8400, "Название источника": "План дачи"}, "не установлен", None),
        ({}, "не установлен", None),
        ({SCALE_PROP: "с листа", SCALE_NUM: 21000}, "с листа", 21000),
    ]
    bad = 0
    for f, want_prov, want_val in cases:
        val, prov = scale_of(f)
        got = trusted_scale(f)
        if prov != want_prov or got != want_val:
            bad += 1
            print(f"  ✗ {f} → ({val}, {prov}), trusted={got}; ждали {want_prov}/{want_val}")
    years = [
        ({"Год создания (нижняя)": 1845,
          "Примечания": "Год приближённо — по крайним датам описи 1741–1916."},
         "по описи", None),
        ({"Год создания (нижняя)": 1911, "Примечания": "ГАПК ф.279 оп.1 д.5"},
         "из записи", 1911),
        ({}, "нет", None),
    ]
    for f, want_prov, want_val in years:
        val, prov = year_of(f)
        got = trusted_year(f)
        if prov != want_prov or got != want_val:
            bad += 1
            print(f"  ✗ год {f} → ({val}, {prov}), trusted={got}; ждали {want_prov}/{want_val}")
    total = len(cases) + len(years)
    print(f"эталон catalog_fields: {total - bad}/{total} совпало")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if selftest() else 0)
