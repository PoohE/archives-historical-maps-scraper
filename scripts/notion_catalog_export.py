"""
Полная выгрузка каталога Notion (ИГИС) в CSV + JSON-снэпшот — для проверки/правки
большого объёма записей локально, без лимитов чат-инструмента Notion MCP.

Источник схемы: scripts/modules/notion_schema.json (актуальный снэпшот 70 полей, типы,
data_source_id). Пишет через официальный notion_client SDK (как import_rgvia_notion.py),
а не через MCP notion-query-data-sources — тот режет SQL на 100 строк/вызов и периодически
упирается в лимит "Query Data Source" (продуктовый лимит интеграции, не лимит самого API).

Выход (output/):
  notion_catalog_<ДАТА>.csv             — плоская таблица, одна строка = одна запись каталога
                                           (relation-поля — через "; ", списком title'ов)
  notion_catalog_<ДАТА>_baseline.jsonl  — построчный NDJSON {"page_id":.., "fields": {...}},
                                           точный снэпшот на момент выгрузки (relation — список
                                           id, не title); пишется построчно, не накопительным
                                           dict'ом — на ~114 тыс. записей накопление убивало
                                           процесс по памяти (24.10.2026). Нужен
                                           notion_catalog_sync.py для диффа правок.
  notion_catalog_<ДАТА>_relations.json  — {поле_relation: {title: page_id}} справочники целей
                                           связей — для резолва title->id при записи правок;
                                           пишется сразу, до основного прохода.

⚠️ "ID связанных источников" (self-relation на весь каталог) не разворачивается в title —
слишком дорого (справочник = сам каталог). В CSV там сырые id. Править это поле руками
в Notion, sync-скрипт его не трогает.

⚠️ **Потолок Notion API: 10 000 записей на один запрос/фильтр** (проверено 16.10.2026 —
`has_more` ЛЖЁТ и возвращает `false` ровно на 10 000-й записи, даже если в базе их больше;
воспроизводится и с явным `sorts`, это не баг курсора, а платформенный лимит). При ~19 300+
записях в каталоге один проход без фильтра теряет почти половину. Обход: делим запрос на
окна по `created_time` (`fetch_window`), рекурсивно бисектим окно, если оно само упёрлось
в 10 000 — так каждый под-запрос гарантированно ниже потолка.

Запуск:
  python scripts/notion_catalog_export.py                  # вся база (~19 300 записей, неск. минут)
  python scripts/notion_catalog_export.py --limit 300       # пробный прогон
  python scripts/notion_catalog_export.py --skip-relations  # быстрее, но relation-поля как id
"""
import argparse
import csv
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import dated_path, env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "modules" / "notion_schema.json"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
OUT_DIR = HERE.parent / "output"

SELF_RELATION_FIELDS = {"ID связанных источников"}


def ds_id(ref: str) -> str:
    """'collection://<uuid>' -> '<uuid>' (то, что ожидает notion_client в data_source_id)."""
    return ref.rsplit("//", 1)[-1]


def plain_value(prop: dict):
    """Свойство страницы Notion (форма REST-ответа) -> плоское значение для CSV/снэпшота.
    relation возвращает список id (title резолвится отдельно, см. relation_id_to_title)."""
    t = prop.get("type")
    if t == "title":
        return "".join(r["plain_text"] for r in prop["title"])
    if t == "rich_text":
        return "".join(r["plain_text"] for r in prop["rich_text"])
    if t == "number":
        return prop["number"]
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "multi_select":
        return "; ".join(o["name"] for o in prop.get("multi_select") or [])
    if t == "url":
        return prop.get("url") or ""
    if t == "date":
        d = prop.get("date")
        return d["start"] if d else ""
    if t == "relation":
        return [r["id"] for r in prop.get("relation") or []]
    if t == "rollup":
        ro = prop.get("rollup") or {}
        try:
            if ro.get("type") == "array":
                return "; ".join(str(plain_value(x)) for x in ro.get("array") or [])
            return ro.get(ro.get("type"), "")
        except Exception:  # noqa: BLE001 -- производное поле, не критично для QA
            return ""
    if t == "formula":
        fo = prop.get("formula") or {}
        return fo.get(fo.get("type"), "")
    if t == "auto_increment_id":
        return prop.get("auto_increment_id", "")
    return ""


