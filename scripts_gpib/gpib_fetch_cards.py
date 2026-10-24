"""ГПИБ, второй проход: чтение карточек узлов и спуск по томам.

Зачем нужен. Прогон через Яндекс (`gpib_yandex_sweep.py`) дал 574 узла, но
заголовок страницы в выдаче УСЕЧЁН до продолжения названия тома: «... за 1876 год.
- [1877].» Из такого заголовка не видно ни издания, ни территории — губерния
читалась лишь у 52 карточек из 574. Плюс выдача подмешала нерелевантное
(узел 42892 — «Приказы по корпусу жандармов»), значит гейт нужен по карточке.

Что даёт карточка `/ru/nodes/<id>` (robots запрещает только `/ru/nodes/search`):
полное библиографическое описание, заглавие, место и год издания, тип издания,
коллекции, РОДИТЕЛЬСКОЕ издание и СПИСОК ТОМОВ.

⚠️ Главное: картография прячется в названиях томов, а не издания. У родителя
79542 «Статистическое описание Калужской губернии» том 5 идёт «с приложением
8-ми генеральных поволостных планов», тома 6 и 7 — «с приложением схематической
почвенной карты». Поэтому спускаемся по детям: иначе пропустим ровно то, что
проекту и нужно.

Обход вниз делаем только у узлов, где территория наша, — иначе уйдём во весь
ГПИБ (17 336 узлов). Вверх идём на один шаг: родитель даёт название детям.

Состояние пишется после каждого узла, повторный запуск продолжает с обрыва.

Запуск:
    python -B scripts_gpib/gpib_fetch_cards.py --limit 20   # проба
    python -B scripts_gpib/gpib_fetch_cards.py
"""
from __future__ import annotations

import argparse
import csv
import html as H
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "gpib_yandex_20261021"
SRC = OUT / "gpib_cards.jsonl"
DST = OUT / "gpib_nodes.jsonl"
HOST = "http://elib.shpl.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

GUB = re.compile(r"Калужск|Смоленск|Ярославск|Пермск", re.I)
FIELDS = ["Тип издания", "Заглавие", "Сведения об ответственности", "Место издания",
          "Издательство", "Год издания", "Физическая характеристика", "Примечание",
          "Коллекции", "Родительское издание", "Серия"]
SKIP = re.compile(r"^(ИнфоРост|Войти|Главная|Указатели|Поиск|Обновления|Читателям"
                  r"|Электронная библиотека ГПИБ|version|revision|Просмотров|OK|×)")


def get(url: str, tries: int = 3) -> str | None:
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 + 3 * n)
    return None


def text_lines(doc: str) -> list[str]:
    b = re.sub(r"<script.*?</script>", "", doc, flags=re.S)
    b = re.sub(r"<style.*?</style>", "", b, flags=re.S)
    b = re.sub(r"<[^>]+>", "\n", b)
    out, prev = [], None
    for x in H.unescape(b).splitlines():
        x = x.strip()
        if not x or x == prev or SKIP.match(x):
            continue
        out.append(x)
        prev = x
    return out


