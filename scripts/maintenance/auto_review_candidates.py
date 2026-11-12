"""
Применяет уже закодированную логику приёмки (scripts/run_review.py::decide + triggers.py,
журнал docs/current/ПРАВИЛА_фильтра_ПрБ.md, 19 случаев, регресс-тест ALL PASS) к записям
каталога со статусом «кандидат» -- решение, кого можно авто-принять/авто-отклонить, а кого
оставить человеку. ТОЛЬКО анализ, ничего не пишет в Notion.

decide() спроектирована для вход-пайплайна (records_full.jsonl до заливки), здесь адаптирована
к уже занесённым записям: title=Название источника, description=Описание, place=Место хранения,
url=Ссылка на онлайн-архив, year_from/year_to=Год создания (нижняя/верхняя). ex_urls/ex_keys
пустые -- проверка "already_in_notion" не применима (запись уже там), bucket "in_notion" в
практике не встретится.

Запуск:
  python scripts/maintenance/auto_review_candidates.py output/notion_catalog_20261024_full.csv
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "modules"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

sys.path.insert(0, str(HERE))
from run_review import decide  # noqa: E402


# Баг 3 (найден 27.10.2026): scope_tag() угадывает губернию ТОЛЬКО по тексту заголовка.
# Однооблостные архивы (ГАЯО/ГАПК/ГАСО/ГАКО и их библиотеки) часто называют в карточке
# только уезд/волость/деревню, не повторяя губернию (она подразумевается самим архивом) —
# из-за этого scope_tag() даёт "unclear" на явно свои записи. Мы ТОЧНО знаем губернию по
# архиву хранения, угадывать по тексту не нужно -- подставляем название губернии в начало
# текста, который видит decide() (не трогает сами данные в Notion, только вход в функцию).
ARCHIVE_GUB_STEM = {
    "Государственный архив Ярославской области (ГАЯО)": "Ярославская губерния. ",
    "Государственный архив Пермского края (ГАПК)": "Пермская губерния. ",
    "Государственный архив Смоленской области (ГАСО)": "Смоленская губерния. ",
    "Государственный архив Калужской области (ГАКО)": "Калужская губерния. ",
    "Смоленская областная универсальная научная библиотека им. А.Т. Твардовского (СОУНБ)": "Смоленская губерния. ",
    "Калужская областная научная библиотека им. В.Г. Белинского (КОНБ)": "Калужская губерния. ",
    "Свердловская областная универсальная научная библиотека им. В. Г. Белинского (СОУНБ (Свердловск))": "Пермская губерния. ",
}


def row_to_rec(row: dict, archive: str) -> dict:
    yf = (row.get("Год создания (нижняя)") or "").strip()
    yt = (row.get("Год создания (верхняя)") or "").strip()
    title = row.get("Название источника", "")
    prefix = ARCHIVE_GUB_STEM.get(archive, "")
    if prefix and prefix.strip(". ").lower() not in title.lower().replace("ё", "е"):
        title = prefix + title
    return {
        "title": title,
        "description": row.get("Описание", ""),
        "place": row.get("Место хранения", ""),
        "url": row.get("Ссылка на онлайн-архив", ""),
        "year_from": int(yf) if yf.isdigit() else None,
        "year_to": int(yt) if yt.isdigit() else None,
    }


def main():
    fix_stdout()
    csv_path = Path(sys.argv[1])

    buckets = Counter()
    by_bucket_reason = defaultdict(list)  # (bucket, reason) -> [(pid, archive, title), ...]
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("Статус приёмки") or "").strip() != "кандидат":
                continue
            archive = (row.get("Архив хранения") or "").strip() or "(без архива)"
            rec = row_to_rec(row, archive)
            bucket, reason = decide(rec, archive, set(), set(), 1600, 1939)
            buckets[bucket] += 1
            by_bucket_reason[(bucket, reason)].append(
                (row.get("page_id", ""), archive, row.get("Название источника", "")))

    print(f"Всего «кандидат»: {sum(buckets.values())}")
    print(f"  keep (можно авто-принять): {buckets['keep']}")
    print(f"  drop (можно авто-отклонить): {buckets['drop']}")
    print(f"  review (нужен человек): {buckets['review']}")
    print(f"  in_notion (не применимо, диагностика): {buckets['in_notion']}")

    print("\n=== KEEP -- по причинам ===")
    for (b, reason), items in sorted(by_bucket_reason.items(), key=lambda x: -len(x[1])):
        if b != "keep":
            continue
        print(f"\n[{reason}] -- {len(items)}")
        archives = Counter(a for _, a, _ in items)
        for a, n in archives.most_common(8):
            print(f"    {a}: {n}")
        for pid, _a, t in items[:3]:
            print(f"    `{pid}` {t[:100]}")

    print("\n=== DROP -- по причинам ===")
    for (b, reason), items in sorted(by_bucket_reason.items(), key=lambda x: -len(x[1])):
        if b != "drop":
            continue
        print(f"\n[{reason}] -- {len(items)}")
        archives = Counter(a for _, a, _ in items)
        for a, n in archives.most_common(8):
            print(f"    {a}: {n}")
        for pid, _a, t in items[:5]:
            print(f"    `{pid}` {t[:100]}")

    out_path = csv_path.parent / "auto_review_candidates_full.tsv"
    with out_path.open("w", encoding="utf-8", newline="") as out:
        out.write("bucket\treason\tpage_id\tarchive\ttitle\n")
        for (b, reason), items in by_bucket_reason.items():
            for pid, a, t in items:
                out.write(f"{b}\t{reason}\t{pid}\t{a}\t{t}\n")
    print(f"\nПолный список -> {out_path}")


if __name__ == "__main__":
    main()
