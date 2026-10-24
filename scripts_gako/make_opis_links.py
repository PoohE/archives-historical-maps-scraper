"""ГАКО: вытащить из сохранённого каталога фондов ссылки «Описи (N)» для профильных фондов.

На странице `/gako/type/stocks` у каждого фонда стоит ссылка на список его описей
(`type=custom&searchObjectType=12922&p0.t=<шифр и название>&...`). Берём её для фондов,
отобранных `select_gako_funds.py`, и выдаём пользователю готовым списком: запросы к
серверу делает он сам, мы разбираем сохранённые страницы (robots запрещает нам обход).

Запуск:
    python -B scripts_gako/make_opis_links.py C:\\arch\\gako_in \
        --selected C:\\arch\\output\\gako_parsed_20261013\\gako_funds_selected.csv \
        --out C:\\arch\\gako_in
"""
from __future__ import annotations

import argparse
import csv
import html as H
import re
import sys
import urllib.parse
from pathlib import Path

# <a ...>Описи (N)</a> ... <a class="relation-link" href="...">
PANEL = re.compile(
    r'Описи\s*\((\d+)\).*?<a class="relation-link"[^>]*href="([^"]+)"', re.S)
FUND_IN_LINK = re.compile(r"p0\.t=([^&]+)")

# ядро: эти классы берём в первую очередь
CORE_TAGS = ("межевание", "землеустройство", "съёмка/геодезия", "планы/карты/чертежи")


def fund_of(url: str) -> str | None:
    m = FUND_IN_LINK.search(url)
    if not m:
        return None
    t = urllib.parse.unquote(m.group(1))
    f = re.match(r"Ф\.\s*([А-ЯЁ]?-?\d+[а-я]?)", t)
    return f.group(1) if f else None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка с сохранёнными страницами каталога фондов")
    ap.add_argument("--selected", required=True, help="CSV профильных фондов")
    ap.add_argument("--out", required=True)
    ap.add_argument("--all", action="store_true", help="не только ядро, а все профильные")
    args = ap.parse_args()

    with open(args.selected, encoding="utf-8-sig", newline="") as fh:
        selected = list(csv.DictReader(fh))
    wanted = {}
    for r in selected:
        tags = r["tags"]
        if args.all or any(t in tags for t in CORE_TAGS):
            wanted[r["fund"]] = r
    print(f"профильных фондов выбрано: {len(wanted)} из {len(selected)}")

    found: dict[str, dict] = {}
    for f in sorted(Path(args.src).glob("*.html")):
        raw = f.read_text(encoding="utf-8", errors="replace")
        for m in PANEL.finditer(raw):
            n_opisi, url = m.group(1), H.unescape(m.group(2))
            fund = fund_of(url)
            if fund and fund in wanted and fund not in found:
                # Ссылки в каталоге бывают относительными и с НЕкодированной кириллицей
                # (а у части — с переводом строки внутри названия), поэтому собираем
                # канонический URL сами: нужны только id фонда, подпись `p0.t` избыточна.
                idm = re.search(r"p0\.d=(\d+)", url)
                if not idm:
                    continue
                oid = idm.group(1)
                canon = ("https://archive.admoblkaluga.ru/gako/search"
                         f"?type=custom&searchObjectType=12922&p0.d={oid}&p0.v={oid}"
                         "&p0.a=13292&p0.c=10&pageSize=100")
                found[fund] = {"fund": fund, "n_opisi": int(n_opisi), "url": canon,
                               "title": wanted[fund]["title"],
                               "tags": wanted[fund]["tags"]}

    missing = [f for f in wanted if f not in found]
    print(f"ссылок найдено: {len(found)}; без ссылки: {len(missing)}")
    if missing:
        print(f"  без ссылки (вероятно, у фонда 0 описей в базе): {', '.join(sorted(missing))}")

    rows = sorted(found.values(), key=lambda r: (-r["n_opisi"], r["fund"]))
    total_opisi = sum(r["n_opisi"] for r in rows)
    print(f"описей суммарно по этим фондам: {total_opisi}")

    lines = [
        "# ГАКО: ссылки на описи профильных фондов",
        "",
        f"Фондов: {len(rows)}, описей суммарно: {total_opisi}.",
        "",
        "**Как работать:** открыть ссылку → откроется список описей фонда → у каждой описи "
        "раскрыть «Дело (N)» или нажать «Открыть список в новом окне» → сохранить страницу "
        "Ctrl+S, тип «Веб-страница, полностью», в эту же папку.",
        "",
        "⚠️ Выдача режется по 100 записей; если у описи дел больше, пролистать страницы "
        "и сохранить каждую (в ссылку уже добавлен `pageSize=100`).",
        "",
        "| ✓ | фонд | описей | класс | название | ссылка |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"|  | Ф. {r['fund']} | {r['n_opisi']} | {r['tags']} | "
                     f"{r['title'][:70]} | {r['url']} |")

    f_out = Path(args.out) / "ОПИСИ_ГАКО_ссылки.md"
    f_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nсписок: {f_out}")
    for r in rows[:5]:
        print(f"  Ф. {r['fund']} ({r['n_opisi']} описей) — {r['title'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