CAP = 10_000  # документированный (эмпирически) потолок Notion на один query-запрос
RETRIES = 6  # соединение периодически рвётся (WinError 10054) -- не баг логики, see-ниже


def query_retry(client, **kwargs):
    """client.data_sources.query с повтором на разрыв соединения (ReadError/ConnectError/
    RemoteProtocolError) — под VPN соединение рвётся раз в неск. сотен запросов, не связано
    с лимитом Notion. Экспоненциальная задержка, до RETRIES попыток."""
    for attempt in range(RETRIES):
        try:
            return client.data_sources.query(**kwargs)
        except Exception:  # noqa: BLE001 -- транспортные ошибки httpx разных классов
            if attempt == RETRIES - 1:
                raise
            delay = min(2 ** attempt, 30)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def time_filter(start: datetime, end: datetime) -> dict:
    return {"and": [
        {"timestamp": "created_time", "created_time": {"on_or_after": fmt_ts(start)}},
        {"timestamp": "created_time", "created_time": {"before": fmt_ts(end)}},
    ]}


def fetch_window(client, catalog_id, start: datetime, end: datetime, logger, depth=0):
    """Генератор страниц, созданных в [start, end) — отдаёт по одной, не копит весь каталог
    в памяти (на ~19 300 записях полный список держал сырые Notion-объекты одним блоком —
    убило процесс по памяти 16.10.2026). Буфер одного окна растёт лишь до CAP, затем либо
    отдаётся целиком (окно реально закончилось), либо отбрасывается в пользу бисекции —
    не доверяет has_more на границе (см. предупреждение в докстринге модуля)."""
    buf, cursor = [], None
    while True:
        resp = query_retry(
            client, data_source_id=catalog_id, page_size=100, start_cursor=cursor,
            filter=time_filter(start, end),
            sorts=[{"timestamp": "created_time", "direction": "ascending"}],
        )
        buf.extend(resp["results"])
        if len(buf) >= CAP:
            mid = start + (end - start) / 2
            if mid <= start or mid >= end:
                raise RuntimeError(
                    f"окно {start}..{end} не бисектится дальше, а записей всё равно >= {CAP} "
                    "с одинаковым created_time -- нужен ручной разбор (другой фильтр-ось)")
            logger.info(f"{'  ' * depth}окно {start}..{end}: потолок {CAP}, бисектим на {mid}")
            # buf (до CAP полных Notion-объектов) иначе остаётся живым в приостановленном
            # фрейме на всё время работы дочерних yield from -- на глубокой рекурсии
            # (плотный кластер created_time) это копится по уровню и съедает всю RAM
            # (воспроизведено 30.10.2026: 3 падения подряд на одном окне ~18.10).
            buf = None
            yield from fetch_window(client, catalog_id, start, mid, logger, depth + 1)
            yield from fetch_window(client, catalog_id, mid, end, logger, depth + 1)
            return
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
        time.sleep(0.34)
    yield from buf


def get_bound(client, catalog_id, direction: str) -> datetime:
    resp = query_retry(client, data_source_id=catalog_id, page_size=1,
                        sorts=[{"timestamp": "created_time", "direction": direction}])
    return parse_ts(resp["results"][0]["created_time"])


