"""Пачка 14 (ярославская земская оценка) → каталог: 3 издания, которых нет в каталоге.

Решение владельца 24.11.2026 («да» на внесение трёх книг). Остальные найденные издания уже в
каталоге — им серия и губерния проставлены пачкой 14б (output/fixes/batch14b_zem_2026-11-24.csv).

  python scripts/yar_zem_upload_2026_11_24.py upload | verify
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kandidaty_apply_2026_11_23 import ENV_PATH, api  # noqa: E402
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "yar_zem_2026-11-24"
REL = json.loads((ROOT / "output" / "notion_catalog_20261123_231257_relations.json").read_text(encoding="utf-8"))
DS = json.loads((ROOT / "scripts" / "modules" / "notion_schema.json").read_text(encoding="utf-8"))["data_source_id"]
SER = "Земские оценочно-статистические и почвенно-оценочные материалы"
RGB, NEB = "Российская государственная библиотека (РГБ)", "Национальная электронная библиотека (НЭБ)"
ROWS = [
    {"key": "rsl_01003795536", "url": "https://search.rsl.ru/ru/record/01003795536", "arch": RGB, "place": RGB,
     "access": "Только метаданные", "y": 1912, "uezd": "Рыбинский уезд",
     "title": "Бернштейн, Борис Львович (1868-1932). - Почвенно-геологическое описание Рыбинского уезда / [Б.Л. Бернштейн]. - Ярославль : Типо-лит. Губ. зем. упр., 1912. - II, 76 с., 5 л. диагр., карт.; 26. - (Статистическое бюро Ярославского губернского земства. [Статистический сборник; Вып. 85])."},
    {"key": "rsl_01004193300", "url": "https://search.rsl.ru/ru/record/01004193300", "arch": RGB, "place": RGB,
     "access": "Только метаданные", "y": 1914, "uezd": "Ростовский уезд",
     "title": "Оценка лесов Ростовского уезда. - Ярославль : типо-лит. Губ. зем. управы, 1914. - [4], 48, 58 с.; 27. - (Статистический отдел Ярославского губернского земства. [Статистический сборник]; Вып. 110).",
     "extra": "Та же книга в НЭБ: https://rusneb.ru/catalog/000200_000018_v19_rc_1979672/"},
    {"key": "neb_000200_000018_v19_rc_2070216", "url": "https://rusneb.ru/catalog/000200_000018_v19_rc_2070216/", "arch": NEB,
     "place": "Российская национальная библиотека (РНБ) — оригинал; цифровая копия в НЭБ", "access": "Открытый доступ",
     "y": 1912, "uezd": "Ярославский уезд",
     "title": "Бернштейн Б.Л. Крупные почвенные районы Ярославского уезда с описанием почвы лесов. - Ярославль, 1912. - [4], II, 45 с., 1 л. карт."},
]


def rt(s):
    return {"rich_text": [{"type": "text", "text": {"content": str(s)[:2000]}}]}


def props(x):
    note = ["Пачка 14 сессии анализа (ярославская земская оценка); решение владельца 24.11.2026 — внести. "
            "Найдено маршрутом series_library_sweep (Yandex Search API), карточка библиотеки дочитана.",
            "Тип B10 — тематическое описание уезда земским статистическим бюро; год — из карточки библиотеки."]
    if x.get("extra"):
        note.append(x["extra"])
    return {"Название источника": {"title": [{"type": "text", "text": {"content": x["title"][:2000]}}]},
            "Описание": rt(x["title"]),
            "Архив хранения": {"relation": [{"id": REL["Архив хранения"][x["arch"]]}]},
            "Место хранения": rt(x["place"]),
            "Охватываемая территория": {"relation": [{"id": REL["Охватываемая территория"][g]} for g in ("Ярославская губерния", x["uezd"])]},
            "Современные регионы": {"relation": [{"id": REL["Современные регионы"]["Ярославская область"]}]},
            "Серия / массив": {"relation": [{"id": REL["Серия / массив"][SER]}]},
            "Тип источника": {"relation": [{"id": REL["Тип источника"]["B10"]}]}, "DC Type": {"select": {"name": "Text"}},
            "Административный уровень": {"select": {"name": "Уезд"}}, "Статус приёмки": {"select": {"name": "принято"}},
            "Статус доступа": {"select": {"name": x["access"]}}, "Язык": {"select": {"name": "Русский"}},
            "Автор внесения": {"select": {"name": "Агент"}}, "Дата внесения": {"date": {"start": "2026-11-24"}},
            "Ссылка на онлайн-архив": {"url": x["url"]},
            "Год создания (нижняя)": {"number": x["y"]}, "Год создания (верхняя)": {"number": x["y"]},
            "Год: источник значения": {"select": {"name": "из карточки библиотеки"}},
            "Техника исполнения": {"select": {"name": "Печатная"}},
            "Примечания": rt("\n".join(note))}


def upload():
    load_env(ENV_PATH)
    tok = env("NOTION_TOKEN", required=True)
    jp = WORK / "created_pages.jsonl"
    done = {json.loads(x)["key"] for x in jp.open(encoding="utf-8")} if jp.exists() else set()
    with jp.open("a", encoding="utf-8", newline="\n") as f:
        for x in ROWS:
            if x["key"] in done:
                continue
            p = api("POST", "/pages", tok, {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": props(x)})
            f.write(json.dumps({"key": x["key"], "page_id": p["id"]}) + "\n")
            f.flush()
    print("создано:", sum(1 for _ in jp.open(encoding="utf-8")), "из", len(ROWS))


def verify():
    load_env(ENV_PATH)
    tok = env("NOTION_TOKEN", required=True)
    made = [json.loads(x) for x in (WORK / "created_pages.jsonl").open(encoding="utf-8")]
    want = {x["key"]: x for x in ROWS}
    ok = 0
    for m in made:
        p = api("GET", f"/pages/{m['page_id']}", tok)
        pr = p["properties"]
        title = "".join(t["plain_text"] for t in pr["Название источника"]["title"])
        good = (not p.get("in_trash") and title == want[m["key"]]["title"]
                and pr["Статус приёмки"]["select"]["name"] == "принято"
                and pr["Серия / массив"]["relation"] and len(pr["Охватываемая территория"]["relation"]) == 2)
        ok += bool(good)
        if not good:
            print("расхождение", m)
    keys = [m["key"] for m in made]
    print(f"сверка опросом: {ok} из {len(made)} верно; дублей: {len(keys) - len(set(keys))}; не создано: {sorted(set(want) - set(keys))}")


if __name__ == "__main__":
    fix_stdout()
    {"upload": upload, "verify": verify}[sys.argv[1]]()
