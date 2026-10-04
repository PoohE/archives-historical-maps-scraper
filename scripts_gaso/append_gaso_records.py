# -*- coding: utf-8 -*-
"""Накопитель записей описи ГАСО ф. 259 оп. 1, распознаваемых Claude Vision.

Распознавание идёт порциями по 4 страницы (сетка 2×2, 165 dpi — проверено, читается полностью).
Скрипт дописывает очередную порцию в JSONL, чтобы результат не терялся при обрыве и чтобы
не держать весь набор в контексте.

Запуск: python scripts_gaso/append_gaso_records.py <порция.json>
где порция.json — список записей с полями:
  n            № по порядку (колонка 1 описи)
  opis         № описи (колонка 2, обычно «1»)
  delo         № дела (колонка 3; в этой описи часто пусто — тогда "")
  title        заголовок (колонка 4) — полностью, без сокращений
  year_from    крайняя дата от (колонка 5)
  year_to      крайняя дата до (колонка 5)
  sheets       количество листов (колонка 6)
  note         примечание (колонка 10)
  uezd         уезд (раздел описи)
  svyazka      номер связки
  page         номер страницы PDF, с которой снято
"""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\gaso_f259_opis1_vision_20261004")
JSONL = OUT / "records.jsonl"

FIELDS = ("n", "opis", "delo", "title", "year_from", "year_to", "sheets",
          "note", "uezd", "svyazka", "page")


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    batch = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    seen = set()
    if JSONL.exists():
        for ln in JSONL.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                seen.add((str(r.get("uezd")), str(r.get("n"))))

    added = skipped = 0
    with JSONL.open("a", encoding="utf-8") as fh:
        for r in batch:
            key = (str(r.get("uezd")), str(r.get("n")))
            if key in seen:
                skipped += 1
                continue
            rec = {k: r.get(k, "") for k in FIELDS}
            rec["source"] = "gaso"
            rec["fund"] = "259"
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            seen.add(key)
            added += 1

    total = sum(1 for ln in JSONL.read_text(encoding="utf-8").splitlines() if ln.strip())
    print(f"добавлено {added}, пропущено дублей {skipped}, всего в наборе {total}")


if __name__ == "__main__":
    main()