def fetch_title_map(client, data_source_id, logger, label):
    """title -> page_id карта небольшого справочника (территории, архивы, типы и т.п.)."""
    titles = {}
    cursor = None
    while True:
        resp = query_retry(client, data_source_id=data_source_id, page_size=100, start_cursor=cursor)
        for page in resp["results"]:
            title_prop = next((p for p in page["properties"].values() if p["type"] == "title"), None)
            title = "".join(r["plain_text"] for r in title_prop["title"]) if title_prop else ""
            if title:
                titles[title] = page["id"]
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
        time.sleep(0.34)
    logger.info(f"справочник «{label}»: {len(titles)} записей")
    return titles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="ограничить число записей (0 = все)")
    parser.add_argument("--skip-relations", action="store_true",
                         help="не резолвить relation-справочники (быстрее; relation -> id вместо title)")
    parser.add_argument("--start", type=str, default="",
                         help="ISO-дата/время начала окна created_time (включительно), напр. 2026-10-17. "
                              "Для ручного дробления плотных периодов на устойчивые к обрыву куски.")
    parser.add_argument("--end", type=str, default="",
                         help="ISO-дата/время конца окна created_time (исключительно).")
    args = parser.parse_args()

    fix_stdout()
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN", required=True)
    client = Client(auth=token)
    logger = log("notion_catalog_export")

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    props = schema["schema"]
    catalog_id = schema["data_source_id"]
    fields = list(props.keys())
    relation_fields = {k: v for k, v in props.items() if v["type"] == "relation"}

    relation_lookup = {}
    if not args.skip_relations:
        for field, spec in relation_fields.items():
            if field in SELF_RELATION_FIELDS:
                continue
            relation_lookup[field] = fetch_title_map(client, ds_id(spec["data_source"]), logger, field)
    relation_id_to_title = {field: {v: k for k, v in m.items()} for field, m in relation_lookup.items()}

    earliest = parse_ts(args.start) if args.start else get_bound(client, catalog_id, "ascending")
    latest = (parse_ts(args.end) if args.end
              else get_bound(client, catalog_id, "descending") + timedelta(days=1))
    logger.info(f"диапазон created_time: {earliest} .. {latest}")

    out_csv = dated_path("notion_catalog", "csv", out=OUT_DIR)

    # relations.json не зависит от основного прохода — пишем сразу, чтобы выжило при убийстве
    # процесса посреди долгой выгрузки (было: ждало до самого конца вместе с baseline).
    out_rel = out_csv.with_name(out_csv.stem + "_relations.json")
    out_rel.write_text(json.dumps(relation_lookup, ensure_ascii=False, indent=2), encoding="utf-8")

    # baseline — построчный NDJSON, не накопительный dict на ~114 тыс. записей (убило процесс
    # по памяти 24.10.2026 на машине, где и без того было мало свободной RAM: тот же класс
    # бага, что чинили для CSV 16.10.2026, но для второго файла его тогда не заметили).
    out_baseline = out_csv.with_name(out_csv.stem + "_baseline.jsonl")
    seen, dupes, total = set(), 0, 0
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f, \
         out_baseline.open("w", encoding="utf-8") as fb:
        writer = csv.DictWriter(f, fieldnames=["page_id", "url", *fields])
        writer.writeheader()
        # Генератор: страницы пишутся в CSV/baseline по одной, не копятся в памяти (fetch_window).
        for page in fetch_window(client, catalog_id, earliest, latest, logger):
            page_id = page["id"]
            if page_id in seen:  # страховка на случай совпавших границ окон
                dupes += 1
                continue
            seen.add(page_id)
            row = {"page_id": page_id, "url": f"https://app.notion.com/{page_id.replace('-', '')}"}
            raw = {}
            for field in fields:
                prop = page["properties"].get(field)
                val = plain_value(prop) if prop is not None else ("" if props[field]["type"] != "relation" else [])
                if props[field]["type"] == "relation":
                    raw[field] = val  # список id — точный снэпшот для диффа
                    id2title = relation_id_to_title.get(field, {})
                    row[field] = "; ".join(id2title.get(pid, pid) for pid in val)
                else:
                    raw[field] = val
                    row[field] = val
            writer.writerow(row)
            fb.write(json.dumps({"page_id": page_id, "fields": raw}, ensure_ascii=False) + "\n")
            total += 1
            if total % 1000 == 0:
                logger.info(f"выгружено {total}")
                fb.flush()
            if args.limit and total >= args.limit:
                break
    logger.info(f"выгружено {total} (дублей по границам окон: {dupes})")

    # Стабильная копия для повторного обращения -- не искать среди файлов с меняющимся
    # именем в output/, и не на Яндекс.Диске (решение 30.10.2026 после инцидента с
    # зависшей облачной заглушкой -- Dropbox этой проблемы не создавал). Папка -- рядом
    # с материалами будущей статьи о представленности, где эта выгрузка и нужна.
    stable_dir = Path(
        r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
        r"\Представленность исторических картографических источников в федеральных"
        r" и региональных архивах и библиотеках\данные"
    )
    stable_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_csv, stable_dir / "текущий.csv")
    shutil.copyfile(out_baseline, stable_dir / "текущий_baseline.jsonl")
    shutil.copyfile(out_rel, stable_dir / "текущий_relations.json")
    logger.info(f"стабильная копия обновлена: {stable_dir}")

    print(json.dumps({"rows": total, "columns": len(fields) + 2,
                       "csv": str(out_csv), "baseline": str(out_baseline),
                       "relations": str(out_rel)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
