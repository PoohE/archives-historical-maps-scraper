"""
Исправление дублей-обрубков в справочнике территорий (collection 3920ba89-eabe-8179-
8e13-000be85ae51b) и перепривязка каталожных записей на канонические сущности.

Диагноз (2026-10-11): у части уездов/губерний завелись ВТОРЫЕ сущности без слова
"уезд"/"губерния" в названии (напр. "Осинский" рядом с каноническим "Осинский уезд").
Большая часть партии РГАДА ф.1354 оказалась привязана к этим обрубкам, а не к
каноническим сущностям — отсюда и путаница в фильтре Notion по "Охватываемая территория".

Логика:
1. Тянем справочник территорий, делим на canonical ("<База> уезд"/"<База> губерния")
   и bare (без суффикса, тот же Тип).
2. Для bare ищем canonical по точному совпадению базового имени + Губерния. Для
   известных случаев "город -> уезд" (напр. "Калуга" -> "Калужский") — через явный
   словарь TOWN_TO_UEZD (только для наших 4 губерний, составлен вручную по дампу).
3. Тянем ВСЕ записи каталога (decdf63c-6f64-4852-ada2-65e72c79d9bc) с непустым полем
   "Охватываемая территория", заменяем bare-ID на canonical-ID (дедуп по месту).
4. PATCH изменённых записей. Затем архивируем (archived=true, корзина Notion,
   обратимо) все bare-сущности: с заменой — потому что обезличены; без замены и без
   ссылающихся записей — потому что мусор/чужая губерния.
5. Bare-сущности без замены, но С живыми ссылающимися записями — НЕ трогаем,
   печатаем предупреждение для ручного разбора (лучше оставить баг, чем сломать данные).

Запуск:
  python scripts/maintenance/fix_territory_duplicates.py --dry-run
  python scripts/maintenance/fix_territory_duplicates.py
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TERRITORY_DS = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"
CATALOG_DS = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")

# Известные пары "название города -> базовое (адъективное) имя уезда" — только те,
# что реально встретились среди bare-сущностей в наших 4 губерниях (Калужская/
# Пермская/Смоленская/Ярославская). Не угадываем за пределами наблюдённого дампа.
TOWN_TO_UEZD = {
    "Калуга": "Калужский", "Перемышль": "Перемышльский", "Козельск": "Козельский",
    "Мосальск": "Мосальский", "Медынь": "Медынский", "Лихвин": "Лихвинский",
    "Мещовск": "Мещовский", "Таруса": "Тарусский", "Боровск": "Боровский",
    "Пермь": "Пермский", "Кунгур": "Кунгурский", "Оса": "Осинский",
    "Чердынь": "Чердынский", "Соликамск": "Соликамский", "Верхотурье": "Верхотурский",
    "Ирбит": "Ирбитский", "Смоленск": "Смоленский", "Вязьма": "Вяземский",
    "Дорогобуж": "Дорогобужский", "Духовщина": "Духовщинский", "Гжатск": "Гжатский",
    "Красный": "Краснинский", "Рославль": "Рославльский", "Сычёвка": "Сычёвский",
    "Ростов": "Ростовский", "Ярославль": "Ярославский", "Мышкин": "Мышкинский",
    "Переславль-Залесский": "Переславский", "Углич": "Угличский",
}
# Известно, что это НЕ наши уезды (чужая губерния/не имперский уездный город) — если
# среди них найдутся живые ссылки, это отдельная задача, не авто-архивировать слепо,
# но и не искать им замену.
KNOWN_SPURIOUS = {"Карачев", "Болхов", "Орёл", "Ржев", "Кизел", "Ярославец",
                  "Думиничский", "Велиж", "Сафоново"}


def load_token() -> str:
    t = os.environ.get("NOTION_TOKEN", "")
    if t:
        return t
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("NOTION_TOKEN"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TOKEN = load_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
           "Content-Type": "application/json"}


def api(method: str, url: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


def query_all(data_source_id: str, filt: dict | None = None) -> list[dict]:
    # Без явной стабильной сортировки курсорная пагинация Notion может возвращать
    # нестабильный порядок между запросами (страницы повторяются/пропускаются) —
    # поэтому сортируем по created_time и дедупим по id как защиту.
    rows, seen, cursor, pages = [], set(), None, 0
    while True:
        body = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "ascending"}]}
        if filt:
            body["filter"] = filt
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{data_source_id}/query", body)
        pages += 1
        new = 0
        for r in res.get("results", []):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
                new += 1
        if not res.get("has_more"):
            break
        if new == 0:
            print(f"  ⚠️ страница {pages}: 0 новых строк при has_more=true — похоже на цикл пагинации, останавливаюсь")
            break
        if pages > 200:
            print("  ⚠️ превышен предел 200 страниц — останавливаюсь на всякий случай")
            break
        cursor = res["next_cursor"]
        time.sleep(0.34)
    return rows


def plain_title(prop: dict) -> str:
    return "".join(x.get("plain_text", "") for x in prop.get("title", []))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN")
        sys.exit(1)

    print("Тяну справочник территорий...")
    territories = query_all(TERRITORY_DS)
    print(f"  {len(territories)} сущностей")

    canonical_by_key = {}  # (base_name, губерния_or_none) -> page_id
    bare = []  # list of dict(id, name, tip, gub)
    for p in territories:
        pr = p["properties"]
        name = plain_title(pr.get("Название", {}))
        tip = (pr.get("Тип", {}) or {}).get("select", {})
        tip = tip.get("name") if tip else None
        gub_sel = (pr.get("Губерния", {}) or {}).get("select", {})
        gub = gub_sel.get("name") if gub_sel else None
        suffix = {"Уезд": " уезд", "Губерния": " губерния"}.get(tip)
        if suffix and name.lower().endswith(suffix):
            base = name[: -len(suffix)]
            canonical_by_key[(base, gub)] = p["id"]
        elif tip in ("Уезд", "Губерния"):
            bare.append({"id": p["id"], "name": name, "tip": tip, "gub": gub})

    print(f"  canonical: {len(canonical_by_key)} | bare (обрубки): {len(bare)}")

    bare_to_canonical = {}
    unmatched_spurious, unmatched_unknown = [], []
    for b in bare:
        base = b["name"]
        key = (base, b["gub"])
        target = canonical_by_key.get(key)
        if not target and base in TOWN_TO_UEZD:
            target = canonical_by_key.get((TOWN_TO_UEZD[base], b["gub"]))
        if target:
            bare_to_canonical[b["id"]] = target
        elif base in KNOWN_SPURIOUS:
            unmatched_spurious.append(b)
        else:
            unmatched_unknown.append(b)

    print(f"  сопоставлено с каноническими: {len(bare_to_canonical)}")
    print(f"  известно чужих/мусорных (без замены): {len(unmatched_spurious)}")
    if unmatched_unknown:
        print(f"  ⚠️ НЕОПОЗНАННЫХ bare без замены: {len(unmatched_unknown)}")
        for b in unmatched_unknown:
            print(f"    {b['name']} ({b['tip']}, губ={b['gub']}) id={b['id']}")

    print("\nТяну каталог (все записи)...")
    catalog = query_all(CATALOG_DS)
    print(f"  {len(catalog)} записей всего")

    bare_ids = set(bare_to_canonical) | {b["id"] for b in unmatched_spurious} | {b["id"] for b in unmatched_unknown}
    touched = []
    for p in catalog:
        pr = p["properties"]
        rel = pr.get("Охватываемая территория", {}).get("relation", [])
        rel_ids = [r["id"] for r in rel]
        if not any(rid in bare_ids for rid in rel_ids):
            continue
        new_ids, changed = [], False
        for rid in rel_ids:
            if rid in bare_to_canonical:
                repl = bare_to_canonical[rid]
                changed = True
                if repl not in new_ids:
                    new_ids.append(repl)
            elif rid in bare_ids:
                # bare без canonical-замены (мусорный/неопознанный) — сохраняем как есть,
                # НЕ удаляем ссылку молча (решение не наше). Печатаем для внимания.
                new_ids.append(rid)
            else:
                if rid not in new_ids:
                    new_ids.append(rid)
        if changed:
            touched.append((p["id"], plain_title(pr.get("Название источника", {})), new_ids))

    print(f"\nЗаписей для перепривязки: {len(touched)}")
    updated = errors = 0
    for page_id, title, new_ids in touched:
        print(f"  {'DRY ' if a.dry_run else ''}relink: {title[:70]}")
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{page_id}",
                {"properties": {"Охватываемая территория": {"relation": [{"id": i} for i in new_ids]}}})
            updated += 1
            time.sleep(0.34)
        except RuntimeError as e:
            errors += 1
            print(f"    Ошибка: {e}")

    print(f"\nПерепривязано: {updated} | ошибок: {errors}")

    # Архивируем bare-сущности: те, что были заменены (теперь обезличены), и те
    # известно-мусорные/чужие, у которых НЕТ ни одной живой ссылающейся записи.
    # Пере-проверяем остаточные ссылки на bare среди НЕ тронутых записей (на случай
    # нескольких ссылок на одну bare-сущность из разных записей, которые мы заменили).
    still_referenced_unmatched = set()
    for p in catalog:
        rel_ids = [r["id"] for r in p["properties"].get("Охватываемая территория", {}).get("relation", [])]
        for rid in rel_ids:
            if rid in bare_ids and rid not in bare_to_canonical:
                still_referenced_unmatched.add(rid)

    to_archive = list(bare_to_canonical.keys())
    for b in unmatched_spurious:
        if b["id"] not in still_referenced_unmatched:
            to_archive.append(b["id"])
        else:
            print(f"  ⚠️ '{b['name']}' помечена мусорной, но на неё есть живые ссылки — НЕ архивирую, нужен разбор")

    print(f"\nСущностей для архивации: {len(to_archive)}")
    archived = arch_errors = 0
    for tid in to_archive:
        if a.dry_run:
            archived += 1
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{tid}", {"archived": True})
            archived += 1
            time.sleep(0.34)
        except RuntimeError as e:
            arch_errors += 1
            print(f"    Ошибка архивации {tid}: {e}")

    print(f"\n{'DRY-RUN ' if a.dry_run else ''}Архивировано bare-сущностей: {archived} | ошибок: {arch_errors}")
    if unmatched_unknown:
        print("\n⚠️ Остались неопознанные bare-сущности без решения — см. список выше, разобрать отдельно.")


if __name__ == "__main__":
    main()
