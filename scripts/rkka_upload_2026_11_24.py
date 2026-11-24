"""Пачка 13 (РККА / советские топокарты до 1963) → каталог. Решение владельца 24.11.2026: «вноси, отсечка 1963».

Из 17 найденных записей по нашим губерниям после сверки года ИЗДАНИЯ листа по карточке РГБ
(в заголовке серии стоит диапазон 1953—1990, сам лист издан в 1979–1990) в отсечку попали 4;
O-37 уже есть в каталоге (НЭБ 000199_000009_008742254). Вносятся 3.

  python scripts/rkka_upload_2026_11_24.py upload | verify
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kandidaty_apply_2026_11_23 import ENV_PATH, api  # noqa: E402
from common import env, fix_stdout, load_env  # noqa: E402
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "rkka_2026-11-24"
REL = json.loads((ROOT / "output" / "notion_catalog_20261123_231257_relations.json").read_text(encoding="utf-8"))
DS = json.loads((ROOT / "scripts" / "modules" / "notion_schema.json").read_text(encoding="utf-8"))["data_source_id"]
CARDS = json.loads((WORK / "rgb_cards_full.json").read_text(encoding="utf-8"))
RKKA = "Топографические карты Генерального штаба РККА (1918–1945)"
GUGK = "Советские топографические карты ГУГК/ЦНИИГАиК"
ROWS = [
    {"id": "008076828", "y1": 1941, "y2": 1941, "scale": 100000, "terr": ["Смоленская губерния"], "reg": ["Смоленская область"],
     "ser": RKKA, "nom": "N-36-34", "neb": False},
    {"id": "008737339", "y1": 1951, "y2": 1952, "scale": 1000000, "terr": ["Калужская губерния"], "reg": ["Калужская область"],
     "ser": GUGK, "nom": "N-37", "neb": True},
    {"id": "008743083", "y1": 1951, "y2": 1953, "scale": 1000000, "terr": ["Пермская губерния"], "reg": ["Пермский край"],
     "ser": GUGK, "nom": "O-40", "neb": True},
]
def rt(s): return {"rich_text": [{"type": "text", "text": {"content": str(s)[:2000]}}]}
def props(x):
    t = CARDS[x["id"]]["title"].replace(" - Search RSL", "")
    note = ["Пачка 13 сессии анализа; решение владельца 24.11.2026 («вноси, отсечка 1963»). Найдено маршрутом series_library_sweep (Yandex Search API), карточка РГБ дочитана.",
            f"Номенклатура {x['nom']}; губерния — по рамке листа и координатам губернских/уездных городов (Wikidata), output/rkka_2026-11-24/nomenklatura.py.",
            "Год: нижняя — составление, верхняя — издание листа (по карточке РГБ)."]
    if x["neb"]: note.append(f"Та же карточка в НЭБ: https://rusneb.ru/catalog/000199_000009_{x['id']}/")
    return {"Название источника": {"title": [{"type": "text", "text": {"content": t[:2000]}}]},
            "Описание": rt(t), "Архив хранения": {"relation": [{"id": REL["Архив хранения"]["Российская государственная библиотека (РГБ)"]}]},
            "Место хранения": rt("Российская государственная библиотека (РГБ)"),
            "Охватываемая территория": {"relation": [{"id": REL["Охватываемая территория"][g]} for g in x["terr"]]},
            "Современные регионы": {"relation": [{"id": REL["Современные регионы"][g]} for g in x["reg"]]},
            "Серия / массив": {"relation": [{"id": REL["Серия / массив"][x["ser"]]}]},
            "Тип источника": {"relation": [{"id": REL["Тип источника"]["A4"]}]}, "DC Type": {"select": {"name": "StillImage"}},
            "Административный уровень": {"select": {"name": "Губерния"}}, "Статус приёмки": {"select": {"name": "принято"}},
            "Статус доступа": {"select": {"name": "Только метаданные"}}, "Язык": {"select": {"name": "Русский"}},
            "Автор внесения": {"select": {"name": "Агент"}}, "Дата внесения": {"date": {"start": "2026-11-24"}},
            "Ссылка на онлайн-архив": {"url": f"https://search.rsl.ru/ru/record/01{x['id']}"},
            "Год создания (нижняя)": {"number": x["y1"]}, "Год создания (верхняя)": {"number": x["y2"]},
            "Год: источник значения": {"select": {"name": "из карточки библиотеки"}},
            "Масштаб (знаменатель)": {"number": x["scale"]}, "Техника исполнения": {"select": {"name": "Печатная"}},
            "Примечания": rt("\n".join(note))}
def upload():
    load_env(ENV_PATH); tok = env("NOTION_TOKEN", required=True)
    jp = WORK / "created_pages.jsonl"
    done = {json.loads(x)["id"] for x in jp.open(encoding="utf-8")} if jp.exists() else set()
    with jp.open("a", encoding="utf-8", newline="\n") as f:
        for x in ROWS:
            if x["id"] in done: continue
            p = api("POST", "/pages", tok, {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": props(x)})
            f.write(json.dumps({"id": x["id"], "page_id": p["id"]}) + "\n"); f.flush()
    print("создано:", sum(1 for _ in jp.open(encoding="utf-8")), "из", len(ROWS))
def verify():
    load_env(ENV_PATH); tok = env("NOTION_TOKEN", required=True)
    made = [json.loads(x) for x in (WORK / "created_pages.jsonl").open(encoding="utf-8")]
    ok = 0
    for m in made:
        p = api("GET", f"/pages/{m['page_id']}", tok); pr = p["properties"]
        good = not p.get("in_trash") and pr["Статус приёмки"]["select"]["name"] == "принято" and pr["Серия / массив"]["relation"] and pr["Охватываемая территория"]["relation"]
        ok += bool(good)
        if not good: print("расхождение", m)
    print(f"сверка опросом: {ok} из {len(made)} верно")
if __name__ == "__main__":
    fix_stdout(); {"upload": upload, "verify": verify}[sys.argv[1]]()
