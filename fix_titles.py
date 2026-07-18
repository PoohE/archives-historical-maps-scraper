"""
Постобработка results.csv: исправить слипшиеся слова в заголовках.
Запуск: python fix_titles.py output/cloud/results.csv
"""
import csv
import re
import sys
from pathlib import Path


def fix_title(title: str) -> str:
    """Добавляет пробел перед заглавной буквой если она идёт после строчной/цифры."""
    # Кириллица: вставляем пробел перед заглавной буквой если предыдущий символ — строчная/цифра
    fixed = re.sub(r'([а-яёa-z0-9])([А-ЯЁA-Z])', r'\1 \2', title)
    # Убираем множественные пробелы
    fixed = re.sub(r' {2,}', ' ', fixed).strip()
    return fixed


def process(input_path: Path) -> Path:
    output_path = input_path.parent / (input_path.stem + "_fixed.csv")
    fixed_count = 0

    with (open(input_path, encoding="utf-8-sig", newline="") as fin,
          open(output_path, "w", encoding="utf-8-sig", newline="") as fout):
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            original = row["Название"]
            row["Название"] = fix_title(original)
            if row["Название"] != original:
                fixed_count += 1
            writer.writerow(row)

    print(f"Обработано строк: {sum(1 for _ in open(input_path, encoding='utf-8-sig')) - 1}")
    print(f"Исправлено заголовков: {fixed_count}")
    print(f"Результат: {output_path}")
    return output_path


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/cloud/results.csv")
    if not path.exists():
        print(f"Файл не найден: {path}")
        sys.exit(1)
    process(path)
