"""Возврат листов серийных изданий, ошибочно снятых гейтом как «план города».

Критерий пользователя (08.11.2026): единица каталога — ЛИСТ СЕРИИ, а не изображённый
объект. Город сам по себе не наш уровень; но лист, входящий в серийное издание (лист
атласа губернии, уездная карта с приложенным планом города, дача специального межевания
на городской выгон), — наш, независимо от того, что на нём нарисовано.

Гейт в прогонах 02–06.10.2026 снимал такие листы по слову «План города», не проверяя
принадлежность серии. Это ошибка исполнения, а не критерия.

Отобрано 12 записей из 175 `city_level`: десять листов «Атласа Смоленской губернии»,
карта Ростовского уезда с планом Ростова, план Рыбинска с выгонною землёю.

  python restore_city_sheets.py --plan | --apply
"""

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from harvest_cards import fetch, parse  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402
from series910_notion_link import SERIES_DS, query_all, rt, title_of  # noqa: E402

DB = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\найденные_источники.sqlite"
)
CATALOG_DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"

SELECT = """SELECT klyuch, nazvanie, url, derzhatel, gubernii FROM istochniki
WHERE v_skoupe=1 AND status LIKE '%city_level%'
AND (nazvanie LIKE '%Атлас Смоленской%' OR nazvanie LIKE '%Ростовского уезда%'
     OR nazvanie LIKE '%Рыбинска с выгон%')"""

# серия → по названию карточки в Notion
SERIES_FOR = {
    "Атлас Смоленской губернии": "Атлас Смоленской губернии",
    # атрибуция по ведомству и объекту, не по титулу серии:
    # «чертёж Новикова — ростовского уездного землемера», 1858 → межевое ведомство;
    # план выгонной земли Рыбинска по съёмке 1850–51 → межевой объект (городской выгон).
    "Ростовского уезда": "Генеральное и специальное межевание (межевой комплекс, 1765–1917)",
    "Рыбинска с выгон": "Генеральное и специальное межевание (межевой комплекс, 1765–1917)",
}
ATTR_NOTE = (" ⚠️ Отнесение к серии выполнено по ВЕДОМСТВУ и ОБЪЕКТУ (уездный землемер; "
             "выгонная земля), а не по титулу серийного издания — проверить при сверке.")
ARCH_RGB = "Российская государственная библиотека"

NOTE = ("Возвращено 08.11.2026 из отсева прогонов 02–06.10.2026 (гейт city_level). "
        "Гейт снял запись по слову «План города», не проверив принадлежность листа "
        "серийному изданию. Критерий: единица каталога — лист серии, а не изображённый "
        "объект.")


def card_url(url: str) -> str | None:
    m = re.search(r"000199_000009_(\d{9})", url)
    return f"https://search.rsl.ru/ru/record/01{m.group(1)}" if m else None


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan", action="store_true")
    apply = ap.parse_args().apply

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(SELECT).fetchall()
    print(f"к возврату: {len(rows)}")

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))
    series = {title_of(p): p["id"] for p in query_all(client, SERIES_DS)}

    done = 0
    for r in rows:
        name = r["nazvanie"]
        src = card_url(r["url"])
        extra: dict = {}
        if src:
            html = fetch(src)
            if html:
                extra = parse(html)
            time.sleep(0.3)
        full = extra.get("zagolovok_polnyi") or name
        clean = re.sub(r"^\[Атлас Смоленской губернии\]\s*", "", name).strip()

        ser_id = None
        note = NOTE
        for key, title in SERIES_FOR.items():
            if key in name and title in series:
                ser_id = series[title]
                if key != "Атлас Смоленской губернии":
                    note = NOTE + ATTR_NOTE
        props: dict = {
            "Название источника": {"title": [{"type": "text", "text": {
                "content": (clean if ser_id else name)[:200]}}]},
            "Описание": {"rich_text": rt(full[:1900])},
            "Ссылка на онлайн-архив": {"url": r["url"]},
            "Примечания": {"rich_text": rt(note)},
        }
        if ser_id:
            props["Серия / массив"] = {"relation": [{"id": ser_id}]}
        if extra.get("shelf"):
            props["Библиотечный шифр"] = {"rich_text": rt(extra["shelf"])}
        if extra.get("scale"):
            props["Масштаб (знаменатель)"] = {"number": int(extra["scale"])}
            props["Оригинальный масштаб"] = {"rich_text": rt(extra.get("scale_ctx", ""))}

        mark = "серия ✓" if ser_id else "БЕЗ серии"
        print(f"  [{mark}] {clean[:72]}")
        if extra.get("shelf") or extra.get("scale"):
            print(f"      шифр {extra.get('shelf', '—')} | масштаб {extra.get('scale', '—')}")
        if apply:
            page = retry(lambda: client.pages.create(
                parent={"database_id": CATALOG_DB}, properties=props))
            con.execute("UPDATE istochniki SET notion_id=?, status=? WHERE klyuch=?",
                        (page["id"], "возвращено из отсева 08.11.2026", r["klyuch"]))
            con.execute(
                "INSERT INTO resheniya (klyuch, reshenie, prichina, kto) VALUES (?,?,?,?)",
                (r["klyuch"], "вернуть в каталог",
                 "лист серийного издания, снят гейтом по слову «план города»", "пользователь"))
            done += 1
    if apply:
        con.commit()
        print(f"\nвнесено в каталог: {done}; в базе проставлен notion_id и журнал решений")
    else:
        print("\n(плановый прогон, ничего не внесено)")
    con.close()


if __name__ == "__main__":
    main()
