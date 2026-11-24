"""ГАСО ф. 259 «Коллекция планов, чертежей земель и лесов Смоленской губернии» → каталог (24.11.2026).

Решение владельца 24.11: подготовить пакет и внести после показа чисел. Опись распознана 04.10
(`output/gaso_f259_opis1_vision_20261004/records.jsonl`, 268 дел, проверка по заверительным
надписям — пропусков и дублей номеров нет). В каталоге ф. 259 не было ни одной записи.

Правила сборки (как у прочих записей ГАСО):
  * территория — по разделу описи (уезды Смоленской губ.; Медынский → Калужская губ.;
    Можайский — Московская губ., вне скоупа → не вносится);
  * тип — классификатор 11.11 (`classify_for_upload.SYSTEM2`, Sonnet), только уверенный;
    «нет» (фасады, проекты зданий) → не вносится, причина в журнале сборки;
  * год — из граф описи «крайние даты»; пусто — пусто; граница отбора — по 1941 г.;
  * статус «принято», доступ «Только метаданные», ссылка — опись фонда на портале ГАСО.

  python scripts/gaso259_upload_2026_11_24.py build
  python scripts/gaso259_upload_2026_11_24.py upload      # создание страниц, журнал по page id
  python scripts/gaso259_upload_2026_11_24.py verify
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_for_upload import SYSTEM2, answer_text, strip_fence  # noqa: E402
from kandidaty_apply_2026_11_23 import ENV_PATH, api  # noqa: E402
from common import anthropic_client, env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "gaso_f259_opis1_vision_20261004" / "records.jsonl"
WORK = ROOT / "output" / "gaso259_upload_2026-11-24"
REL = ROOT / "output" / "notion_catalog_20261123_231257_relations.json"
DS = json.loads((ROOT / "scripts" / "modules" / "notion_schema.json").read_text(encoding="utf-8"))["data_source_id"]
URL = "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=155"
ARCH = "Государственный архив Смоленской области (ГАСО)"
CODES = {"A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9",
         "B10", "B11", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"}
DC = {"A": "StillImage", "B": "Text", "C": "Dataset"}


def level(title: str, section: str) -> str:
    t = title.lower()
    if "губерни" in t and "карта" in t:
        return "Губерния"
    if "округов" in t or "уездов" in t:
        return "Уезд"
    if section.startswith("г. ") or "город" in t or re.search(r"\bг\. [А-Я]", title):
        return "Населённый пункт"
    return "Дача"


def build() -> None:
    rows = [json.loads(x) for x in SRC.open(encoding="utf-8")]
    load_env()
    client = anthropic_client()
    typed = {}
    for k in range(0, len(rows), 25):
        chunk = rows[k:k + 25]
        body = "\n".join(f'{j}. ЗАГОЛОВОК: {r["title"]}\n   ФОНД/СЕРИЯ: ГАСО ф. 259 «Коллекция планов, '
                         f'чертежей земель и лесов Смоленской губернии», раздел «{r["uezd"]}»'
                         for j, r in enumerate(chunk))
        for _ in range(3):
            msg = client.messages.create(model="claude-sonnet-5-5", max_tokens=6000, system=SYSTEM2,
                                         messages=[{"role": "user", "content": body}])
            try:
                for a in json.loads(strip_fence(answer_text(msg))):
                    typed[k + int(a["i"])] = a
                break
            except json.JSONDecodeError:
                continue
    out, drop = [], []
    for i, r in enumerate(rows):
        a = typed.get(i, {})
        code = a.get("code") if a.get("sure") and a.get("code") in CODES else ""
        sec = r["uezd"]
        if "Московская" in sec:
            drop.append({**r, "почему": "Можайский уезд Московской губернии — вне скоупа"})
            continue
        if a.get("code") == "нет":
            drop.append({**r, "почему": f"не источник каталога по типологии: {a.get('why', '')}"})
            continue
        y1, y2 = r["year_from"], r["year_to"]
        if (y2 or y1) and int(y2 or y1) > 1941:
            drop.append({**r, "почему": f"год {y2 or y1} — после 1941"})
            continue
        kal = "Калужская" in sec
        note = [f"страница скана описи: {r['page']} (способ: vision, распознано 04.10.2026)",
                "Опись № 1 ф. 259 «Коллекция планов, чертежей земель и лесов Смоленской губернии», 1750–1915",
                f"раздел описи: {sec}" + (f"; связка {r['svyazka']}" if r.get("svyazka") else ""),
                "Ссылка — на опись фонда (карточки дел портал ГАСО не публикует)"]
        if r.get("note"):
            note.append(f"примечание описи: {r['note']}")
        note.append(f"Тип размечен моделью 24.11.2026 по заголовку: {code} — {a.get('why', '')}" if code
                    else "Тип не определён (модель не уверена) — оставлен пустым")
        out.append({"n": r["n"], "title": r["title"], "year_from": y1, "year_to": y2, "sheets": r["sheets"],
                    "region": "Калужская область" if kal else "Смоленская область",
                    "terr": "Калужская губерния" if kal else "Смоленская губерния",
                    "level": level(r["title"], sec), "code": code, "note": "\n".join(note)})
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "paket.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out), encoding="utf-8")
    with (WORK / "ne_vneseno.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["n", "uezd", "title", "почему"], extrasaction="ignore")
        w.writeheader()
        w.writerows(drop)
    print(f"к внесению {len(out)}, не вносится {len(drop)}")
    print("тип:", Counter(x["code"] or "пусто" for x in out).most_common())
    print("уровень:", Counter(x["level"] for x in out).most_common())
    print("территория:", Counter(x["terr"] for x in out).most_common())
    print("год:", sum(1 for x in out if x["year_from"] or x["year_to"]), "с годом")
    for d in drop:
        print("  не вносится:", d["n"], d["title"][:70], "—", d["почему"][:60])


def props(x: dict, rel: dict) -> dict:
    rt = lambda s: {"rich_text": [{"type": "text", "text": {"content": str(s)[:2000]}}]}  # noqa: E731
    p = {"Название источника": {"title": [{"type": "text", "text": {"content": x["title"][:2000]}}]},
         "Описание": rt(x["title"]), "Фонд": rt("259"), "Опись": rt("1"), "Единица хранения": rt(x["n"]),
         "Архив хранения": {"relation": [{"id": rel["Архив хранения"][ARCH]}]},
         "Место хранения": rt("Государственный архив Смоленской области (ГАСО), г. Смоленск"),
         "Охватываемая территория": {"relation": [{"id": rel["Охватываемая территория"][x["terr"]]}]},
         "Современные регионы": {"relation": [{"id": rel["Современные регионы"][x["region"]]}]},
         "Административный уровень": {"select": {"name": x["level"]}},
         "Статус приёмки": {"select": {"name": "принято"}},
         "Статус доступа": {"select": {"name": "Только метаданные"}},
         "Язык": {"select": {"name": "Русский"}},
         "Автор внесения": {"select": {"name": "Агент"}},
         "Дата внесения": {"date": {"start": "2026-11-24"}},
         "Ссылка на онлайн-архив": {"url": URL},
         "Примечания": rt(x["note"])}
    if x["code"]:
        p["Тип источника"] = {"relation": [{"id": rel["Тип источника"][x["code"]]}]}
        p["DC Type"] = {"select": {"name": DC[x["code"][0]]}}
    if x["year_from"]:
        p["Год создания (нижняя)"] = {"number": int(x["year_from"])}
    if x["year_to"]:
        p["Год создания (верхняя)"] = {"number": int(x["year_to"])}
    if x["year_from"] or x["year_to"]:
        p["Год: источник значения"] = {"select": {"name": "из карточки дела"}}
    if x["sheets"]:
        p["Листы / страницы"] = rt(x["sheets"])
    return p


def upload() -> None:
    rel = json.loads(REL.read_text(encoding="utf-8"))
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    jp = WORK / "created_pages.jsonl"
    done = {json.loads(x)["n"] for x in jp.open(encoding="utf-8")} if jp.exists() else set()
    rows = [json.loads(x) for x in (WORK / "paket.jsonl").open(encoding="utf-8")]
    with jp.open("a", encoding="utf-8", newline="\n") as f:
        for x in rows:
            if x["n"] in done:
                continue
            p = api("POST", "/pages", token, {"parent": {"type": "data_source_id", "data_source_id": DS},
                                              "properties": props(x, rel)})
            f.write(json.dumps({"n": x["n"], "page_id": p["id"]}, ensure_ascii=False) + "\n")
            f.flush()
    print(f"создано всего: {sum(1 for _ in jp.open(encoding='utf-8'))} из {len(rows)}")


def verify() -> None:
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    rows = {json.loads(x)["n"]: json.loads(x) for x in (WORK / "paket.jsonl").open(encoding="utf-8")}
    made = [json.loads(x) for x in (WORK / "created_pages.jsonl").open(encoding="utf-8")]
    bad = []
    for m in made:
        p = api("GET", f"/pages/{m['page_id']}", token)
        pr = p.get("properties", {})
        title = "".join(t["plain_text"] for t in pr.get("Название источника", {}).get("title", []))
        ok = (not p.get("in_trash") and title == rows[m["n"]]["title"][:2000]
              and pr["Архив хранения"]["relation"] and pr["Статус приёмки"]["select"]["name"] == "принято")
        if not ok:
            bad.append(m)
    ns = Counter(m["n"] for m in made)
    print(f"сверка опросом: {len(made) - len(bad)} из {len(made)} верно; дублей по номеру дела: "
          f"{[n for n, c in ns.items() if c > 1]}; не создано: {sorted(set(rows) - set(ns))}; расхождения: {bad}")


if __name__ == "__main__":
    fix_stdout()
    {"build": build, "upload": upload, "verify": verify}[sys.argv[1]]()
