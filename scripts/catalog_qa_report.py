"""
QA-сверка полного экспорта каталога ИГИС (Notion) — дубли + заполненность обязательных полей.

Источник: CSV, выгруженный notion_catalog_export.py (output/notion_catalog_<ДАТА>_full.csv).
Правила — docs/../ЧЕКЛИСТ_ПРЕДЗАЛИВКИ_полей.md (18 полей, проверки на уровне набора).

Потоковый проход (csv.DictReader), не держит весь каталог тяжёлыми объектами в памяти —
на ~114 тыс. записей это важно (см. урок с OOM при выгрузке, 24.10.2026).

Запуск:
  python scripts/catalog_qa_report.py output/notion_catalog_20261024_full.csv
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout, dated_path  # noqa: E402

REQUIRED_FIELDS = [
    "Название источника", "Описание", "Архив хранения", "Тип источника", "DC Type",
    "Охватываемая территория", "Современные регионы", "Административный уровень",
    "Язык", "Место хранения", "Статус приёмки", "Статус доступа", "Автор внесения",
]


def main():
    fix_stdout()
    csv_path = Path(sys.argv[1])

    total = 0
    empty_counts = Counter()
    empty_by_archive = defaultdict(Counter)  # archive -> field -> empty count
    total_by_archive = Counter()
    accept_status = Counter()
    admin_level = Counter()
    admin_level_by_archive = defaultdict(Counter)
    dc_type = Counter()
    dc_type_by_tip = defaultdict(Counter)  # Тип источника -> DC Type counter
    language = Counter()

    locator_dupes = defaultdict(list)       # (archive, fond, opis, edhr) -> [(page_id, title),...]
    biblio_dupes = defaultdict(list)        # (archive, библ.шифр) -> [page_id,...]
    title_dupes = defaultdict(list)         # (archive, title) -> [page_id,...]
    no_locator_no_biblio = []               # page_id без фонд/опись/ед.хр. И без библ.шифра
    bracket_titles = []                     # "Название источника" содержит [ ]
    masshtab_mismatch = []                  # знаменатель заполнен, оригинальный масштаб пуст (и наоборот)
    author_suspicious = []                  # "Автор / составитель" похоже на мусор (сост./копир./техника)

    SUSPICIOUS_AUTHOR_MARKERS = ("сост.", "копир", "рукопис", "гравюр", "печат")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            total += 1
            pid = row.get("page_id", "")
            archive = (row.get("Архив хранения") or "").strip() or "(без архива)"
            total_by_archive[archive] += 1

            for field in REQUIRED_FIELDS:
                if not (row.get(field) or "").strip():
                    empty_counts[field] += 1
                    empty_by_archive[archive][field] += 1

            accept_status[(row.get("Статус приёмки") or "").strip() or "(пусто)"] += 1

            al = (row.get("Административный уровень") or "").strip() or "(пусто)"
            admin_level[al] += 1
            admin_level_by_archive[archive][al] += 1

            dct = (row.get("DC Type") or "").strip() or "(пусто)"
            dc_type[dct] += 1
            tip = (row.get("Тип источника") or "").strip() or "(пусто)"
            dc_type_by_tip[tip][dct] += 1

            language[(row.get("Язык") or "").strip() or "(пусто)"] += 1

            fond = (row.get("Фонд") or "").strip()
            opis = (row.get("Опись") or "").strip()
            edhr = (row.get("Единица хранения") or "").strip()
            biblio = (row.get("Библиотечный шифр") or "").strip()

            title_now = (row.get("Название источника") or "").strip()
            if fond and opis and edhr:
                locator_dupes[(archive, fond, opis, edhr)].append((pid, title_now))
            elif biblio:
                biblio_dupes[(archive, biblio)].append(pid)
            else:
                no_locator_no_biblio.append(pid)

            title = (row.get("Название источника") or "").strip()
            if title:
                title_dupes[(archive, title)].append(pid)
                if "[" in title or "]" in title:
                    bracket_titles.append((pid, title))

            author = (row.get("Автор / составитель") or "").strip()
            if author and any(m in author.lower() for m in SUSPICIOUS_AUTHOR_MARKERS):
                author_suspicious.append((pid, author))

            znam = (row.get("Масштаб (знаменатель)") or "").strip()
            orig_m = (row.get("Оригинальный масштаб") or "").strip()
            if znam and not orig_m:
                masshtab_mismatch.append((pid, "знаменатель есть, оригинальный пуст", znam))

            if total % 20000 == 0:
                print(f"обработано {total}", file=sys.stderr)

    all_locator_dup_groups = {k: v for k, v in locator_dupes.items() if len(v) > 1}
    # настоящий дубль = совпадает И локатор, И заголовок целиком. Совпадение ТОЛЬКО локатора
    # при разных заголовках — законный паттерн "одно дело, много строк описи" (см. чек-лист
    # п.3, ГАСО ф.814) и НЕ является дублем — не поднимать как находку.
    locator_dup_groups = {}
    locator_same_delo_diff_title = {}
    for k, v in all_locator_dup_groups.items():
        titles = {t for _, t in v}
        if len(titles) == 1:
            locator_dup_groups[k] = v
        else:
            locator_same_delo_diff_title[k] = v
    biblio_dup_groups = {k: v for k, v in biblio_dupes.items() if len(v) > 1}
    title_dup_groups = {k: v for k, v in title_dupes.items() if len(v) > 1}

    out_path = dated_path("catalog_qa_report", "md", out=csv_path.parent)
    with out_path.open("w", encoding="utf-8") as out:
        w = out.write
        w(f"# QA-сверка каталога — {csv_path.name}\n\n")
        w(f"Всего записей: **{total}**\n\n")

        w("## 1. Заполненность обязательных полей (18 полей чек-листа, где применимо)\n\n")
        w("| Поле | Пусто | % |\n|---|---:|---:|\n")
        for field in REQUIRED_FIELDS:
            n = empty_counts[field]
            w(f"| {field} | {n} | {n / total * 100:.2f}% |\n")
        w("\n")

        w("### Пустые обязательные поля по архиву (топ-30 архивов по объёму пустот)\n\n")
        archive_empty_total = Counter({a: sum(c.values()) for a, c in empty_by_archive.items()})
        w("| Архив | Всего записей | Пустых полей (сумма) | Детализация |\n|---|---:|---:|---|\n")
        for a, _ in archive_empty_total.most_common(30):
            detail = ", ".join(f"{f}={n}" for f, n in empty_by_archive[a].most_common() if n)
            w(f"| {a} | {total_by_archive[a]} | {archive_empty_total[a]} | {detail} |\n")
        w("\n")

        w("## 2. Записи без локатора (ни Фонд+Опись+Ед.хр., ни Библиотечный шифр)\n\n")
        w(f"Всего: **{len(no_locator_no_biblio)}**\n\n")
        if no_locator_no_biblio:
            w("Первые 50 page_id: " + ", ".join(no_locator_no_biblio[:50]) + "\n\n")

        w("## 3. Дедуп по ключу (Архив+Фонд+Опись+Единица хранения)\n\n")
        w(f"Групп с >1 записью, где совпадает И локатор, И заголовок целиком "
          f"(настоящий дубль — проверить и, вероятно, отклонить лишние): **{len(locator_dup_groups)}**\n\n")
        if locator_dup_groups:
            w("| Архив | Фонд | Опись | Ед.хр. | Кол-во | page_id |\n|---|---|---|---|---:|---|\n")
            for (a, fo, op, ed), items in sorted(locator_dup_groups.items(), key=lambda x: -len(x[1]))[:200]:
                pids = [pid for pid, _ in items]
                w(f"| {a} | {fo} | {op} | {ed} | {len(pids)} | {', '.join(pids)} |\n")
            w("\n")

        w(f"Групп с совпадающим локатором, но РАЗНЫМИ заголовками (НЕ дубль — законный паттерн "
          f"«одно дело, много строк описи», см. чек-лист п.3): **{len(locator_same_delo_diff_title)}**, "
          f"записей в них: **{sum(len(v) for v in locator_same_delo_diff_title.values())}** "
          f"— не требуют действия, перечень не выводится (не находка)\n\n")

        w("## 4. Дедуп по ключу (Архив+Библиотечный шифр)\n\n")
        w(f"Групп с >1 записью: **{len(biblio_dup_groups)}**\n\n")
        if biblio_dup_groups:
            w("| Архив | Библ. шифр | Кол-во | page_id |\n|---|---|---:|---|\n")
            for (a, bib), pids in sorted(biblio_dup_groups.items(), key=lambda x: -len(x[1]))[:200]:
                w(f"| {a} | {bib} | {len(pids)} | {', '.join(pids)} |\n")
            w("\n")

        w("## 5. Совпадающие заголовки в пределах одного архива (не ключ — текст)\n\n")
        w(f"Групп с одинаковым «Название источника» в одном архиве, >1 записи: "
          f"**{len(title_dup_groups)}** (это НЕ автоматически дубль — возможна серия/разные дела "
          f"с одинаковым названием; нужен ручной просмотр)\n\n")
        multi = [(k, v) for k, v in title_dup_groups.items() if len(v) >= 3]
        w(f"Из них с 3+ совпадениями (повышенный риск настоящего дубля): **{len(multi)}**\n\n")
        if multi:
            w("| Архив | Название | Кол-во | page_id (первые 10) |\n|---|---|---:|---|\n")
            for (a, t), pids in sorted(multi, key=lambda x: -len(x[1]))[:200]:
                w(f"| {a} | {t[:120]} | {len(pids)} | {', '.join(pids[:10])} |\n")
            w("\n")

        w("## 6. Статус приёмки — распределение\n\n")
        w("| Статус | Кол-во |\n|---|---:|\n")
        for k, v in accept_status.most_common():
            w(f"| {k} | {v} |\n")
        w("\n")

        w("## 7. Административный уровень — распределение (общее и по архивам)\n\n")
        w("| Уровень | Кол-во | % |\n|---|---:|---:|\n")
        for k, v in admin_level.most_common():
            w(f"| {k} | {v} | {v / total * 100:.2f}% |\n")
        w("\n")
        w("### Доля «Губерния» по архиву (подозрение на fallback — чек-лист п.9)\n\n")
        w("| Архив | Всего | Губерния | % губерния |\n|---|---:|---:|---:|\n")
        rows = []
        for a, cnt in admin_level_by_archive.items():
            tot_a = total_by_archive[a]
            gub = cnt.get("Губерния", 0)
            rows.append((a, tot_a, gub, gub / tot_a * 100 if tot_a else 0))
        for a, tot_a, gub, pct in sorted(rows, key=lambda x: -x[3]):
            if gub:
                w(f"| {a} | {tot_a} | {gub} | {pct:.1f}% |\n")
        w("\n")

        w("## 8. DC Type — распределение и согласованность с «Тип источника»\n\n")
        w("| DC Type | Кол-во |\n|---|---:|\n")
        for k, v in dc_type.most_common():
            w(f"| {k} | {v} |\n")
        w("\n")
        w("### Тип источника → какие DC Type встречаются (ищем несогласованность)\n\n")
        w("| Тип источника | DC Type (распределение) |\n|---|---|\n")
        for tip, counter in sorted(dc_type_by_tip.items(), key=lambda x: -sum(x[1].values())):
            dist = ", ".join(f"{k}={v}" for k, v in counter.most_common())
            w(f"| {tip} | {dist} |\n")
        w("\n")

        w("## 9. Язык — распределение\n\n")
        w("| Язык | Кол-во |\n|---|---:|\n")
        for k, v in language.most_common():
            w(f"| {k} | {v} |\n")
        w("\n")

        w("## 10. «Название источника» содержит квадратные скобки (правило п.1)\n\n")
        w(f"Всего: **{len(bracket_titles)}**\n\n")
        if bracket_titles:
            for pid, t in bracket_titles[:100]:
                w(f"- `{pid}`: {t[:150]}\n")
            if len(bracket_titles) > 100:
                w(f"\n... и ещё {len(bracket_titles) - 100}\n")
        w("\n")

        w("## 11. «Автор / составитель» — подозрительные значения (техника/сост./рукопись в поле автора)\n\n")
        w(f"Всего: **{len(author_suspicious)}**\n\n")
        if author_suspicious:
            for pid, a in author_suspicious[:150]:
                w(f"- `{pid}`: {a}\n")
            if len(author_suspicious) > 150:
                w(f"\n... и ещё {len(author_suspicious) - 150}\n")
        w("\n")

        w("## 12. Масштаб: знаменатель заполнен, «Оригинальный масштаб» пуст (п.14-15)\n\n")
        w(f"Всего: **{len(masshtab_mismatch)}**\n\n")
        if masshtab_mismatch:
            for pid, note, val in masshtab_mismatch[:100]:
                w(f"- `{pid}`: {note} ({val})\n")
            if len(masshtab_mismatch) > 100:
                w(f"\n... и ещё {len(masshtab_mismatch) - 100}\n")

    print(f"Отчёт готов: {out_path}")
    print(f"Всего записей: {total}")
    print(f"Дублей по локатору (фонд+опись+ед.хр.): {len(locator_dup_groups)} групп")
    print(f"Дублей по библ.шифру: {len(biblio_dup_groups)} групп")
    print(f"Без локатора вообще: {len(no_locator_no_biblio)}")
    print(f"Совпадающих заголовков (3+ в одном архиве): {len(multi)}")


if __name__ == "__main__":
    main()
