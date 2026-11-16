"""
Пересборка очереди добора карточек из ТЕКУЩЕГО улова словаря.

Зачем. `harvest_cards.py` ходит по `output/work_2026-11-08/work.jsonl` — списку,
замороженному 08.11.2026 (3 099 строк). К 16.11 улов словаря вырос до 135 тыс. строк
и десяти новых площадок, поэтому добор по старому списку закрывает ~1 % того, что
набрано (разбор 16.11.2026). Этот скрипт собирает очередь заново: из улова, с дедупом
по живому каталогу и по журналам уже добранного.

Три источника истины на входе:
  1. `output/series_library_sweep/hits.jsonl`         — улов словаря (все прогоны);
  2. выгрузка каталога `output/notion_catalog_*_baseline.jsonl` (поле «Ссылка на
     онлайн-архив») + `created_pages.jsonl` пакетов, залитых ПОСЛЕ выгрузки;
  3. журналы добора `output/work_*/harvested*.jsonl`.

Ключ записи — не URL, а пара «держатель:идентификатор», снятая тем же `RECORD_RE`, что
и в прогоне словаря. Иначе одна и та же карточка считается разной: у РГБ ссылка живёт в
трёх формах (`search.rsl.ru/ru/record/01<9 цифр>`, `rusneb.ru/catalog/000199_000009_<9 цифр>`,
прямой handle), и дедуп по строке URL их не сводит (память `reference_neb-id-maps-to-rgb-record`).

Выход (`output/harvest_queue_<ДАТА>/`):
  queue.jsonl        — очередь добора: карточки улова, которых нет ни в каталоге, ни в журналах;
  stats.md           — таблица по площадкам: в улове / в каталоге / добрано / в очередь;
  no_route.txt       — площадки, для которых у `harvest_cards.py` НЕТ маршрута в route()
                       (их записи в очередь попадают, но добрать их пока нечем).

Запуск:
  python scripts/build_harvest_queue.py                 # вся очередь
  python scripts/build_harvest_queue.py --hosts fgurgia.ru,rgada.info
  python scripts/build_harvest_queue.py --dry-run       # только посчитать, файлы не писать
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

from series_library_sweep import RECORD_RE  # noqa: E402

HITS = ROOT / "output" / "series_library_sweep" / "hits.jsonl"
CATALOG_LINK = "Ссылка на онлайн-архив"

# Держатель для ключа записи. Имена совпадают с теми, что уже стоят в журналах добора
# (РГБ / ПрБ / НЭБ / РГО), иначе прежнее добранное не сойдётся с новым.
HOLDER = {
    "search.rsl.ru": "РГБ",
    "rusneb.ru": "НЭБ",
    "prlib.ru": "ПрБ",
    "elib.rgo.ru": "РГО",
    "elib.shpl.ru": "ГПИБ",
    "lib.permkrai.ru": "ПермьКрай",
    "primo.nlr.ru": "РНБ",
    "vivaldi.nlr.ru": "РНБ-В",
    "fgurgia.ru": "РГИА",
    "rgada.info": "РГАДА",
    "yar-archives.ru": "ГАЯО",
    "archive.perm.ru": "ГАПК",
    "goskatalog.ru": "Госкаталог",
    "gallica.bnf.fr": "Gallica",
    "catalogue.bnf.fr": "BnF",
    "davidrumsey.com": "Rumsey",
    "loc.gov": "LoC",
    "rasl.ru": "БАН",
}

# 16.11.2026: RECORD_RE в прогоне словаря ждёт `goskatalog.ru/[portal/]#!/object/id=`,
# а выдача отдаёт `web.goskatalog.ru/gk/#!/object/id=N` — поэтому ни одна карточка
# Госкаталога не засчитывалась. Здесь форма добавлена своим шаблоном; в самом прогоне
# правится отдельно, чтобы не менять поведение уже сделанных прогонов.
EXTRA_RE = {
    "goskatalog.ru": re.compile(r"goskatalog\.ru/(?:gk/|portal/)?#!/object/id=(\d+)"),
}

# РГАДА: у записи четыре разные формы ссылки, и у каждой свой уровень. Прежний единый
# шаблон снимал номер ФОНДА — 257 ссылок улова сворачивались в один ключ и фонд выглядел
# как одна карточка (разбор 16.11.2026). Порядок важен: сначала дело, потом опись.
RGADA_RE = (
    ("РГАДА-дело", re.compile(r"rgada\.info/kueh/\d+/(\d+_\d+_[\w-]+)")),
    ("РГАДА-опись", re.compile(r"rgada\.info/dela/\d+/[\w-]+/(\d+-opis_[\w-]+)")),
    ("РГАДА-опись", re.compile(r"rgada\.info/opisi/(\d+-(?:opis|ukaz)_[\w.-]+)\.pdf")),
    ("РГАДА-гео", re.compile(r"rgada\.info/geos\d*/orig/(\d+)")),
)

# Маршруты, которые route() в harvest_cards.py умеет открывать (сверено 16.11.2026).
ROUTED = {"РГБ", "ПрБ", "КП", "НЭБ", "РГО"}

RSL_ID = re.compile(r"(\d{9})$")
NEB_RGB = re.compile(r"^000199_000009_(\d{9})$")


def card_key(url: str) -> tuple[str, str] | None:
    """Ключ карточки: («держатель», «идентификатор») или None, если ссылка не карточная."""
    if "rgada.info" in url:
        for holder, rx in RGADA_RE:
            m = rx.search(url)
            if m:
                return (holder, m.group(1))
        return None          # poisk/db.php и страницы фондов — не записи
    for host, rx in {**RECORD_RE, **EXTRA_RE}.items():
        if host not in url:
            continue
        m = rx.search(url)
        if not m:
            continue
        holder = HOLDER.get(host, host)
        ident = m.group(1) if m.groups() else url
        if holder == "РГБ":
            d = RSL_ID.search(ident)
            ident = d.group(1) if d else ident
        elif holder == "НЭБ":
            # Карточка НЭБ вида 000199_000009_<9 цифр> — это та же запись РГБ.
            rgb = NEB_RGB.match(ident)
            if rgb:
                return ("РГБ", rgb.group(1))
        elif holder == "ГАЯО":
            a = re.search(r"archive(\d+)/unit/(\d+)", url)
            if a:
                ident = f"{a.group(1)}/{a.group(2)}"
        return (holder, ident)
    return None


def read_catalog_keys(verbose: bool = True) -> tuple[set[tuple[str, str]], str, int]:
    """Ключи карточек, уже стоящих в каталоге: свежая выгрузка + заливки после неё."""
    exports = sorted((ROOT / "output").glob("notion_catalog_*_baseline.jsonl"))
    if not exports:
        raise SystemExit("нет выгрузки каталога: прогнать scripts/notion_catalog_export.py")
    latest = exports[-1]
    keys: set[tuple[str, str]] = set()
    rows = 0
    for ln in latest.open(encoding="utf-8"):
        rows += 1
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        url = (rec.get("fields") or {}).get(CATALOG_LINK) or ""
        if url:
            k = card_key(url)
            if k:
                keys.add(k)
    if verbose:
        print(f"каталог: {latest.name} — {rows} записей, карточных ссылок {len(keys)}", flush=True)

    # Пакеты, залитые ПОСЛЕ выгрузки: в ней их нет, но в базе они есть.
    after = 0
    for pkg in sorted((ROOT / "output").glob("upload_*/**/created_pages.jsonl")):
        if pkg.stat().st_mtime <= latest.stat().st_mtime:
            continue
        for ln in pkg.open(encoding="utf-8"):
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            url = rec.get("url") or rec.get(CATALOG_LINK) or ""
            k = card_key(url) if url else None
            if k and k not in keys:
                keys.add(k)
                after += 1
        if verbose:
            print(f"  + заливка после выгрузки: {pkg.parent.name}", flush=True)
    return keys, latest.name, after


def read_harvested() -> set[tuple[str, str]]:
    """Ключи карточек, по которым добор уже отработал (метаданные сняты или карточка пуста)."""
    keys: set[tuple[str, str]] = set()
    for p in sorted((ROOT / "output").glob("work_*/harvested*.jsonl")):
        for ln in p.open(encoding="utf-8"):
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            st = str(rec.get("status", ""))
            if "добрано" not in st and "пуста" not in st:
                continue
            url = rec.get("url") or rec.get("istochnik_kartochki") or ""
            k = card_key(url) if url else None
            if k:
                keys.add(k)
    return keys


def read_hits() -> dict[tuple[str, str], dict]:
    """Уникальные карточки улова со сведённой по ним серией и заголовком."""
    cards: dict[tuple[str, str], dict] = {}
    lines = 0
    for ln in HITS.open(encoding="utf-8"):
        lines += 1
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        url = d.get("url", "")
        k = card_key(url)
        if not k:
            continue
        cur = cards.get(k)
        if cur is None:
            cards[k] = {
                "key": f"{k[0]}:{k[1]}",
                "holder": k[0],
                "url": url,
                "seriya": d.get("серия", ""),
                "zagolovok": d.get("title", ""),
                "snippet": d.get("snippet", ""),
                "istochnik": "прогон словаря (улов 16.11.2026)",
            }
        else:
            s = d.get("серия", "")
            if s and s not in cur["seriya"]:
                cur["seriya"] = f"{cur['seriya']}; {s}" if cur["seriya"] else s
    print(f"улов: {lines} строк → {len(cards)} уникальных карточек", flush=True)
    return cards


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", default="", help="через запятую: только эти держатели/площадки")
    ap.add_argument("--dry-run", action="store_true", help="посчитать, файлов не писать")
    args = ap.parse_args()

    cards = read_hits()
    catalog, export_name, after = read_catalog_keys()
    harvested = read_harvested()
    print(f"журналы добора: {len(harvested)} отработанных карточек", flush=True)
    if after:
        print(f"  (+{after} из заливок после выгрузки)", flush=True)

    only = {h.strip() for h in args.hosts.split(",") if h.strip()}
    in_cat = Counter()
    in_harv = Counter()
    total = Counter()
    queue: list[dict] = []
    for k, rec in cards.items():
        holder = k[0]
        total[holder] += 1
        if k in catalog:
            in_cat[holder] += 1
            continue
        if k in harvested:
            in_harv[holder] += 1
            continue
        if only and holder not in only and not any(h in rec["url"] for h in only):
            continue
        rec["route"] = "есть" if holder in ROUTED else "НЕТ"
        queue.append(rec)

    q_by_holder = Counter(r["holder"] for r in queue)
    rows = []
    for holder in sorted(total, key=lambda h: -total[h]):
        rows.append((holder, total[holder], in_cat[holder], in_harv[holder],
                     q_by_holder[holder], "есть" if holder in ROUTED else "НЕТ"))

    head = f"{'держатель':<13}{'в улове':>9}{'в каталоге':>12}{'добрано':>9}{'в очередь':>11}  маршрут"
    print()
    print(head)
    for r in rows:
        print(f"{r[0]:<13}{r[1]:>9}{r[2]:>12}{r[3]:>9}{r[4]:>11}  {r[5]}")
    print(f"{'ИТОГО':<13}{sum(total.values()):>9}{sum(in_cat.values()):>12}"
          f"{sum(in_harv.values()):>9}{len(queue):>11}")
    no_route = sorted({r["holder"] for r in queue if r["route"] == "НЕТ"})
    if no_route:
        print(f"\nбез маршрута в route(): {', '.join(no_route)} — "
              f"{sum(q_by_holder[h] for h in no_route)} карточек добрать нечем")

    if args.dry_run:
        print("\n--dry-run: файлы не записаны")
        return

    out = ROOT / "output" / f"harvest_queue_{date.today():%Y%m%d}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "queue.jsonl").open("w", encoding="utf-8") as f:
        for rec in queue:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with (out / "stats.md").open("w", encoding="utf-8") as f:
        f.write(f"# Очередь добора карточек — {date.today():%d.%m.%Y}\n\n")
        f.write(f"Улов: `{HITS.name}`, {len(cards)} уникальных карточек.\n")
        f.write(f"Каталог: `{export_name}` (+{after} из заливок после выгрузки).\n")
        f.write(f"Журналы добора: {len(harvested)} отработанных карточек.\n\n")
        f.write("| держатель | в улове | в каталоге | добрано | в очередь | маршрут |\n")
        f.write("|---|---:|---:|---:|---:|---|\n")
        for r in rows:
            f.write(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |\n")
        f.write(f"| **итого** | **{sum(total.values())}** | **{sum(in_cat.values())}** | "
                f"**{sum(in_harv.values())}** | **{len(queue)}** | |\n")
    (out / "no_route.txt").write_text("\n".join(no_route) + "\n", encoding="utf-8")
    print(f"\nочередь: {out / 'queue.jsonl'} — {len(queue)} карточек")
    print(f"сводка:  {out / 'stats.md'}")


if __name__ == "__main__":
    main()
