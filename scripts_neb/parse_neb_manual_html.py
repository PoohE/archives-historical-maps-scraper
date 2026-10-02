# -*- coding: utf-8 -*-
"""НЭБ: разбор выдачи, сохранённой человеком вручную (каталог «Карты», c[]=7).

Почему вручную. robots rusneb.ru запрещает краулеру `/*?`, `/*pagen=`, `/*ajax=` —
постраничный обход автоматом невозможен (проверено по сохранённому robots, 76 директив).
Человеку выдача доступна, поэтому страницы сохраняются браузером, а разбор идёт офлайн.

Почему маршрут другой, чем у автосборщика. Прогон v3.3 искал «<слово> <губерния>» по ВСЕМУ
каталогу и получал 90+ результатов, где карты — меньшинство (книги и периодика, упоминающие
слово). Правильный маршрут — `search/?q=<губерния>&c[]=7`, где `c[]=7` — каталог «Карты»:
предмет фильтруется типом ресурса надёжнее любого слова в заголовке, шесть ключевых слов
не нужны. Это дало 252 карточки против 144 у автосборщика.

Вход : папка с .html (можно с подпапками по губерниям), сохранёнными как «Веб-страница, полностью».
Выход: output/neb_manual_20261003/ — records.csv, records.jsonl, scope_drops.csv, REPORT.json.
"""
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SRC = BASE / "input_neb_manual"
OUT = BASE / "output" / "neb_manual_20261003"

GUBERNIAS = ("Калужская", "Пермская", "Смоленская", "Ярославская")

# §1.2: город — не единица анализа. Отсекаем, только когда город и есть предмет записи.
CITY = re.compile(
    r"план\s+город[аы]?\s+[А-ЯЁ]"        # «План Города Вязьмы» — лист атласа по городу
    r"|план\s+г\.\s*[А-ЯЁ]"              # «План г. Калуги»
    r"|карта\s+город[аы]?\s+[А-ЯЁ]"
    r"|планы?\s+и\s+гербы\s+городов"     # сборник городских планов
    r"|городск\w+\s+(?:план|карта|схема)"
    r"|путеводитель\s+по\s+г\.", re.I)
UEZD_MARK = re.compile(r"губерн|уезд|волост|наместнич|край|област", re.I)
# §1.3: явно чужие территории в заголовке при отсутствии наших
FOREIGN = re.compile(r"Кавказ|Сибир|Туркестан|Финлянд|Польш|Бессараб|Таврическ|Донск", re.I)

COLS = ["source", "territory", "catalog_id", "title", "part_of", "imprint", "place",
        "publisher", "year_from", "year_to", "source_library", "access", "url",
        "thumbnail", "query", "page_file", "level", "needs_human", "evidence",
        "territory_count", "html_sha256"]


def text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)) if node else ""


