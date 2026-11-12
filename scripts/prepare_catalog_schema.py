"""Подготовка каталога к заливке 11.11.2026: карточка архива + два признака провенанса.

Три вещи, без которых пакеты залить нельзя, и каждая — ЗАПИСЬ, поэтому отдельным шагом:

1. **Карточка архива «ГАСО-Урал».** В справочнике «Архивы» есть только
   «ГАСО — Государственный архив Смоленской области». Пакет 3 668 дел пришёл из
   СВЕРДЛОВСКОГО архива (`opisi.gaso-ural.ru`) — это другой архив с тем же обиходным
   сокращением (память `reference_gaso-two-archives-collision`). Без отдельной карточки
   уральские дела привязались бы к смоленскому архиву.

2–3. **Свойства «Территория: источник значения» и «Административный уровень: источник
   значения»** — по образцу уже существующих «Масштаб: источник значения» и
   «Год: источник значения». Нужны потому, что у 94 % дел ГАСО-Урал территория в
   заголовке не названа и берётся по фондообразователю: без признака через месяц не
   отличить установленную территорию от выведенной, а это ровно та ловушка, из которой
   вытащили 42 615 эвристических масштабов.

  python prepare_catalog_schema.py            # показать, что будет сделано
  python prepare_catalog_schema.py --apply    # применить
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402

ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
CATALOG_DB = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ARCHIVES_DB = "a9e98744-faf8-493f-93e5-cb14c0374fd8"

ARCHIVE_ABBR = "ГАСО-Урал"
ARCHIVE_NAME = "Государственный архив Свердловской области (ГАСО-Урал)"

NEW_PROPS = {
    "Территория: источник значения": [
        "из заголовка", "по фондообразователю", "по правилу межгубернских",
        "не установлена"],
    "Административный уровень: источник значения": [
        "из заголовка", "по фондообразователю", "не установлен"],
}

#: 4. Новое значение в ДВА уже существующих select. Повод: у РГО и НЭБ год и масштаб
#: приходят из библиотечной карточки, а в словарях признаков такого источника не было —
#: без него 320 записей РГО получили бы признак «нет» при заполненном годе (поймано
#: чек-листом заполненности 11.11.2026). Одно значение на оба поля, вокабуляр не раздуваем.
ADD_OPTIONS = {
    "Год: источник значения": ["из карточки библиотеки"],
    "Масштаб: источник значения": ["из карточки библиотеки"],
}


def api(method: str, url: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {env('NOTION_TOKEN')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode()[:400]}") from e


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    load_env(ENV)

    # --- 1. карточка архива
    res = api("POST", f"https://api.notion.com/v1/databases/{ARCHIVES_DB}/query",
              {"page_size": 100})
    have = {}
    for p in res.get("results", []):
        pr = p["properties"]
        abbr = "".join(x.get("plain_text", "") for x in
                       pr.get("Аббревиатура", {}).get("rich_text", [])).strip()
        if abbr:
            have[abbr] = p["id"]
    print("1. Справочник «Архивы»")
    if ARCHIVE_ABBR in have:
        print(f"   уже есть: {ARCHIVE_ABBR} → {have[ARCHIVE_ABBR]}")
    else:
        print(f"   СОЗДАТЬ: «{ARCHIVE_ABBR}» — {ARCHIVE_NAME}")
        if args.apply:
            page = api("POST", "https://api.notion.com/v1/pages", {
                "parent": {"database_id": ARCHIVES_DB},
                "properties": {
                    "Название": {"title": [{"type": "text",
                                            "text": {"content": ARCHIVE_NAME}}]},
                    "Аббревиатура": {"rich_text": [{"type": "text",
                                                    "text": {"content": ARCHIVE_ABBR}}]},
                },
            })
            print(f"   создано → {page['id']}")

    # --- 2–3. свойства провенанса
    db = api("GET", f"https://api.notion.com/v1/databases/{CATALOG_DB}")
    props = db.get("properties") or {}
    print("\n2–3. Свойства каталога")
    to_add = {}
    for name, options in NEW_PROPS.items():
        if name in props:
            cur = [o["name"] for o in props[name].get("select", {}).get("options", [])]
            print(f"   уже есть: {name} ({' | '.join(cur)})")
        else:
            print(f"   СОЗДАТЬ select: {name} ({' | '.join(options)})")
            to_add[name] = {"select": {"options": [{"name": o} for o in options]}}
    # --- 4. новые значения в существующие select
    print("\n4. Новые значения в существующих select")
    for name, opts in ADD_OPTIONS.items():
        cur = [o["name"] for o in props.get(name, {}).get("select", {}).get("options", [])]
        miss = [o for o in opts if o not in cur]
        if not miss:
            print(f"   уже есть: {name} ← {', '.join(opts)}")
            continue
        print(f"   ДОБАВИТЬ в {name}: {', '.join(miss)}")
        to_add[name] = {"select": {"options": [{"name": o} for o in cur + miss]}}

    if to_add and args.apply:
        api("PATCH", f"https://api.notion.com/v1/databases/{CATALOG_DB}",
            {"properties": to_add})
        print(f"\n   применено изменений схемы: {len(to_add)}")

    if not args.apply:
        print("\nбез --apply ничего не изменено")


if __name__ == "__main__":
    main()
