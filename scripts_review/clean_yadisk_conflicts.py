"""Уборка конфликтных копий Яндекс.Диска («(копия с компьютера NAME)»).

Я.Диск плодит такие файлы, когда в одной синхронизируемой папке работают две машины
или две сессии. 13.10.2026 за один день он развёл так PROGRESS.md, журнал заданий Винки
и чекпойнт ГАСО — каждый раз правка уходила в копию, а основной файл подменялся.

Классификация и действия:
  идентичен основному      → копию удалить (мусор);
  основного НЕТ            → копию переименовать в основной (она и есть файл);
  РАЗЛИЧАЕТСЯ              → НЕ удалять: перенести в archive/ и показать, что крупнее.

⚠️ Запускать, когда синхронизация на ПАУЗЕ, иначе Я.Диск создаст копии заново.

Запуск:
    python -B scripts_review/clean_yadisk_conflicts.py .            # показать, ничего не делать
    python -B scripts_review/clean_yadisk_conflicts.py . --apply    # выполнить
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

MARK = re.compile(r"\s*\(копия с компьютера [^)]+\)(\s*\(\d+\))?")
# archive — наш же карантин: без него повторный запуск «чинит» уже убранное
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "archive"}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--apply", action="store_true",
                    help="выполнить БЕЗОПАСНУЮ часть: кэши, идентичные копии, возврат имён")
    ap.add_argument("--move-differ", action="store_true",
                    help="дополнительно перенести РАЗЛИЧАЮЩИЕСЯ в archive (решение человека)")
    ap.add_argument("--exclude", default="",
                    help="подстроки путей через запятую: не трогать (напр. папки чужой сессии)")
    ap.add_argument("--archive", default="archive/конфликтные_копии")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    arch = root / args.archive

    excl = [x.strip() for x in args.exclude.split(",") if x.strip()]
    copies, skipped = [], 0
    for p in root.rglob("*(копия с компьютера*"):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if any(x in str(p) for x in excl):
            skipped += 1
            continue
        copies.append(p)
    if skipped:
        print(f"пропущено по --exclude: {skipped}")
    print(f"найдено конфликтных копий: {len(copies)}\n")

    same, orphan, differ, cache = [], [], [], []
    for c in copies:
        if ".ruff_cache" in c.parts or "__pycache__" in c.parts:
            cache.append(c)
            continue
        main_path = c.with_name(MARK.sub("", c.name))
        if not main_path.exists():
            orphan.append((c, main_path))
        elif c.stat().st_size == main_path.stat().st_size and sha(c) == sha(main_path):
            same.append((c, main_path))
        else:
            differ.append((c, main_path))

    print(f"=== мусор кэшей (удалить): {len(cache)}")
    print(f"=== идентичны основному (удалить): {len(same)}")
    for c, _ in same[:12]:
        print(f"    {c.relative_to(root)}")
    print(f"\n=== основного НЕТ (копия и есть файл → вернуть имя): {len(orphan)}")
    for c, m in orphan:
        print(f"    {c.relative_to(root)}  →  {m.name}")
    print(f"\n=== РАЗЛИЧАЮТСЯ (в archive, решать человеку): {len(differ)}")
    for c, m in differ:
        print(f"    {c.relative_to(root)}")
        print(f"        копия {c.stat().st_size} б / основной {m.stat().st_size} б "
              f"— крупнее: {'КОПИЯ' if c.stat().st_size > m.stat().st_size else 'основной'}")

    if not args.apply:
        print("\n(показ без изменений; повторить с --apply)")
        return 0

    for c in cache + [c for c, _ in same]:
        c.unlink()
    for c, m in orphan:
        # у одного файла бывает НЕСКОЛЬКО копий («… (2).py»): первая занимает имя,
        # остальные сравниваем с ней — идентичные удаляем, различающиеся оставляем
        # с суффиксом, чтобы ничего не потерять молча.
        if not m.exists():
            c.rename(m)
            continue
        if sha(c) == sha(m):
            c.unlink()
        else:
            alt = m.with_name(f"{m.stem}__вариант_копии{m.suffix}")
            c.rename(alt)
            print(f"  ⚠️ {c.name}: имя занято, сохранён как {alt.name}")
    moved = 0
    if differ and args.move_differ:
        arch.mkdir(parents=True, exist_ok=True)
        for c, _ in differ:
            shutil.move(str(c), str(arch / f"{c.parent.name}__{c.name}"))
            moved += 1
    print(f"\nудалено {len(cache) + len(same)}, переименовано {len(orphan)}, "
          f"перенесено в archive {moved}")
    if differ and not args.move_differ:
        print(f"⚠️ различающихся НЕ тронуто: {len(differ)} — нужен флаг --move-differ "
              f"(и убедиться, что это не файлы чужой активной сессии)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
