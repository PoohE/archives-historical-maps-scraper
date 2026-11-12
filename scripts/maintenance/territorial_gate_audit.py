"""
Территориальный гейт: повторная сверка ВСЕГО каталога (113 986 записей) правилами
scripts_review/false_carto.py (дозревал 20-24.10, часть записей внесена ДО того, как
правила окрепли -- могли проскочить старые ловушки).

Проверяет "Название источника" каждой записи со статусом приёмки != "отклонено" тремя
функциями гейта: is_false_carto (слово "карта/план" не о карте), alien_hit (назван чужой
топоним), not_a_place (название губернии -- не топоним: престол/сословие/фамилия/судно/
воинская часть/ж.д./Перемышль). Группирует совпадения по (тип, конкретный текст совпадения)
в кластеры -- один и тот же паттерн часто даёт десятки записей, разбирать по кластеру,
не по записи.

Запуск:
  python scripts/maintenance/territorial_gate_audit.py output/notion_catalog_20261024_full.csv
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE.parent / "scripts_review"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

import false_carto as fc  # noqa: E402


def main():
    fix_stdout()
    csv_path = Path(sys.argv[1])

    clusters = defaultdict(list)  # (kind, matched_text_lower) -> [(page_id, archive, title), ...]
    total = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            status = (row.get("Статус приёмки") or "").strip()
            if status == "отклонено":
                continue
            title = (row.get("Название источника") or "").strip()
            if not title:
                continue
            total += 1
            pid = row.get("page_id", "")
            archive = (row.get("Архив хранения") or "").strip() or "(без архива)"

            hit = fc.is_false_carto(title)
            if hit:
                clusters[("FALSE_CARTO", hit.lower())].append((pid, archive, title))
                continue  # одно совпадение на запись достаточно для кластеризации

            hit = fc.alien_hit(title)
            if hit:
                clusters[("ALIEN_TERRITORY", hit.lower())].append((pid, archive, title))
                continue

            hit = fc.not_a_place(title)
            if hit:
                clusters[("NOT_A_PLACE", hit.lower())].append((pid, archive, title))

    print(f"Проверено записей (без отклонённых): {total}")
    print(f"Кластеров совпадений: {len(clusters)}")
    total_hits = sum(len(v) for v in clusters.values())
    print(f"Всего записей с совпадением: {total_hits}")
    print()

    out_path = csv_path.parent / "territorial_gate_audit_clusters.tsv"
    with out_path.open("w", encoding="utf-8", newline="") as out:
        out.write("kind\tmatched_text\tcount\tarchives\tsample_titles\tpage_ids\n")
        for (kind, text), items in sorted(clusters.items(), key=lambda x: -len(x[1])):
            archives = sorted({a for _, a, _ in items})
            samples = [t for _, _, t in items[:3]]
            pids = [p for p, _, _ in items]
            out.write(f"{kind}\t{text}\t{len(items)}\t{' | '.join(archives)}\t"
                      f"{' ||| '.join(samples)}\t{','.join(pids)}\n")
    print(f"Полный разбор по кластерам -> {out_path}")

    print("\nТоп кластеров (по числу записей):")
    for (kind, text), items in sorted(clusters.items(), key=lambda x: -len(x[1]))[:40]:
        archives = sorted({a for _, a, _ in items})
        print(f"\n[{kind}] {text!r} -- {len(items)} записей, архивы: {', '.join(archives)[:120]}")
        for _pid, _a, t in items[:3]:
            print(f"    {t[:110]!r}")


if __name__ == "__main__":
    main()
