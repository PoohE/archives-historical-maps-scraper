# -*- coding: utf-8 -*-
"""Сводка по всем источникам проекта: где есть собранные записи, а где только пробы.

Повод: в `output/` накопилось больше 150 каталогов по полутора десяткам архивов и библиотек —
probe, handoff, offline, acceptance, review. Перед тем как разведывать «следующий архив», надо
понять, что уже сделано: по каким источникам есть реальные наборы записей, по каким только
заготовки сборщика, а по каким вообще ничего.

Группировка по префиксу имени каталога; для каждой группы берётся САМЫЙ СВЕЖИЙ каталог,
в котором есть непустой файл записей.
"""
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output")
REC_FILES = ("records_full.jsonl", "records.jsonl", "records.csv", "notion_import.csv")

# префикс каталога → человеческое имя источника
SOURCES = {
    "rgada": "РГАДА", "rgia_fund380": "РГИА ф.380", "rgia": "РГИА (keyword-sweep)",
    "rgvia": "РГВИА", "garf": "ГАРФ", "gako": "ГАКО (Калужская обл.)",
    "gaso": "ГАСО (Смоленская обл.)", "gayao": "ГАЯО (Ярославская обл.)",
    "gapk": "ГАПК (Пермский край)", "cgamos": "ЦГАМОС (Москва)",
    "neb": "НЭБ", "permkrai": "Пермская краевая б-ка", "prlib": "Президентская б-ка",
    "rsl": "РГБ", "rnb": "РНБ", "rnb18": "РНБ (XVIII в.)", "gpib": "ГПИБ",
    "ebid": "ЕБИД", "goskatalog": "Госкаталог РФ", "rosarchive": "Росархив",
    "kaluga": "Калужская ОУНБ", "smolensk": "Смоленская ОУНБ",
    "sverdlovsk": "Свердловская ОУНБ", "yaroslavl": "Ярославская ОУНБ",
    "rgo": "РГО", "aonb": "Архангельская ОУНБ", "local_libs": "локальные библиотеки",
}


def count(p: Path) -> int:
    try:
        if p.suffix == ".jsonl":
            return sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                       if ln.strip())
        return max(0, sum(1 for _ in p.open(encoding="utf-8-sig")) - 1)
    except OSError:
        return 0


def main() -> None:
    dirs = [d for d in BASE.iterdir() if d.is_dir()]
    found: dict[str, list[tuple[str, int, str]]] = {}
    for key in SOURCES:
        for d in sorted(dirs, key=lambda x: x.name, reverse=True):
            if not d.name.startswith(key):
                continue
            # отсечь чужие префиксы: rgia не должен ловить rgia_fund380, если ключ точный
            if key == "rgia" and d.name.startswith("rgia_fund380"):
                continue
            if key == "rnb" and d.name.startswith("rnb18"):
                continue
            for f in REC_FILES:
                p = d / f
                if p.exists() and (n := count(p)) > 0:
                    found.setdefault(key, []).append((d.name, n, f))
                    break
            if found.get(key):
                break

    print(f"{'ИСТОЧНИК':30} {'ЗАПИСЕЙ':>8}  СВЕЖИЙ НАБОР")
    print("-" * 96)
    empty = []
    for key, name in SOURCES.items():
        if key in found:
            d, n, f = found[key][0]
            print(f"{name:30} {n:>8}  {d}/{f}")
        else:
            cat = [x.name for x in dirs if x.name.startswith(key)]
            empty.append((name, len(cat)))
    print()
    print("Без набора записей (только пробы/заготовки):")
    for name, k in empty:
        print(f"  {name:30} каталогов: {k}")
    # что вообще не упомянуто
    known = {k for k in SOURCES}
    other = sorted({re.sub(r"_20\d{6}.*", "", d.name) for d in dirs
                    if not any(d.name.startswith(k) for k in known)})
    if other:
        print("\nКаталоги вне списка источников:")
        for o in other[:25]:
            print("  ", o)


if __name__ == "__main__":
    main()
