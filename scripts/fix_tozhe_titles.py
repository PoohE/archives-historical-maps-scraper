"""Починка заголовков, собранных из конвенции описи «То же».

Дефект найден 11.11.2026 сразу после заливки ГАСО-Урал, проверкой собственного результата.

В описях ф. 64 заголовок не повторяется: строка пишется как «То же, автор Мудрин» —
то есть хвост ЗАМЕНЯЕТ параметр предыдущего заголовка, а не дописывается к нему.
Сборщик пакета склеивал базу и хвост через « — », и получалось:

    «Топографический журнал Екатеринбургского округ. Автор Неулыбин. — автор Мудрин»

Здесь названы ДВА автора, и первый — чужой: дело д. 3 составил Мудрин, а Неулыбин
значится потому, что он автор базового д. 1. Таких записей 331 из 598 внесённых.

Правило починки: если хвост начинается с параметра, который есть и в базе, —
значение параметра в базе ЗАМЕНЯЕТСЯ хвостом; если хвост «"-"» или «то же» —
он просто отбрасывается (строка описи повторяет предыдущую целиком).

Заголовки правятся только у записей, внесённых ЭТИМ прогоном (дата внесения
2026-11-11, архив ГАСО-Урал) — чужие карточки не трогаем.

  python fix_tozhe_titles.py            # показать, что изменится
  python fix_tozhe_titles.py --apply    # применить
"""

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

RUN = (Path(__file__).resolve().parents[1] / "output" / "upload_2026-11-11"
       / "gaso_review_run")

#: параметр → как он выглядит в базовом заголовке (что заменяем)
PARAM_PATTERNS = [
    # «автор Мудрин» / «автора Подкорытова» → заменить «Автор Неулыбин.» в базе
    (re.compile(r"^автор[а]?\s+", re.I),
     re.compile(r"[,.]?\s*автор[а]?\s+[^.,;]+\.?", re.I)),
    # «ряд XXXI, лист-2» / «рзд XXXI лист 2» → заменить «ряд XXX, лист-1» в базе
    (re.compile(r"^(?:ряд|рзд)\b", re.I),
     re.compile(r"[,.]?\s*-?\s*(?:ряд|рзд)\b[^.;]*", re.I)),
    # «лист-3» → заменить «лист-1» в базе
    (re.compile(r"^лист", re.I),
     re.compile(r"[,.]?\s*лист[\s-]*[^\s.,;]+", re.I)),
]

#: Кавычка-повтор в графе описи: «"- Атманский» значит «автор Атманский» — графа
#: «автор» повторяется знаком, а фамилия новая. Найдено 11.11.2026: таких 42 из 331.
#: ⚠️ «"- "+"» — повтор повтора (автор тот же, что строкой выше): фамилию назвать
#: нельзя, такие остаются с пометкой на сверку.
#: знак повтора пишется по-разному: «"-», «-», «—», «–» — и за ним фамилия
DITTO_AUTHOR = re.compile(
    r'^["«]?\s*[-—–]+\s*["»]?\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*$')
AUTHOR_IN_BASE = re.compile(r"[,.]?\s*автор[а]?\s+[^.,;]+\.?", re.I)
#: хвост означает «строка описи повторяет предыдущую целиком»
SAME = re.compile(r'^\s*(?:"?-"?|то\s*же|-{1,2})\s*$', re.I)


def fix_title(title: str) -> str:
    if " — " not in title:
        return title
    base, tail = title.split(" — ", 1)
    base, tail = base.strip(), tail.strip()
    if SAME.match(tail):
        return base
    m = DITTO_AUTHOR.match(tail)
    if m and AUTHOR_IN_BASE.search(base):
        cleaned = AUTHOR_IN_BASE.sub("", base).strip().rstrip(",;").strip()
        sep = " " if cleaned.endswith((".", ")")) else ". "
        return f"{cleaned}{sep}Автор {m.group(1)}"
    for tail_pat, base_pat in PARAM_PATTERNS:
        if tail_pat.match(tail):
            cleaned = base_pat.sub("", base).strip().rstrip(",;").strip()
            if cleaned and cleaned != base:
                sep = " " if cleaned.endswith((".", ")")) else ". "
                return f"{cleaned}{sep}{tail[0].upper()}{tail[1:]}"
            break
    # Параметр не распознан. Склейку за заголовок не выдаём: хвост остаётся в скобках
    # дословно, как в описи, чтобы было видно, что заголовок требует сверки.
    return f"{base} [по описи: {tail}]"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    path = RUN / "notion_import.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    cols = list(rows[0].keys())
    changed = 0
    for r in rows:
        new = fix_title(r["Название источника"])
        if new != r["Название источника"]:
            if changed < 14:
                print(f"  ф.{r['Фонд']} д.{r['Единица хранения']}")
                print(f"     было:  {r['Название источника'][:104]}")
                print(f"     стало: {new[:104]}")
            r["Название источника"] = new
            changed += 1
    print(f"\nзаголовков исправлено: {changed} из {len(rows)}")

    if not args.apply:
        print("без --apply файл не изменён")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"→ {path}\nдалее: прогон моста с --update по порциям")


if __name__ == "__main__":
    main()
