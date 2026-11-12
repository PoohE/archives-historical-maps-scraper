"""Ревизия накопленного — по СОБСТВЕННЫМ вердиктам пакетов, а не по сверке шифров.

Первый заход (`inventory_pending.py`) дал «20 855 новых», но этой цифре верить
нельзя: у большинства пакетов нет page_id, а восстановленный по полям шифр
не совпадает с каталожным. Зато у самих пакетов есть поля решения, проставленные
при их сборке:

  * `v_kataloge`   — РГИА ф. 380: запись уже в каталоге или нет;
  * `terr_verdict` — пакеты A–F: наша / чужая / общая территория;
  * `gate`         — серийный пакет: ready / needs_human и причина;
  * `status_dobora`— добрано ли содержимое карточки.

Их и читаем. Это и есть ответ на вопрос «что собрано воедино».

  python inventory_verdicts.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"


def load(rel: str) -> list[dict]:
    p = ROOT / rel
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.open(encoding="utf-8") if ln.strip()]


def show(name: str, rows: list[dict], field: str) -> None:
    if not rows:
        print(f"\n=== {name}: файла нет")
        return
    c = Counter(str(r.get(field)) for r in rows)
    print(f"\n=== {name}: {len(rows)} записей | поле «{field}»")
    for k, v in c.most_common(8):
        print(f"    {v:6d}  {k[:70]}")


def main() -> None:
    fix_stdout()

    r380 = load("rgia380_ours/package_rgia380.jsonl")
    show("РГИА ф. 380 по нашим губерниям", r380, "v_kataloge")
    if r380:
        new = [r for r in r380 if not r.get("v_kataloge")]
        print(f"    → НЕ в каталоге: {len(new)}")
        for r in new[:4]:
            print(f"       {r.get('fund_code')} | {str(r.get('title'))[:80]}")

    for letter, fname in [
        ("A — в скоупе", "package_A_scope.jsonl"),
        ("B — листы серий", "package_B_sheets.jsonl"),
        ("C — чужая территория", "package_C_foreign.jsonl"),
        ("D — заблокировано", "package_D_blocked.jsonl"),
        ("E — после 1980", "package_E_post1980.jsonl"),
        ("F — общероссийские", "package_F_general.jsonl"),
    ]:
        rows = load(f"package_2026-11-08/{fname}")
        if rows:
            c = Counter(str(r.get("terr_verdict")) for r in rows)
            dob = Counter(str(r.get("status_dobora")) for r in rows)
            print(f"\n=== Пакет {letter}: {len(rows)}")
            print(f"    территория: {dict(c.most_common(4))}")
            print(f"    добор: {dict(dob.most_common(3))}")

    for name, fname, field in [
        ("Серийный пакет — готовые", "package_ready.jsonl", "gate"),
        ("Серийный пакет — обогащённые", "package_enriched.jsonl", "gate"),
        ("Серийный пакет — нужны глаза", "package_still_human.jsonl", "gate"),
        ("Серийный пакет — отложено по серии 11", "package_held_seriya11.jsonl", "gate"),
        ("Серийный пакет — общий", "series_package.jsonl", "gate"),
    ]:
        rows = load(f"series_package_20261107/{fname}")
        show(name, rows, field)

    forest = load("forest_package/package_forest.jsonl")
    if forest:
        c = Counter(str(r.get("v_kataloge") or r.get("status") or "?") for r in forest)
        print(f"\n=== Лесной пакет: {len(forest)} | {dict(c.most_common(5))}")
        print(f"    ключи записи: {sorted(forest[0].keys())[:12]}")

    print("\n=== Пакеты последних дней (проверены preflight)")
    for name, rel in [
        ("ГАСО-Урал", "gaso_ural/package.jsonl"),
        ("РГО", "work_2026-11-08/rgo_package.jsonl"),
        ("НЭБ", "work_2026-11-08/neb_package.jsonl"),
    ]:
        rows = load(rel)
        ours = sum(1 for r in rows if r.get("gub"))
        print(f"    {name:12s} {len(rows):6d} записей, по нашим губерниям {ours}")


if __name__ == "__main__":
    main()