def parse_imprint(s: str) -> tuple[str, str, str, str]:
    """«Санкт-Петербург : Ильин, 1876» → место, издатель, год_от, год_до."""
    s = (s or "").strip(" .,")
    years = re.findall(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", s)
    place = publisher = ""
    if ":" in s:
        place, rest = s.split(":", 1)
        publisher = re.sub(r",?\s*\b1[5-9]\d{2}\b.*$|,?\s*\b20[0-2]\d\b.*$", "", rest).strip(" .,")
    else:
        place = re.sub(r",?\s*\b1[5-9]\d{2}\b.*$", "", s).strip(" .,")
    return place.strip(" .,"), publisher, (years[0] if years else ""), (years[-1] if years else "")


def territory_of(query: str, title: str) -> str:
    for g in GUBERNIAS:
        if g.lower() in (query or "").lower():
            return f"{g} губерния"
    for g in GUBERNIAS:
        if re.search(g[:-2], title or "", re.I):
            return f"{g} губерния"
    return ""


def parse_file(path: Path) -> tuple[list[dict], str, int]:
    html = path.read_text(encoding="utf-8", errors="replace")
    sha = hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()[:16]
    soup = BeautifulSoup(html, "lxml")

    q = ""
    inp = soup.find("input", attrs={"value": re.compile(r"губерни", re.I)})
    if inp:
        q = inp.get("value", "").strip()
    m = re.search(r"Найдено\s+(\d+)", soup.get_text(" ", strip=True))
    declared = int(m.group(1)) if m else 0

    rows: list[dict] = []
    for item in soup.select("div.search-list__item[data-search-result-item]"):
        link = item.find("a", href=re.compile(r"/catalog/"))
        if not link:
            continue
        url = link["href"]
        if url.startswith("/"):
            url = "https://rusneb.ru" + url
        cid = re.search(r"/catalog/([^/?#]+)", url)
        # заголовок — ПЕРВЫЙ <div> внутри ссылки; текст всей ссылки тянет за собой
        # сведения об ответственности («сост. …», «Чер. Бланкенгорн») и рвёт название
        title_a = item.find("a", class_=re.compile("max_height_unset"))
        title = ""
        if title_a:
            d0 = title_a.find("div")
            title = text(d0) if d0 else text(title_a)
        title = title or text(link)

        part_of = ""
        po = item.find(string=re.compile(r"Входит в"))
        if po:
            nxt = po.find_parent().find("a")
            part_of = text(nxt)

        imprint = ""
        t4 = item.select_one("div.info_1 div.top_4 div")
        if t4:
            imprint = text(t4)
        place, publisher, y1, y2 = parse_imprint(imprint)

        lib = ""
        for d in item.select("div.info_4"):
            s = text(d)
            if s.startswith("Источник:"):
                lib = s.replace("Источник:", "").strip()
        access = ""
        for d in item.select("div.info_4"):
            s = text(d)
            if "Доступ:" in s:
                access = re.sub(r".*Доступ:\s*⬤?\s*", "", s).strip()

        rows.append({
            "source": "neb", "catalog_id": cid.group(1) if cid else "", "title": title,
            "part_of": part_of, "imprint": imprint, "place": place, "publisher": publisher,
            "year_from": y1, "year_to": y2, "source_library": lib, "access": access,
            "url": url, "thumbnail": "", "query": q, "page_file": path.name,
            "level": "unit", "html_sha256": sha,
        })
    return rows, q, declared


# Город как ПРЕДМЕТ записи — отсекаем безусловно, даже если в названии есть слово
# «губерния»: в «Атлас Смоленской губернии План Города Белого» губерния — часть названия
# атласа, а предметом листа является город. Прежнее условие «CITY and not UEZD_MARK»
# пропускало все 12 городских листов атласа.
CITY_SUBJECT = re.compile(
    r"план\s+город[аы]?\s+[А-ЯЁ]"
    r"|план\s+г\.\s*[А-ЯЁ]"
    r"|карта\s+(?:заштатного\s+)?город[аы]?\s+[А-ЯЁ]"
    r"|губернии\s+города\s+[А-ЯЁ]"          # «План Ярославской губернии города Углич»
    r"|планы?\s+и\s+гербы\s+городов", re.I)
# карта уезда с приложенным планом города — единица УЕЗДНАЯ, берём (решение 2026-10-03)
CITY_PLUS_UEZD = re.compile(r"уезд\w*.{0,40}\sи\s+план\s+город", re.I)


def gate(r: dict) -> tuple[bool, str, str]:
    """Возврат: (оставить, причина_отсева, evidence)."""
    title = r["title"]
    if CITY_SUBJECT.search(title):
        if CITY_PLUS_UEZD.search(title):
            return True, "", "uezd_map_with_city_plan"
        return False, "city_level", "city_is_subject_of_item"
    if CITY.search(title) and not UEZD_MARK.search(title):
        return False, "city_level", "city_in_item_title"
    if not r["territory"]:
        if FOREIGN.search(title):
            return False, "out_of_region", "foreign_region_in_title"
        return True, "", "territory_unknown"
    return True, "", "target_region_in_query"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.rglob("*.html"))
    if not files:
        print(f"HTML не найден в {SRC}")
        return

    seen: dict[str, dict] = {}
    drops: list[dict] = []
    declared: dict[str, int] = {}
    skipped_files: list[str] = []

    for f in files:
        rows, q, dec = parse_file(f)
        if not q or not any(g.lower() in q.lower() for g in GUBERNIAS):
            skipped_files.append(f.name)
            continue
        # берём только маршрут «<губерния>» + каталог Карты; старые запросы «<слово> <губерния>» мимо
        if re.match(r"^(карта|план|атлас|чертёж|съёмка|топограф)", q.strip(), re.I):
            skipped_files.append(f.name)
            continue
        declared[q] = max(declared.get(q, 0), dec)
        for r in rows:
            r["territory"] = territory_of(q, r["title"])
            keep, reason, ev = gate(r)
            r["evidence"] = ev
            r["needs_human"] = "true" if ev == "territory_unknown" else "false"
            if not keep:
                r["scope_drop_reason"] = reason
                drops.append(r)
                continue
            prev = seen.get(r["catalog_id"])
            if prev is None:
                r["territories"] = {r["territory"]} if r["territory"] else set()
                seen[r["catalog_id"]] = r
            else:
                # одна карточка может выйти в поиске НЕСКОЛЬКИХ губерний (атлас империи и т.п.)
                if r["territory"]:
                    prev.setdefault("territories", set()).add(r["territory"])
                if len(r["title"]) > len(prev["title"]):
                    prev["title"] = r["title"]

    for r in seen.values():
        ts = sorted(r.pop("territories", set()) or ({r["territory"]} if r["territory"] else set()))
        r["territory"] = "; ".join(ts)
        r["territory_count"] = len(ts)
    rows = sorted(seen.values(), key=lambda x: (x["territory"], x["title"]))
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    with (OUT / "scope_drops.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS + ["scope_drop_reason"], extrasaction="ignore")
        w.writeheader()
        w.writerows(drops)

    rep = {
        "source": "neb", "mode": "manual_html_catalog_maps", "catalog_filter": "c[]=7 (Карты)",
        "files_total": len(files), "files_used": len(files) - len(skipped_files),
        "files_skipped": skipped_files,
        "declared_by_query": declared,
        "unique_records": len(rows), "drops": len(drops),
        "drop_reasons": dict(Counter(d["scope_drop_reason"] for d in drops)),
        "by_territory": dict(Counter(t for r in rows for t in (r["territory"].split("; ") if r["territory"] else ["не определена"]))),
        "multi_territory": sum(1 for r in rows if r.get("territory_count", 0) > 1),
        "needs_human": sum(1 for r in rows if r["needs_human"] == "true"),
        "with_year": sum(1 for r in rows if r["year_from"]),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"файлов: {len(files)}, использовано {rep['files_used']}, пропущено {len(skipped_files)}")
    print(f"уникальных записей: {len(rows)} | отсев: {len(drops)} {rep['drop_reasons']}")
    print("по губерниям:", rep["by_territory"])
    print("заявлено источником:", declared)
    print(f"с годом: {rep['with_year']} | needs_human: {rep['needs_human']}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
