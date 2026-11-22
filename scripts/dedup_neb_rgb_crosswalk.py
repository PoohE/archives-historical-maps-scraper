"""Дедуп НЭБ↔РГБ: один документ, записанный в двух системах под разными URL.

Дедуп по «Ссылке на онлайн-архив» такие пары НЕ видит: URL разные. А документ один —
идентификатор НЭБ вида `000199_000009_008730959` это запись РГБ `01008730959`
(память reference_neb-id-maps-to-rgb-record). В пакете серийного улова 22.11 нашлось
17 таких пар внутри самого пакета; отдельно надо проверить, нет ли у записи НЭБ
двойника-РГБ, который уже внесён в каталог раньше.

Какую из пары оставляем: **запись РГБ**. У неё в карточке есть «Шифр хранения» и кнопка
заказа в читальный зал, то есть адрес заказа полнее (правило адреса заказа, 22.11.2026).
Снятая запись НЭБ уходит в журнал с указанием, какая запись её заменила, — отсев это
решение, а не мусор.

  python scripts/dedup_neb_rgb_crosswalk.py output/upload_2026-11-22-series/review_run
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
URL_COL = "Ссылка на онлайн-архив"
NEB = re.compile(r"/catalog/000199_000009_(\d+)")
RGB = re.compile(r"search\.rsl\.ru/[^/]+/record/(\d+)")


def rgb_key(url: str) -> str | None:
    """Номер записи РГБ без префикса «01», чтобы сравнивать с номером НЭБ.

    ⚠️ Здесь была ошибка первой версии: `lstrip("0")` снимал только ведущие нули, и
    `01002988670` давало `1002988670`, тогда как НЭБ-номер `002988670` давал `2988670` —
    ключи не совпадали, скрипт отрапортовал «дублей 0» при фактических 17. Префикс «01»
    надо снимать целиком, он часть схемы номера РГБ, а не нули выравнивания. Поймано
    только потому, что число 17 было известно из независимого подсчёта: ключ дедупа,
    который ничего не склеивает, выглядит в отчёте точно так же, как чистый пакет.
    """
    m = RGB.search(url)
    if not m:
        return None
    num = m.group(1)
    if num.startswith("01"):
        num = num[2:]
    return num.lstrip("0")


def neb_key(url: str) -> str | None:
    m = NEB.search(url)
    return m.group(1).lstrip("0") if m else None


def known_rgb_keys() -> dict[str, str]:
    """Номера записей РГБ, уже присутствующие в каталоге: выгрузка + журналы заливок."""
    keys: dict[str, str] = {}
    cands = sorted(OUT.glob("notion_catalog_*_baseline.jsonl"))
    if cands:
        base = max(cands, key=lambda p: p.stat().st_size)
        with base.open(encoding="utf-8") as f:
            for line in f:
                if "search.rsl.ru" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = (rec.get("fields") or {}).get(URL_COL) or ""
                k = rgb_key(u)
                if k:
                    keys[k] = u
    for pat in ("*/created_pages.jsonl", "*/*/created_pages.jsonl",
                "*/created.jsonl", "*/*/created.jsonl"):
        for p in OUT.glob(pat):
            for line in p.open(encoding="utf-8"):
                if "search.rsl.ru" not in line:
                    continue
                try:
                    u = json.loads(line).get("url") or ""
                except json.JSONDecodeError:
                    continue
                k = rgb_key(u)
                if k:
                    keys[k] = u
    return keys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("review_run")
    ap.add_argument("--apply", action="store_true", help="записать очищенный пакет")
    args = ap.parse_args()

    R = Path(args.review_run)
    rows = list(csv.DictReader((R / "notion_import.csv").open(encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    rev = {x["url"]: x for x in
           json.loads((R / "export_review.json").read_text(encoding="utf-8"))["records"]}

    in_pkg_rgb = {rgb_key(r[URL_COL]): r for r in rows if rgb_key(r[URL_COL])}
    known = known_rgb_keys()
    print(f"номеров РГБ уже в каталоге: {len(known)}")

    keep, drops = [], []
    for r in rows:
        nk = neb_key(r[URL_COL])
        if nk and nk in in_pkg_rgb:
            drops.append({**r, "_причина": "дубль внутри пакета: тот же документ есть "
                                           "записью РГБ",
                          "_заменяет": in_pkg_rgb[nk][URL_COL]})
            continue
        if nk and nk in known:
            drops.append({**r, "_причина": "тот же документ уже в каталоге записью РГБ",
                          "_заменяет": known[nk]})
            continue
        keep.append(r)

    print(f"\nбыло: {len(rows)}")
    print(f"  снято как НЭБ-двойник записи РГБ: {len(drops)}")
    print(f"  остаётся: {len(keep)}")
    for d in drops[:8]:
        print(f"\n  снимаю: {d[URL_COL]}")
        print(f"     {d['Название источника'][:74]}")
        print(f"     причина: {d['_причина']}")
        print(f"     остаётся: {d['_заменяет']}")

    if args.apply and drops:
        dec = R.parent / "decisions"
        dec.mkdir(parents=True, exist_ok=True)
        with (dec / "neb_rgb_doubles.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols + ["_причина", "_заменяет"])
            w.writeheader()
            w.writerows(drops)
        with (R / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(keep)
        urls = {r[URL_COL] for r in keep}
        (R / "export_review.json").write_text(json.dumps(
            {"records": [v for u, v in rev.items() if u in urls]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nзаписано: пакет {len(keep)}, журнал -> {dec / 'neb_rgb_doubles.csv'}")
    elif not args.apply:
        print("\n(проба: ничего не записано; добавьте --apply)")


if __name__ == "__main__":
    main()
