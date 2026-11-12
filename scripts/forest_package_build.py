"""Сводный пакет по ЛЕСНОЙ серии: всё, что есть по четырём губерниям.

Три источника сводятся в один пакет и один обзор:
  1. КАТАЛОГ Notion — что уже внесено (выгрузка baseline);
  2. РГИА ф. 380 — разбор локальных состояний прогона (`rgia380_ours/package_rgia380.jsonl`);
  3. СЕТЕВОЙ ПРОГОН по лесным терминам (`forest_sweep/hits.jsonl`) — что найдено заново.

Дедуп между источниками: по шифру (архив+фонд+опись+дело) и по URL.
В Notion ничего не пишет.

  python forest_package_build.py
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from forest_audit_store import FALSE, FOREST  # noqa: E402
from territory_gate import our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
CATALOG = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
RGIA = ROOT / "rgia380_ours" / "package_rgia380.jsonl"
SWEEP = ROOT / "forest_sweep" / "hits.jsonl"
OUT = ROOT / "forest_package"

GUBS = ["Калужская", "Смоленская", "Ярославская", "Пермская"]
NOISE = re.compile(
    r"лесопромышленн\w*\s+комплекс|расценк|заготовительн|лесозаготов|"
    r"диссертац|автореферат|учебн\w*\s+пособ",
    re.I,
)


def from_catalog() -> list[dict]:
    out = []
    if not CATALOG.exists():
        return out
    for line in CATALOG.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = json.loads(line).get("fields") or {}
        t = " ".join(
            str(f.get(k) or "") for k in ("Название источника", "Описание", "Примечания")
        )
        if not (FOREST.search(t) and not FALSE.search(t)):
            continue
        gl = our_gubernii(t)
        if not gl:
            continue
        out.append(
            {
                "src": "каталог",
                "arch": f.get("Архив [авто]") or "",
                "fond": str(f.get("Фонд") or ""),
                "opis": str(f.get("Опись") or ""),
                "delo": str(f.get("Единица хранения") or ""),
                "title": (f.get("Название источника") or "")[:200],
                "year": f.get("Год создания (нижняя)"),
                "gub": gl,
                "url": f.get("Ссылка на онлайн-архив") or "",
                "status": f.get("Статус приёмки") or "",
            }
        )
    return out


def from_rgia() -> list[dict]:
    out = []
    if not RGIA.exists():
        return out
    for line in RGIA.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("forest"):
            continue
        out.append(
            {
                "src": "РГИА ф.380 (локальный разбор)",
                "arch": "РГИА",
                "fond": "380",
                "opis": r.get("opis") or "",
                "delo": r.get("delo") or "",
                "title": (r.get("title") or "")[:200],
                "year": (r.get("date_raw") or "")[:9],
                "gub": r.get("gubernii") or [],
                "url": r.get("url") or "",
                "status": "в каталоге" if r.get("v_kataloge") else "НЕ внесено",
            }
        )
    return out


def from_sweep() -> list[dict]:
    out = []
    if not SWEEP.exists():
        return out
    seen: set[str] = set()
    for line in SWEEP.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        txt = (r.get("title") or "") + " " + (r.get("snippet") or "")
        if not FOREST.search(txt) or FALSE.search(txt) or NOISE.search(txt):
            continue
        gl = our_gubernii(txt)
        if not gl:
            continue
        u = r.get("url") or ""
        if u in seen:
            continue
        seen.add(u)
        out.append(
            {
                "src": "сетевой прогон",
                "arch": r.get("host") or "",
                "fond": "",
                "opis": "",
                "delo": r.get("rec_id") or "",
                "title": (r.get("title") or "")[:200],
                "year": None,
                "gub": gl,
                "url": u,
                "status": "кандидат, не сверен с каталогом",
            }
        )
    return out


def key(r: dict) -> str:
    if r["arch"] and r["fond"]:
        return f"{r['arch']}|{r['fond']}|{r['opis']}|{r['delo']}"
    return r["url"] or f"{r['arch']}|{r['title'][:60]}"


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)

    cat, rgia, sweep = from_catalog(), from_rgia(), from_sweep()
    print(f"из каталога: {len(cat)}")
    print(f"из РГИА ф.380: {len(rgia)}")
    print(f"из сетевого прогона: {len(sweep)}")

    merged: dict[str, dict] = {}
    for r in cat + rgia + sweep:
        k = key(r)
        if k in merged:
            merged[k].setdefault("_also", []).append(r["src"])
            continue
        merged[k] = r
    rows = list(merged.values())
    print(f"после дедупа: {len(rows)}\n")

    by_gub: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        for g in r["gub"]:
            by_gub[g][r["src"]] += 1
            by_gub[g]["всего"] += 1

    print(f"{'губерния':<14}{'всего':>8}{'каталог':>10}{'РГИА':>8}{'прогон':>9}")
    for g in GUBS:
        c = by_gub.get(g, Counter())
        print(
            f"{g:<14}{c['всего']:>8}{c['каталог']:>10}"
            f"{c['РГИА ф.380 (локальный разбор)']:>8}{c['сетевой прогон']:>9}"
        )

    with (OUT / "package_forest.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    rep = ["# Лесная серия по четырём губерниям: всё, что найдено\n"]
    rep.append(
        f"Собрано `forest_package_build.py`. Источники: каталог Notion ({len(cat)}), "
        f"локальный разбор РГИА ф. 380 ({len(rgia)}), сетевой прогон по лесным "
        f"терминам ({len(sweep)}). После дедупа по шифру и URL — **{len(rows)}**.\n"
    )
    rep.append("## По губерниям\n")
    rep.append("| Губерния | Всего | Из каталога | РГИА ф.380 | Новое из прогона |")
    rep.append("|---|---|---|---|---|")
    for g in GUBS:
        c = by_gub.get(g, Counter())
        rep.append(
            f"| {g} | {c['всего']} | {c['каталог']} | "
            f"{c['РГИА ф.380 (локальный разбор)']} | {c['сетевой прогон']} |"
        )

    arch = Counter(r["arch"] for r in rows)
    rep.append("\n## По держателям\n")
    rep.append("| Держатель | Записей |")
    rep.append("|---|---|")
    for a, c in arch.most_common(30):
        rep.append(f"| {a or '—'} | {c} |")

    newq = [r for r in rows if r["src"] == "сетевой прогон"]
    rep.append(f"\n## Новое из сетевого прогона ({len(newq)}) — не сверено с каталогом\n")
    rep.append("| Губерния | Держатель | Заголовок | Ссылка |")
    rep.append("|---|---|---|---|")
    for r in sorted(newq, key=lambda x: (x["gub"], x["arch"]))[:300]:
        rep.append(
            f"| {'; '.join(r['gub'])} | {r['arch']} | {r['title'][:120]} | {r['url']} |"
        )

    notloaded = [r for r in rows if r["status"] == "НЕ внесено"]
    if notloaded:
        rep.append(f"\n## РГИА ф. 380 — лесные дела, не внесённые в каталог ({len(notloaded)})\n")
        rep.append("| Шифр | Губерния | Даты | Заголовок |")
        rep.append("|---|---|---|---|")
        for r in notloaded:
            rep.append(
                f"| ф.{r['fond']} оп.{r['opis']} д.{r['delo']} | {'; '.join(r['gub'])} | "
                f"{r['year'] or ''} | {r['title'][:120]} |"
            )

    (OUT / "ОБЗОР_лесная_серия.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"\nпакет: {OUT / 'package_forest.jsonl'}")
    print(f"обзор: {OUT / 'ОБЗОР_лесная_серия.md'}")


if __name__ == "__main__":
    main()
