# -*- coding: utf-8 -*-
import io, re, sys
from pathlib import Path
from bs4 import BeautifulSoup
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SRC = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\input_neb_cards")
files = sorted(SRC.rglob("*.html"))
for f in files[1:3]:
    print("=" * 70); print(f.name[:80])
    soup = BeautifulSoup(f.read_text(encoding="utf-8", errors="replace"), "lxml")
    lines = [x for x in re.sub(r"[ \t]+", " ", soup.get_text("\n", strip=True)).split("\n") if x.strip()]
    start = next((i for i, l in enumerate(lines) if "Библиографическое описание" in l), 0)
    for i in range(start, min(start + 55, len(lines))):
        print(f"  [{i}] {lines[i][:130]}")
