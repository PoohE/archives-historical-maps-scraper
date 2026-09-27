"""Общее правило авто-простановки «Охватываемая территория» и «Современные регионы».

Единая логика для моста (`notion_upload_candidates.py`) и sweep (`maintenance/sweep_territory.py`),
чтобы поля заполнялись АВТОМАТИЧЕСКИ при каждой заливке любого источника, а не разовым скриптом.

Правило:
  1. Из названия вытащить уезд/город (у РГАДА — из «Губерния, уезд: X; Y», в т.ч. перечисления
     через «,»/«;»/« и »).
  2. Смэтчить со справочником территорий по стему (нормализация ё→е + срез окончаний прилагательных
     + карта вариантов написания из описей РГАДА).
  3. «Современные регионы» = { губерния каждой смэтченной территории → регион } ∪
     { прямой стем губернии в названии → регион }. Так регион тянется из территории
     (Чердынский уезд → Пермская → Пермский край), а не только из стема губернии.

Функции чистые: справочники (индексы) передаются аргументами — тестируемо, без кред внутри.
"""
import re

# губерния (справочник select, lower) → современный регион (title в справочнике «Современные регионы»)
GUB_TO_REGION = {
    "калужская": "Калужская область",
    "пермская": "Пермский край",
    "смоленская": "Смоленская область",
    "ярославская": "Ярославская область",
}
# прямой стем губернии в названии → регион (фолбэк, если территория не смэтчилась)
REGION_STEMS = {
    "калуж": "Калужская область",
    "перм": "Пермский край",
    "смолен": "Смоленская область",
    "ярослав": "Ярославская область",
}
# варианты написания уездов в описях РГАДА → канон справочника (применяется к стему)
VARIANT = {
    "духовцин": "духовщин",   # Духовцинский → Духовщинский
    "рославск": "рославльск",  # Рославский → Рославльский
}

_RGADA_TERR = re.compile(r"уезд[^:]*:\s*([^;]+);\s*(.+)$")
_SUFFIXES = ("ского", "скому", "ском", "ская", "ский", "ой", "ый", "ий")


def stem(s: str) -> str:
    """Нижний регистр, ё→е, срез окончаний прилагательных, карта вариантов."""
    s = s.lower().replace("ё", "е").strip().rstrip(".")
    for suf in _SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf) + 2:
            s = s[: -len(suf)]
            break
    return VARIANT.get(s, s)


def is_rgada(title: str, url: str) -> bool:
    return "rgada" in (url or "").lower() or bool(_RGADA_TERR.search(title or ""))


def territory_names(title: str, rgada: bool) -> list[str]:
    """Список сырых имён уездов/городов из названия."""
    names: list[str] = []
    if rgada:
        m = _RGADA_TERR.search(title)
        if m:
            for part in re.split(r"[,;]|\sи\s", m.group(2)):
                part = re.sub(r"\(.*?\)", "", part).strip().rstrip(".")
                part = re.sub(r"\s+уезд[а-я]*$", "", part, flags=re.I).strip()
                if part and part.lower() not in ("уезды", "уезд"):
                    names.append(part)
    else:
        for m in re.finditer(r"([А-ЯЁ][а-яё\-]+)\s+уезд", title):
            names.append(m.group(1))
    return names


def resolve(title, url, terr_stem_index, terr_gub, reg_index, hints=None):
    """→ (territory_page_ids, region_page_ids). Индексы:
       terr_stem_index: stem(name) -> page_id территории;
       terr_gub:        page_id территории -> губерния(lower);
       reg_index:       название региона -> page_id.
       hints:           явные строки территории от источника (ПрБ entry["territory"]
                        «Калужская губерния»/«Соликамск»; локальный каталог «Мещовский»/
                        «Калужская губерния»). Надёжнее парсинга названия — их матчим по стему.
    """
    rgada = is_rgada(title, url)
    terr_ids: list[str] = []
    regions: set[str] = set()
    for nm in territory_names(title, rgada) + list(hints or []):
        if not nm:
            continue
        pid = terr_stem_index.get(stem(nm))
        if pid:
            terr_ids.append(pid)
            g = (terr_gub.get(pid) or "").lower()
            if g in GUB_TO_REGION:
                regions.add(GUB_TO_REGION[g])
    src = ((title or "") + " " + " ".join(hints or [])).lower().replace("ё", "е")
    for stm, name in REGION_STEMS.items():
        if stm in src:
            regions.add(name)
    reg_ids = [reg_index[n] for n in regions if n in reg_index]
    return list(dict.fromkeys(terr_ids)), list(dict.fromkeys(reg_ids))


def load_indexes(api_call, terr_db, reg_db):
    """Построить индексы из справочников. api_call(method,url,data)->json (как в мосте/sweep)."""
    def load(dbid):
        rows, cur = [], None
        while True:
            body = {"page_size": 100}
            if cur:
                body["start_cursor"] = cur
            r = api_call("POST", f"https://api.notion.com/v1/databases/{dbid}/query", body)
            rows += r["results"]
            if not r["has_more"]:
                break
            cur = r["next_cursor"]
        return rows

    terr_rows = load(terr_db)
    terr_stem_index, terr_gub = {}, {}
    for pg in terr_rows:
        pr = pg["properties"]
        nm = "".join(x["plain_text"] for x in pr["Название"]["title"]).strip()
        if not nm:
            continue
        terr_stem_index.setdefault(stem(nm), pg["id"])
        gub = (pr.get("Губерния", {}).get("select") or {}).get("name", "")
        terr_gub[pg["id"]] = gub

    reg_rows = load(reg_db)
    reg_index = {}
    for pg in reg_rows:
        tcol = [k for k, v in pg["properties"].items() if v["type"] == "title"][0]
        nm = "".join(x["plain_text"] for x in pg["properties"][tcol]["title"]).strip()
        if nm:
            reg_index[nm] = pg["id"]
    return terr_stem_index, terr_gub, reg_index
