"""
Сборка публичного catalog.csv для пакета Zenodo из полной выгрузки каталога ИГИС.

Фильтр и состав полей — решение пользователя 30.10.2026:
  - только записи со `Статус приёмки` = "принято" (кандидаты и отклонённые не публикуются);
  - поля строго по output/zenodo_package/DATA_DICTIONARY.md, без служебных/workflow-полей
    (page_id, url, Шифр записи, № п/п, Архив [авто], Код типа [авто] -- рollup-дубли или
    всегда пустые; Год обновления / проверки, Исследовательские задачи, Место создания,
    Ссылка на онлайн-архив, RMSE оцифровки (м) -- внутренние рабочие поля, не описаны в словаре).

Запуск:
  python scripts/build_zenodo_catalog.py <исходный_notion_catalog.csv>
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout, log  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "output"
ZENODO_CSV = OUT_DIR / "zenodo_package" / "catalog.csv"

EXCLUDE_FIELDS = {
    "Шифр записи", "№ п/п", "Архив [авто]", "Код типа [авто]",
    "Год обновления / проверки", "Исследовательские задачи",
    "Место создания", "Ссылка на онлайн-архив", "RMSE оцифровки (м)",
}


def main():
    fix_stdout()
    logger = log("build_zenodo_catalog")
    if len(sys.argv) < 2:
        logger.error("укажите путь к исходному notion_catalog_*.csv")
        sys.exit(1)
    src = Path(sys.argv[1])
    csv.field_size_limit(10_000_000)

    with src.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_fields = reader.fieldnames
        fields = [c for c in all_fields if c not in EXCLUDE_FIELDS and c not in ("page_id", "url")]
        logger.info(f"исходных колонок: {len(all_fields)}, в публикации: {len(fields)}")

        ZENODO_CSV.parent.mkdir(parents=True, exist_ok=True)
        total = kept = 0
        with ZENODO_CSV.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields)
            writer.writeheader()
            for row in reader:
                total += 1
                if row.get("Статус приёмки", "") != "принято":
                    continue
                writer.writerow({k: row.get(k, "") for k in fields})
                kept += 1
                if kept % 20000 == 0:
                    logger.info(f"записано {kept}")
    logger.info(f"готово: {kept}/{total} записей (принято) -> {ZENODO_CSV}")
    print(f"{{\"total_source\": {total}, \"published\": {kept}, \"columns\": {len(fields)}, "
          f"\"out\": \"{ZENODO_CSV}\"}}")


if __name__ == "__main__":
    main()