def parse(node_id: str, doc: str) -> dict:
    lines = text_lines(doc)
    rec: dict[str, str] = {}
    # поля-подписи: значение идёт следующей строкой, «(N)» — счётчик указателя
    for i, line in enumerate(lines):
        if line in FIELDS and i + 1 < len(lines):
            val = lines[i + 1]
            if val not in FIELDS and not re.fullmatch(r"\(\d+\)", val):
                rec.setdefault(line, val[:600])
    # библиографическое описание — всё между подписью и первым полем
    bibl = ""
    if "Библиографическое описание" in lines:
        k = lines.index("Библиографическое описание")
        chunk = []
        for x in lines[k + 1:k + 12]:
            if x in FIELDS:
                break
            chunk.append(x)
        bibl = " ".join(chunk)[:900]
    title = ""
    m = re.search(r"<title>(.*?)</title>", doc, re.S)
    if m:
        title = re.sub(r"^ГПИБ\s*\|\s*", "", re.sub(r"\s+", " ", H.unescape(m.group(1)))).strip()
    kids = []
    for mm in re.finditer(r'href="/ru/nodes/(\d+)[^"]*"[^>]*>(.*?)</a>', doc, re.S):
        kid, kt = mm.group(1), re.sub(r"<[^>]+>", "", mm.group(2))
        kt = re.sub(r"\s+", " ", H.unescape(kt)).strip()
        if kid != node_id and kt and len(kt) > 3:
            kids.append({"node_id": kid, "zagolovok": kt[:300]})
    seen, uniq = set(), []
    for k in kids:
        if k["node_id"] not in seen:
            seen.add(k["node_id"])
            uniq.append(k)
    return {
        "node_id": node_id,
        "url": f"{HOST}/ru/nodes/{node_id}",
        "zagolovok": title,
        "zaglavie": rec.get("Заглавие", ""),
        "bibl_opisanie": bibl,
        "tip_izdaniya": rec.get("Тип издания", ""),
        "otvetstvennost": rec.get("Сведения об ответственности", ""),
        "mesto": rec.get("Место издания", ""),
        "izdatel": rec.get("Издательство", ""),
        "god": rec.get("Год издания", ""),
        "fiz_harakteristika": rec.get("Физическая характеристика", ""),
        "primechanie": rec.get("Примечание", ""),
        "kollekcii": rec.get("Коллекции", ""),
        "roditelskoe": rec.get("Родительское издание", ""),
        "deti": uniq,
        "istochnik": "ГПИБ (elib.shpl.ru)",
    }


def ours(rec: dict) -> bool:
    blob = " ".join(str(rec.get(k, "")) for k in
                    ("zagolovok", "zaglavie", "bibl_opisanie", "roditelskoe",
                     "primechanie", "mesto"))
    return bool(GUB.search(blob))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()

    seeds = [json.loads(ln)["node_id"] for ln in SRC.open(encoding="utf-8")]
    done: dict[str, dict] = {}
    if DST.exists():
        for ln in DST.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                done[r["node_id"]] = r
            except Exception:  # noqa: BLE001, S112
                continue

    queue = [n for n in seeds if n not in done]
    if args.limit:
        queue = queue[: args.limit]
    print(f"узлов-затравок {len(seeds)}, уже прочитано {len(done)}, в очереди {len(queue)}")

    added = 0
    with DST.open("a", encoding="utf-8") as fh:
        i = 0
        while queue:
            node = queue.pop(0)
            if node in done:
                continue
            i += 1
            doc = get(f"{HOST}/ru/nodes/{node}")
            if doc is None:
                print(f"  {i:>4} {node:>7} — не открылся", flush=True)
                time.sleep(args.delay)
                continue
            rec = parse(node, doc)
            done[node] = rec
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            mine = ours(rec)
            # спуск по томам — только у наших, иначе уйдём во весь ГПИБ
            if mine and not args.limit:
                for kid in rec["deti"]:
                    if kid["node_id"] not in done and kid["node_id"] not in queue:
                        queue.append(kid["node_id"])
                        added += 1
            if i % 25 == 0 or i <= 5 or mine:
                flag = "НАШ " if mine else "    "
                name = rec["zaglavie"] or rec["zagolovok"] or "—"
                print(f"  {i:>4} {node:>7} {flag}| {name[:60]} "
                      f"| детей {len(rec['deti'])} | очередь {len(queue)}", flush=True)
            time.sleep(args.delay)

    rows = list(done.values())
    for r in rows:
        r["deti_n"] = len(r.get("deti", []))
        r["deti_ids"] = ";".join(k["node_id"] for k in r.get("deti", []))
    cols = [c for c in rows[0] if c != "deti"]
    with (OUT / "gpib_nodes.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    mine = [r for r in rows if ours(r)]
    print(f"\nузлов прочитано: {len(rows)} | добрано по томам: {added}")
    print(f"по 4 губерниям: {len(mine)}")
    print(f"→ {OUT / 'gpib_nodes.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
