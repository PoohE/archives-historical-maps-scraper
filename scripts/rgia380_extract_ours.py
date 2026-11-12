"""РГИА ф. 380: выборка по нашим четырём губерниям из УЖЕ СОБРАННЫХ состояний описей.

Что выяснилось 09.11.2026. Прогон фонда 380 («Плановый архив Министерства
земледелия») был доведён до конца ещё в октябре: обойдены все **41 опись**,
собрано **42 563** узла, и в файлах состояния `fund380_opis_state/*.json` на каждое
дело лежит `node_metadata` с **шифром (Ф./Оп./Д.), заголовком и датами**.
То есть сетевой добор не нужен — нужен разбор локальных файлов.

Устройство фонда: описи 1–37 — **по губерниям в алфавитном порядке**, одна опись =
одна губерния (иногда несколько), а описи 38–41 — сводные:
  оп. 38 — хронологические и систематические каталоги на государственные земли и леса;
  оп. 39 — карты и планы казённых и частных земель и лесов **по ВСЕМ губерниям**;
  оп. 40 — карты и планы водных систем и чертежи гидротехнических сооружений;
  оп. 41 — чертежи зданий промышленных предприятий и сельскохозяйственных заведений.

Наши: оп. 10 Калужская, оп. 21 Пермская, оп. 28 Смоленская,
оп. 37 Черниговская-Ярославская (смешанная — нужен гейт по заголовку).

Выход: output/rgia380_ours/
  package_rgia380.jsonl   — все дела наших губерний с локаторами
  ОБЗОР_РГИА_ф380.md      — разбор: что уже в каталоге, чего не хватает

  python rgia380_extract_ours.py
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from forest_audit_store import FALSE, FOREST  # noqa: E402
from territory_gate import classify, our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
STATE = ROOT / "rgia_fund380_20261003_v3_1" / "fund380_opis_state"
CATALOG = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "rgia380_ours"

# Описи, целиком относящиеся к нашим губерниям (по аннотации описи).
OUR_OPIS = {"10": "Калужская", "21": "Пермская", "28": "Смоленская"}
# Смешанные и сводные — решает гейт по заголовку дела.
MIXED_OPIS = {"37", "38", "39", "40", "41"}


def load_state() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(STATE.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        op = str(d.get("opis_number"))
        ann = d.get("opis_annotation") or ""
        terr = d.get("territory") or ""
        for oid, md in (d.get("node_metadata") or {}).items():
            rows.append(
                {
                    "object_id": oid,
                    "opis": op,
                    "opis_territory": terr,
                    "opis_annotation": ann,
                    "fund_code": (md or {}).get("fund_code") or "",
                    "title": (md or {}).get("title") or "",
                    "date_raw": (md or {}).get("date_raw") or "",
                }
            )
    return rows


def delo_of(code: str) -> str:
    # «Ф. 380 Оп. 38 Д. 1» -> «1»
    i = code.rfind("Д.")
    return code[i + 2 :].strip() if i >= 0 else ""


def catalog_keys() -> set[tuple[str, str]]:
    """Что по ф. 380 уже в каталоге: пары (опись, дело)."""
    keys: set[tuple[str, str]] = set()
    if not CATALOG.exists():
        return keys
    for line in CATALOG.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = (json.loads(line).get("fields") or {})
        if str(f.get("Фонд") or "") != "380":
            continue
        keys.add((str(f.get("Опись") or ""), str(f.get("Единица хранения") or "")))
    return keys


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_state()
    print(f"дел в состояниях описей: {len(rows)}")

    have = catalog_keys()
    print(f"пар (опись, дело) ф.380 уже в каталоге: {len(have)}")

    ours: list[dict] = []
    for r in rows:
        op = r["opis"]
        gl: list[str] = []
        why = ""
        if op in OUR_OPIS:
            gl = [OUR_OPIS[op]]
            why = f"опись {op} целиком — {OUR_OPIS[op]} губерния (аннотация описи)"
        elif op in MIXED_OPIS:
            g = our_gubernii(r["title"])
            if g:
                gl = g
                why = f"опись {op} сводная; губерния опознана в заголовке дела"
        if not gl:
            continue
        r = dict(r)
        r["gubernii"] = gl
        r["why"] = why
        r["delo"] = delo_of(r["fund_code"])
        r["forest"] = bool(FOREST.search(r["title"]) and not FALSE.search(r["title"]))
        r["v_kataloge"] = (op, r["delo"]) in have
        r["url"] = f"https://fgurgia.ru/object/{r['object_id']}"
        ours.append(r)

    print(f"дел по нашим губерниям: {len(ours)}")
    by_op = Counter(r["opis"] for r in ours)
    new = [r for r in ours if not r["v_kataloge"]]
    print(f"из них НЕ в каталоге: {len(new)}\n")

    print(f"{'оп':>4} {'наших':>7} {'в каталоге':>11} {'новых':>7} {'лесных':>7}  аннотация")
    for op in sorted(by_op, key=lambda x: int(x) if x.isdigit() else 999):
        sel = [r for r in ours if r["opis"] == op]
        print(
            f"{op:>4} {len(sel):>7} {sum(1 for r in sel if r['v_kataloge']):>11} "
            f"{sum(1 for r in sel if not r['v_kataloge']):>7} "
            f"{sum(1 for r in sel if r['forest']):>7}  {sel[0]['opis_annotation'][:60]}"
        )

    with (OUT / "package_rgia380.jsonl").open("w", encoding="utf-8") as fh:
        for r in ours:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    gub_cnt: dict[str, Counter] = defaultdict(Counter)
    for r in ours:
        for g in r["gubernii"]:
            gub_cnt[g]["всего"] += 1
            if not r["v_kataloge"]:
                gub_cnt[g]["новых"] += 1
            if r["forest"]:
                gub_cnt[g]["лесных"] += 1

    rep = ["# РГИА ф. 380 «Плановый архив Министерства земледелия» — что у нас есть\n"]
    rep.append(
        "Собрано `rgia380_extract_ours.py` 09.11.2026 **из локальных файлов состояния** "
        "октябрьского прогона — сеть не использовалась. В `fund380_opis_state/*.json` "
        "на каждое дело лежит шифр, заголовок и даты.\n"
    )
    rep.append("## Устройство фонда\n")
    rep.append(
        f"**41 опись, {len(rows)} дел.** Описи 1–37 — по губерниям в алфавитном "
        "порядке (одна опись = одна губерния, иногда несколько); описи 38–41 — сводные.\n"
    )
    rep.append("| Опись | Дел | Содержание |")
    rep.append("|---|---|---|")
    ann_by_op: dict[str, tuple[int, str]] = {}
    for r in rows:
        op = r["opis"]
        c, a = ann_by_op.get(op, (0, r["opis_annotation"]))
        ann_by_op[op] = (c + 1, a)
    for op in sorted(ann_by_op, key=lambda x: int(x) if x.isdigit() else 999):
        c, a = ann_by_op[op]
        mark = " ⬅ **наша**" if op in OUR_OPIS or op in MIXED_OPIS else ""
        rep.append(f"| {op} | {c} | {a[:110]}{mark} |")

    rep.append("\n## Наши губернии\n")
    rep.append("| Губерния | Дел в фонде | Уже в каталоге | **Не внесено** | Лесных |")
    rep.append("|---|---|---|---|---|")
    for g, c in sorted(gub_cnt.items(), key=lambda x: -x[1]["всего"]):
        rep.append(
            f"| {g} | {c['всего']} | {c['всего'] - c['новых']} | **{c['новых']}** | {c['лесных']} |"
        )

    rep.append("\n## По описям\n")
    rep.append("| Опись | Наших дел | В каталоге | Не внесено | Лесных | Аннотация |")
    rep.append("|---|---|---|---|---|---|")
    for op in sorted(by_op, key=lambda x: int(x) if x.isdigit() else 999):
        sel = [r for r in ours if r["opis"] == op]
        rep.append(
            f"| {op} | {len(sel)} | {sum(1 for r in sel if r['v_kataloge'])} | "
            f"**{sum(1 for r in sel if not r['v_kataloge'])}** | "
            f"{sum(1 for r in sel if r['forest'])} | {sel[0]['opis_annotation'][:80]} |"
        )

    rep.append("\n## Не внесённые дела (первые 200)\n")
    rep.append("| Шифр | Губерния | Даты | Лес | Заголовок |")
    rep.append("|---|---|---|---|---|")
    for r in new[:200]:
        rep.append(
            f"| {r['fund_code']} | {'; '.join(r['gubernii'])} | {r['date_raw']} | "
            f"{'лес' if r['forest'] else ''} | {r['title'][:130]} |"
        )
    if len(new) > 200:
        rep.append(f"\n…и ещё {len(new) - 200} — полный список в `package_rgia380.jsonl`.\n")

    (OUT / "ОБЗОР_РГИА_ф380.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"\nпакет: {OUT / 'package_rgia380.jsonl'}")
    print(f"отчёт: {OUT / 'ОБЗОР_РГИА_ф380.md'}")

    verd = Counter(classify(r["title"])[0] for r in rows if r["opis"] in MIXED_OPIS)
    print(f"\nгейт по сводным описям 37–41: {dict(verd)}")


if __name__ == "__main__":
    main()
