# -*- coding: utf-8 -*-
"""РГАДА ф.1354: разведка «Каталога чертёжного архива» (1354-ukaz_1.pdf, 1458 стр.).

Указатель — ПОПОЛНЯЕМЫЙ каталог чертёжных материалов межевого архива с ТЕКСТОВЫМ слоем.
Задача разведки: есть ли в нём наши 4 губернии, на каких страницах, как устроена запись.
"""
import io
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
PDF = BASE / "output" / "rgada_opisi_pdf_20261002" / "1354-ukaz_1.pdf"
OUT = BASE / "output" / "rgada_CONSOLIDATED"

STEMS = ["Калуж", "Перм", "Смолен", "Яросла"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pages: list[str] = []
    with pdfplumber.open(PDF) as pdf:
        for p in pdf.pages:
            pages.append(p.extract_text() or "")
    print(f"страниц: {len(pages)}, пустых: {sum(1 for t in pages if not t.strip())}")

    # 1) полное оглавление (строки «Название .... номер»)
    toc_txt = "\n".join(pages[:4])
    toc = re.findall(r"([А-ЯЁ][^\n.]{3,60}?)\.{3,}\s*(\d+)", toc_txt)
    print(f"\nОГЛАВЛЕНИЕ ({len(toc)} строк):")
    for name, pg in toc:
        print(f"  {name.strip()} — {pg}")

    # 2) где встречаются наши губернии
    print("\nНАШИ ГУБЕРНИИ ПО СТРАНИЦАМ:")
    hits: dict[str, list[int]] = {}
    for i, t in enumerate(pages, 1):
        for s in STEMS:
            if re.search(s, t):
                hits.setdefault(s, []).append(i)
    for s in STEMS:
        v = hits.get(s, [])
        rng = f"{min(v)}–{max(v)}" if v else "—"
        print(f"  {s}: {len(v)} стр. (диапазон {rng}) первые: {v[:10]}")

    # 3) пример записи со страницы, где есть наша губерния
    for s in STEMS:
        v = hits.get(s, [])
        if v:
            pg = v[0]
            print(f"\n--- ОБРАЗЕЦ стр.{pg} ({s}):")
            print(pages[pg - 1][:1200])
            break

    # 4) сохранить весь текст для дальнейшего разбора
    (OUT / "_f1354_ukaz1_text.txt").write_text(
        "\n".join(f"@@PAGE {i}\n{t}" for i, t in enumerate(pages, 1)), encoding="utf-8")
    print(f"\nтекст сохранён: {OUT / '_f1354_ukaz1_text.txt'}")

    # 5) какие вообще территории есть (заголовки-губернии в теле)
    gub = Counter()
    for t in pages:
        for m in re.findall(r"([А-ЯЁ][а-яё\-]+(?:ская|цкая|кая))\s+губерния", t):
            gub[m] += 1
    print(f"\nгуберний упомянуто в теле: {len(gub)}")
    print("  топ:", gub.most_common(15))


if __name__ == "__main__":
    main()
