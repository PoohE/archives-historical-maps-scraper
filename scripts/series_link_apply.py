# -*- coding: utf-8 -*-
"""Проставить привязку «Серия / массив» по отобранным карточкам (решение владельца).

Вход — `output/audit_series/кандидаты_привязки_полные.json` (подбор `series_link_candidates.py`).
Пишутся ТОЛЬКО карточки, названные в `--cards`: подбор по фразам даёт разное качество, и три
группы владелец признал бесспорными 16.11.2026 (трёхвёрстка, столистовая, «Волости и гмины
1890 года»), а наместничества, Смоленскую 1773 и МПС отправил в ручной разбор.

Защиты:
  * существующие связи записи СОХРАНЯЮТСЯ — карточка добавляется к ним, не заменяет
    (у записи может быть и издательская оболочка, и тематическая серия);
  * страница перечитывается перед записью: выгрузка от 15.11, за сутки связь могли проставить;
  * каждая удачная правка пишется строкой в журнал — приёмка идёт по нему, а не по счётчику
    (урок 16.11: мост доложил 30 созданных при шести реальных).

  python scripts/series_link_apply.py --cards "Трёхвёрстная карта" --dry-run
  python scripts/series_link_apply.py --cards "Трёхвёрстная карта,Столистовая" --apply
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import env, fix_stdout, load_env, log  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

LOG = log("series_link_apply")
WORK = ROOT / "output" / "audit_series"
FULL = WORK / "кандидаты_привязки_полные.json"
REPORT = WORK / "кандидаты_привязки.json"
JOURNAL = WORK / "привязано_2026-11-16.jsonl"
FIELD = "Серия / массив"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--cards", default="",
                    help="названия карточек через запятую (достаточно начала названия)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    # ⚠️ 16.11.2026: привязку «Трёхвёрстная карта» я признал бесспорной по четырём примерам,
    # а в полном списке из 66 оказалось 38 посторонних — дела о производстве съёмки, отчёты
    # ВТД, десятивёрстные карты, почтовые карты, планы городов. Снятие нужно в самом движке:
    # ошибочная привязка врёт о составе серии и чинится тем же инструментом, что ставилась.
    ap.add_argument("--unlink", help="json-файл со списком {page_id, card_id} — снять привязку")
    # Привязка по ИМЕННОМУ списку: отбор по фразам даёт сырьё, а решение «лист серии или
    # документ вокруг неё» принимается по правилу каталога и попадает в этот файл.
    ap.add_argument("--link-file", help="json-файл со списком {page_id, card_id} — проставить")
    a = ap.parse_args()

    if a.link_file:
        rows = json.loads(Path(a.link_file).read_text(encoding="utf-8"))
        load_env(ENV_PATH)
        c = Client(auth=env("NOTION_TOKEN"))
        ok = skip = err = 0
        with JOURNAL.open("a", encoding="utf-8") as jf:
            for r in rows:
                pid, cid = r["page_id"], r["card_id"]
                try:
                    page = retry(lambda p=pid: c.pages.retrieve(page_id=p))
                    cur = [x["id"].replace("-", "")
                           for x in (page["properties"].get(FIELD) or {}).get("relation", [])]
                    if cid in cur:
                        skip += 1
                        continue
                    retry(lambda p=pid, cu=cur, ci=cid: c.pages.update(
                        page_id=p,
                        properties={FIELD: {"relation": [{"id": x} for x in cu]
                                            + [{"id": ci}]}}))
                    ok += 1
                    jf.write(json.dumps(r, ensure_ascii=False) + chr(10))
                    jf.flush()
                    time.sleep(0.34)
                except Exception as e:  # noqa: BLE001
                    err += 1
                    LOG.info(f"  ошибка на {pid[:8]}: {type(e).__name__}: {e}")
        LOG.info(f"проставлено {ok} | уже было {skip} | ошибок {err}")
        return

    if a.unlink:
        rows = json.loads(Path(a.unlink).read_text(encoding="utf-8"))
        load_env(ENV_PATH)
        c = Client(auth=env("NOTION_TOKEN"))
        off = miss = 0
        for r in rows:
            pid, cid = r["page_id"], r["card_id"]
            page = retry(lambda p=pid: c.pages.retrieve(page_id=p))
            cur = [x["id"].replace("-", "")
                   for x in (page["properties"].get(FIELD) or {}).get("relation", [])]
            if cid not in cur:
                miss += 1
                continue
            keep = [x for x in cur if x != cid]
            retry(lambda p=pid, k=keep: c.pages.update(
                page_id=p, properties={FIELD: {"relation": [{"id": x} for x in k]}}))
            off += 1
            time.sleep(0.34)
        LOG.info(f"снято привязок: {off} | не было: {miss}")
        return

    wanted = [x.strip().lower() for x in a.cards.split(",") if x.strip()]
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    full = json.loads(FULL.read_text(encoding="utf-8"))
    names = {r["id"]: r["карточка"] for r in report}

    targets = {cid: nm for cid, nm in names.items()
               if any(nm.lower().startswith(w) or w in nm.lower() for w in wanted)}
    if not targets:
        sys.exit(f"ни одна карточка не совпала с {wanted}")
    for cid, nm in targets.items():
        LOG.info(f"карточка: {nm[:70]} — кандидатов {len(full.get(cid, []))}")

    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))
    done = ok = skip = err = 0
    jf = None if not a.apply else JOURNAL.open("a", encoding="utf-8")
    for cid, nm in targets.items():
        rows = full.get(cid, [])
        if a.limit:
            rows = rows[: a.limit]
        for r in rows:
            pid = r.get("page_id")
            if not pid:
                skip += 1
                continue
            done += 1
            if not a.apply:
                continue
            try:
                page = retry(lambda p=pid: c.pages.retrieve(page_id=p))
                cur = [x["id"].replace("-", "")
                       for x in (page["properties"].get(FIELD) or {}).get("relation", [])]
                if cid in cur:
                    skip += 1
                    continue
                retry(lambda p=pid, cu=cur: c.pages.update(
                    page_id=p,
                    properties={FIELD: {"relation": [{"id": x} for x in cu] + [{"id": cid}]}}))
                ok += 1
                jf.write(json.dumps({"page_id": pid, "карточка": nm, "card_id": cid,
                                     "название": r["название"][:120]},
                                    ensure_ascii=False) + chr(10))
                jf.flush()
                time.sleep(0.34)
            except Exception as e:  # noqa: BLE001 — продолжаем, отказ в журнал
                err += 1
                LOG.info(f"  ошибка на {pid[:8]}: {type(e).__name__}: {e}")
            if ok and ok % 25 == 0:
                LOG.info(f"  проставлено {ok}, пропущено {skip}, ошибок {err}")
    if jf:
        jf.close()
    tag = "" if a.apply else "ПРОБА — "
    LOG.info(f"{tag}к обработке {done} | проставлено {ok} | пропущено {skip} | ошибок {err}")
    if a.apply:
        LOG.info(f"журнал: {JOURNAL}")


if __name__ == "__main__":
    main()
