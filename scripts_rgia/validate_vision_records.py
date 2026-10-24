"""Проверить JSONL с распознанными записями описей РГИА, ф. 380.

Запуск: python -B scripts_rgia/validate_vision_records.py INPUT.jsonl [--out DIR]
Исходный JSONL не изменяется. Проверки только помечают записи для ручной сверки.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SAZHEN_PER_DESYATINA = 2400
AREA_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")
SCALE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:саж\.?|сажен(?:ей|и)?|верст(?:а|ы)?|вер\.?)|1\s*/\s*\d+)?",
    re.IGNORECASE,
)


def parse_area(value: object) -> int | None:
    """Вернуть площадь в квадратных саженях, если запись корректна."""
    if not isinstance(value, str):
        return None
    match = AREA_RE.fullmatch(value.strip())
    if match is None:
        return None
    desyatiny, sazheni = map(int, match.groups())
    if sazheni >= SAZHEN_PER_DESYATINA:
        return None
    return desyatiny * SAZHEN_PER_DESYATINA + sazheni


def add_reason(record: dict, reason: str) -> None:
    existing = record.get("needs_human_reason")
    parts = [part.strip() for part in existing.split("; ")] if isinstance(existing, str) else []
    if reason not in parts:
        record["needs_human_reason"] = f"{existing}; {reason}" if existing else reason
    record["needs_human"] = True


def read_records(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Строка {line_number}: неверный JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Строка {line_number}: ожидался объект JSON")
            # n = null допустим: в описи есть записи без № по порядку (зачёркнутые
            # «передано», поздние добавления без номера). Такие в проверке
            # сквозной нумерации не участвуют.
            if record.get("n") is not None and type(record.get("n")) is not int:
                raise ValueError(f"Строка {line_number}: поле n должно быть целым числом или null")
            if not isinstance(record.get("razdel"), str):
                raise ValueError(f"Строка {line_number}: поле razdel должно быть строкой")
            records.append(record)
    return records


def validate(records: list[dict], input_path: Path) -> dict:
    report = {
        "input": str(input_path),
        "total_records": len(records),
        "arith_checked": 0,
        "arith_ok": 0,
        "arith_failed": 0,
        "arith_failed_manual": 0,
        "arith_skipped": 0,
        "numbering_gaps": [],
        "scale_out_of_vocab": [],
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "arithmetic_limit": (
            "Во входной схеме нет независимого значения neudobnoy, поэтому равенство "
            "udobnoy + (vsego - udobnoy) == vsego тавтологично и ошибок чтения не ловит. "
            "Содержательная проверка здесь одна: vsego >= udobnoy. Запись с vsego < udobnoy "
            "помечается arith_ok=false (неудобная земля отрицательна). Пройденная проверка "
            "НЕ означает, что числа прочитаны верно, — только что они непротиворечивы."
        ),
    }
    numbers_by_section: dict[str, set[int]] = defaultdict(set)

    for record in records:
        if record["n"] is not None:
            numbers_by_section[record["razdel"]].add(record["n"])
        udobnoy = parse_area(record.get("udobnoy"))
        vsego = parse_area(record.get("vsego"))
        if udobnoy is None or vsego is None:
            # Площадь не записана или не разобрана (пусто, иной формат, несколько пар
            # площадей в одной записи) — машинно проверять нечего. Но ручную пометку
            # arith_ok=false, поставленную при чтении, НЕ затирать: иначе найденная
            # человеком ошибка молча исчезает из набора.
            if record.get("arith_ok") is not False:
                record["arith_ok"] = None
                report["arith_skipped"] += 1
            else:
                report["arith_failed_manual"] += 1
        elif vsego < udobnoy:
            # В схеме ф. 380 независимого neudobnoy нет, поэтому равенство
            # udobnoy + (vsego - udobnoy) == vsego тавтологично и ничего не ловит.
            # Единственный содержательный сигнал — ВСЕГО меньше УДОБНОЙ, то есть
            # неудобная земля вышла отрицательной: одно из чисел прочитано неверно.
            record["arith_ok"] = False
            report["arith_checked"] += 1
            report["arith_failed"] += 1
            add_reason(
                record,
                "арифметика не сходится: ВСЕГО "
                f"({vsego} саж.) меньше УДОБНОЙ ({udobnoy} саж.) — "
                f"неудобная земля отрицательна ({vsego - udobnoy} саж.)",
            )
        else:
            record["arith_ok"] = True
            report["arith_checked"] += 1
            report["arith_ok"] += 1

        scale = record.get("scale_raw", "")
        if not isinstance(scale, str) or SCALE_RE.fullmatch(scale.strip()) is None:
            report["scale_out_of_vocab"].append({"n": record["n"], "scale_raw": scale})
            add_reason(record, f"масштаб вне словаря: '{scale}'")

    for razdel, numbers in sorted(numbers_by_section.items()):
        ordered = sorted(numbers)
        for previous, current in zip(ordered, ordered[1:]):
            if current > previous + 1:
                report["numbering_gaps"].append(
                    {"razdel": razdel, "gap_after_n": previous, "next_n": current}
                )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Исходный JSONL")
    parser.add_argument("--out", type=Path, help="Папка результатов")
    args = parser.parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"нет входного файла: {input_path}")
    out_dir = args.out or input_path.parent / f"{input_path.stem}_validated_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir = out_dir.resolve()
    output_path = out_dir / input_path.name
    report_path = out_dir / "VALIDATION_REPORT.json"
    if output_path == input_path or output_path.exists() or report_path.exists():
        parser.error("результат совпадает с исходником или уже существует")

    try:
        records = read_records(input_path)
        report = validate(records, input_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8") as target:
            for record in records:
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
        with report_path.open("x", encoding="utf-8") as target:
            json.dump(report, target, ensure_ascii=False, indent=2)
            target.write("\n")
    except (OSError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    print(f"Вход: {input_path}")
    print(f"Записей: {report['total_records']}")
    print(
        "Арифметика: "
        f"проверено {report['arith_checked']}, сходится {report['arith_ok']}, "
        f"не сходится {report['arith_failed']}, пропущено {report['arith_skipped']}"
    )
    if report["arith_failed_manual"]:
        print(
            f"  + помечено вручную при чтении: {report['arith_failed_manual']} "
            "(машинно не проверяется — несколько пар площадей в записи)"
        )
    print(f"Разрывов нумерации: {len(report['numbering_gaps'])}")
    print(f"Масштабов вне словаря: {len(report['scale_out_of_vocab'])}")
    print(f"JSONL: {output_path}")
    print(f"Отчёт: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
