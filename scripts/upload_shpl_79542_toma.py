"""Внесение 11 томов «Статистического описания Калужской губернии» (ГПИБ, node 79542).

Зачем. В каталоге стояла ОДНА запись-обёртка на всё многотомное издание 1897–1915,
без года и без территории, хотя каждый том — отдельный уезд. На это указал А. Алейников
в задаче RAB-7 23.10.2026 («можно ли в каталог добавить каждый том = уезд отдельно?»),
вопрос остался без ответа. Единица каталога у нас — выпуск, а не издательская обёртка
(память `feedback_edinica-kataloga-list-serii-ne-obekt`), поэтому вносим 11 томов.

Обёртку (node 79542) НЕ трогаем и не удаляем: она остаётся записью на издание целиком,
к ней привязана серия. Новые записи ссылаются на неё примечанием.

Состав снят с портала 19.11.2026 (`output/shpl_79542_toma.json`): Козельский (2 вып.),
Лихвинский, Перемышльский, Калужский, Малоярославецкий (2 вып.), Мещовский (2 вып.),
Жиздринский (2 вып.). У т. 5 вып. 1 — приложение 8 карт, у т. 6 вып. 2 — схематическая
почвенная карта Мещовского уезда с границами волостей (о ней Алейников писал отдельно).

Приёмка — по журналу созданных page_id и сверке чтением страниц, а не по докладу
(память `feedback_upload-acceptance-by-page-id-journal`).

Запуск:
    python scripts/upload_shpl_79542_toma.py --dry-run
    python scripts/upload_shpl_79542_toma.py --apply
    python scripts/upload_shpl_79542_toma.py --verify
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout, load_env  # noqa: E402

TOMA = ROOT / "output" / "shpl_79542_toma.json"
JOURNAL = ROOT / "output" / "upload_shpl_79542" / "created_pages.jsonl"

CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
WRAPPER_PAGE = "4010ba89-eabe-81c9-95b1-dcdb78944a80"          # запись на издание целиком

# Связи, снятые с записи-обёртки — у томов они те же.
TYPE_REL = "3830ba89-eabe-812b-8503-fc918c8a2b0b"               # тип источника
ARCHIVE_REL = "3920ba89-eabe-81d8-8da0-c14ad8609570"            # ГПИБ
SERIES_REL = "4130ba89-eabe-8133-a490-ea94dfbb8265"             # земские оценочно-статистические
REGION_REL = "3c30ba89-eabe-811e-b25b-d2ca491ba56f"             # современный регион
GUBERNIYA = "3920ba89-eabe-81be-af09-c20fea0fb910"              # Калужская губерния

UEZD = {
    "Козельский": "3920ba89-eabe-814c-8bb7-d1929ea83990",
    "Лихвинский": "3920ba89-eabe-8156-8052-c6ff8d6b554f",
    "Перемышльский": "3920ba89-eabe-81f4-9d78-d761b206d2a2",
    "Калужский": "3920ba89-eabe-812c-b0e1-e9663448c291",
    "Малоярославецкий": "3920ba89-eabe-815c-a1bd-d214c23f3236",
    "Мещовский": "3920ba89-eabe-81ea-b0b4-eb18d1a7d818",
    "Жиздринский": "3920ba89-eabe-816b-a4f5-f994853f12a4",
}
UEZD_RE = re.compile("(" + "|".join(u[:-2] for u in UEZD) + r")\w*")


def uezd_of(title: str) -> str | None:
    m = UEZD_RE.search(title)
    if not m:
        return None
    stem = m.group(1)
    return next((u for u in UEZD if u.startswith(stem)), None)


def build(rec: dict) -> dict:
    """Поля одной записи каталога по тому издания."""
    title = rec["title"].strip().rstrip(".")
    uezd = uezd_of(title)
    full = f"Статистическое описание Калужской губернии. {title}"
    # Карты в томе названы прямо в заголовке — это важно для отбора.
    karty = "карт" in title.lower() or "почвенной карт" in title.lower()
    note = (f"ГПИБ (elib.shpl.ru), node_id {rec['node']}, карточка: {rec['url']}. "
            f"Том многотомного издания «Статистическое описание Калужской губернии "
            f"[по годам]. — Калуга, 1897–1915» (обёртка — node 79542). "
            f"Уезд: {uezd or 'не определён'}.")
    if karty:
        note += " ⚠️ В томе есть картографическое приложение (названо в заголовке)."
    if rec.get("stranic"):
        note += f" Объём: {rec['stranic']} с."
    props: dict = {
        "Название источника": {"title": [{"text": {"content": full[:1900]}}]},
        "Описание": {"rich_text": [{"text": {"content": full[:1900]}}]},
        "Ссылка на онлайн-архив": {"url": rec["url"]},
        "Библиотечный шифр": {"rich_text": [{"text": {"content": f"ГПИБ, node {rec['node']}"}}]},
        "Место хранения": {"rich_text": [{"text": {
            "content": "Государственная публичная историческая библиотека России (elib.shpl.ru)"}}]},
        "Примечания": {"rich_text": [{"text": {"content": note[:1900]}}]},
        "Язык": {"select": {"name": "Русский"}},
        "Автор внесения": {"select": {"name": "Агент"}},
        "Статус приёмки": {"select": {"name": "кандидат"}},
        "Статус доступа": {"select": {"name": "Открытый доступ"}},
        "DC Type": {"select": {"name": "Text"}},
        "Административный уровень": {"select": {"name": "Уезд" if uezd else "Губерния"}},
        "Дата внесения": {"date": {"start": date.today().isoformat()}},
        "Тип источника": {"relation": [{"id": TYPE_REL}]},
        "Архив хранения": {"relation": [{"id": ARCHIVE_REL}]},
        "Серия / массив": {"relation": [{"id": SERIES_REL}]},
        "Современные регионы": {"relation": [{"id": REGION_REL}]},
        "Охватываемая территория": {"relation": [{"id": UEZD[uezd] if uezd else GUBERNIYA}]},
    }
    if rec.get("god"):
        props["Год сведений"] = {"number": int(rec["god"])}
    return props


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="создать записи в каталоге")
    ap.add_argument("--dry-run", action="store_true", help="показать, что будет создано")
    ap.add_argument("--verify", action="store_true", help="сверить созданное чтением страниц")
    args = ap.parse_args()
    load_env()
    import os

    from notion_client import Client
    c = Client(auth=os.environ["NOTION_TOKEN"])
    rows = json.loads(TOMA.read_text(encoding="utf-8"))

    if args.verify:
        if not JOURNAL.exists():
            raise SystemExit("журнала нет — сначала --apply")
        recs = [json.loads(ln) for ln in JOURNAL.open(encoding="utf-8")]
        bad = 0
        for r in recs:
            p = c.pages.retrieve(page_id=r["page_id"])
            name = "".join(x["plain_text"] for x in p["properties"]["Название источника"]["title"])
            url = p["properties"]["Ссылка на онлайн-архив"]["url"]
            terr = [x["id"] for x in p["properties"]["Охватываемая территория"]["relation"]]
            ok = url == r["url"] and name.startswith("Статистическое описание") and terr
            bad += 0 if ok else 1
            print(f"  {'OK ' if ok else '!! '} {r['node']}  {name[:72]}")
        print(f"\nпроверено {len(recs)} страниц, расхождений {bad}")
        sys.exit(1 if bad else 0)

    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if JOURNAL.exists():
        done = {json.loads(ln)["node"] for ln in JOURNAL.open(encoding="utf-8")}

    created = 0
    with JOURNAL.open("a", encoding="utf-8") as jf:
        for rec in rows:
            if rec["node"] in done:
                print(f"  пропуск (уже внесён): {rec['node']}")
                continue
            props = build(rec)
            u = uezd_of(rec["title"]) or "—"
            if args.dry_run or not args.apply:
                print(f"  [{rec['node']}] {u:<17} {rec.get('god','—'):<6} "
                      f"{props['Название источника']['title'][0]['text']['content'][:70]}")
                continue
            page = c.pages.create(parent={"data_source_id": CATALOG_DS}, properties=props)
            jf.write(json.dumps({"node": rec["node"], "page_id": page["id"],
                                 "url": rec["url"], "uezd": u}, ensure_ascii=False) + "\n")
            jf.flush()
            created += 1
            print(f"  создано: {rec['node']}  {u:<17} → {page['id']}")
    if args.apply:
        print(f"\nсоздано записей: {created}; журнал: {JOURNAL}")
        print("дальше: python scripts/upload_shpl_79542_toma.py --verify")
    else:
        print(f"\n--dry-run: {len(rows)} томов готовы к внесению, ничего не создано")


if __name__ == "__main__":
    main()
