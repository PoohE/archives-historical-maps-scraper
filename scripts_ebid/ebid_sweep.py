"""ЭБИД (Электронная библиотека исторических документов): прогон по 4 губерниям.

Разведка 21.10.2026 — случай редкий и удобный:
  * `robots.txt` ОТСУТСТВУЕТ (404) → запретов нет вовсе, в т.ч. на поиск;
  * движок тот же, что у ГПИБ (ИнфоРост): карточки `/ru/nodes/<id>`, поиск
    `/ru/nodes/search`. Поэтому карточки разбираем парсером ГПИБ, не плодя второй.
  * ⚠️ Параметр поиска — `query` (не `q`, не `text`, не `search` — проверено перебором:
    все остальные дают ноль). Пагинация `&page=N`, по 50 узлов на страницу.
  * ⚠️ По умолчанию поиск идёт И ПО ПОЛНЫМ ТЕКСТАМ: «Калужская губерния» даёт ссылку
    на страницу 200, то есть ~10 000 результатов — это каждое упоминание в текстах
    документов. С явными `search_in_metadata=1&search_in_texts=0` остаётся 3 страницы
    (~150) — описания изданий, что нам и нужно. Полнотекстовый режим не берём: он
    вытащит любое дело, где слово встретилось в тексте.

Запуск:
    python -B scripts_ebid/ebid_sweep.py --phase sweep --limit 4
    python -B scripts_ebid/ebid_sweep.py --phase all
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_gpib"))
from gpib_fetch_cards import parse as parse_node  # noqa: E402  (движок один — ИнфоРост)

OUT = ROOT / "output" / "ebid_20261021"
HOST = "https://docs.historyrussia.org"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 1.5
PER_PAGE_MAX_PAGES = 12  # запас: реально 3 страницы при поиске по метаданным

GUBERNII = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
GUB_IM = ["Калужская", "Смоленская", "Ярославская", "Пермская"]
KINDS = [
    "карта {g} губернии",
    "атлас {g} губернии",
    "план {g} губернии",
    "межевание {g} губернии",
    "статистическое описание {g} губернии",
    "список населенных мест {g} губернии",
    "материалы для географии и статистики {g} губернии",
    "топографическое описание {g} губернии",
    "военно-статистическое обозрение {g} губернии",
    "памятная книжка {g} губернии",
]
GUB_RE = re.compile(r"Калужск|Смоленск|Ярославск|Пермск", re.I)


def queries() -> list[str]:
    out = [k.format(g=g) for g in GUBERNII for k in KINDS]
    out += [f"{g} губерния" for g in GUB_IM]  # общий запрос по метаданным
    return out


def get(url: str, tries: int = 3) -> str | None:
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 + 3 * n)
    return None


def search(q: str, page: int = 0) -> tuple[list[str], int]:
    """Узлы на странице и максимальный номер страницы из пагинации."""
    params = {"query": q, "search_in_metadata": "1", "search_in_texts": "0"}
    if page:
        params["page"] = str(page)
    doc = get(f"{HOST}/ru/nodes/search?" + urllib.parse.urlencode(params))
    if not doc:
        return [], 1
    ids = sorted(set(re.findall(r"/ru/nodes/(\d+)", doc)), key=int)
    pages = {int(x) for x in re.findall(r"[?&]page=(\d+)", doc)}
    return ids, (max(pages) if pages else 1)


def phase_sweep(limit: int) -> int:
    dst = OUT / "ebid_hits.jsonl"
    found: dict[str, dict] = {}
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                found[r["node_id"]] = r
            except Exception:  # noqa: BLE001, S112
                continue
    qs = queries()
    if limit:
        qs = qs[:limit]
    print(f"запросов: {len(qs)} | уже собрано: {len(found)}")
    for i, q in enumerate(qs, 1):
        ids, last = search(q)
        new = 0
        for nid in ids:
            if nid not in found:
                found[nid] = {"node_id": nid, "url": f"{HOST}/ru/nodes/{nid}", "zapros": q}
                new += 1
        time.sleep(DELAY)
        for page in range(2, min(last, PER_PAGE_MAX_PAGES) + 1):
            ids_p, _ = search(q, page)
            for nid in ids_p:
                if nid not in found:
                    found[nid] = {"node_id": nid, "url": f"{HOST}/ru/nodes/{nid}", "zapros": q}
                    new += 1
            time.sleep(DELAY)
        print(f"  {i:>3}/{len(qs)} {q[:50]:<52} стр.{min(last, PER_PAGE_MAX_PAGES)} "
              f"+{new} (всего {len(found)})", flush=True)
    with dst.open("w", encoding="utf-8") as fh:
        for r in sorted(found.values(), key=lambda x: int(x["node_id"])):
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nуникальных узлов: {len(found)}")
    return len(found)


def phase_cards(limit: int) -> int:
    src = OUT / "ebid_hits.jsonl"
    dst = OUT / "ebid_nodes.jsonl"
    seeds = [json.loads(ln) for ln in src.open(encoding="utf-8")]
    done: set[str] = set()
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["node_id"])
            except Exception:  # noqa: BLE001, S112
                continue
    todo = [r for r in seeds if r["node_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"узлов всего {len(seeds)}, прочитано {len(done)}, в работе {len(todo)}")
    with dst.open("a", encoding="utf-8") as fh:
        for i, it in enumerate(todo, 1):
            doc = get(it["url"])
            if doc is None:
                print(f"  {i:>4} {it['node_id']:>8} — не открылся", flush=True)
                time.sleep(DELAY)
                continue
            rec = parse_node(it["node_id"], doc)
            rec["zapros"] = it.get("zapros", "")
            rec["istochnik"] = "ЭБИД (docs.historyrussia.org)"
            blob = " ".join(str(rec.get(k, "")) for k in
                            ("zagolovok", "zaglavie", "bibl_opisanie", "roditelskoe",
                             "primechanie", "mesto"))
            rec["nash_region"] = "да" if GUB_RE.search(blob) else ""
            rec["deti_n"] = len(rec.get("deti", []))
            rec["deti_ids"] = ";".join(k["node_id"] for k in rec.get("deti", []))
            rec.pop("deti", None)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 20 == 0 or i <= 5 or rec["nash_region"]:
                flag = "НАШ " if rec["nash_region"] else "    "
                name = rec.get("zaglavie") or rec.get("zagolovok") or "—"
                print(f"  {i:>4}/{len(todo)} {it['node_id']:>8} {flag}| {name[:60]}",
                      flush=True)
            time.sleep(DELAY)
    rows = [json.loads(ln) for ln in dst.open(encoding="utf-8")]
    if rows:
        cols = list(rows[0])
        with (OUT / "ebid_nodes.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    mine = sum(1 for r in rows if r.get("nash_region"))
    print(f"\nузлов прочитано: {len(rows)} | по 4 губерниям: {mine}")
    print(f"→ {OUT / 'ebid_nodes.csv'}")
    return len(rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["sweep", "cards", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase in ("sweep", "all"):
        print("=== ФАЗА 1: поиск по метаданным ЭБИД ===")
        phase_sweep(args.limit)
    if args.phase in ("cards", "all"):
        print("\n=== ФАЗА 2: чтение карточек ===")
        phase_cards(args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
