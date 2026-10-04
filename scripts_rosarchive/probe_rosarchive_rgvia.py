# -*- coding: utf-8 -*-
"""Росархив-онлайн (online.archives.ru): разведка описей, указанных коллегами по РГВИА.

Повод: позиция № 11 очереди простояла с 10.07 как «сервер не отвечает»; 04.10 установлено,
что это геоблок нероссийских IP, а не неисправность. Ходим браузером пользователя через CDP.

Ссылки коллег (04.10): ф. 416 Генеральные карты России; ф. 414 оп. 1 статистические,
экономические, этнографические и военно-топографические сведения о России; ф. 418 планы и
описания городов, крепостей, селений.
"""
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cdp import fetch  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rosarchive_rgvia_20261004")
URLS = {
    "root": "https://online.archives.ru/",
    "f416": "https://online.archives.ru/guide/10000000001003/10000069247003/",
    "f414_op1": "https://online.archives.ru/search/10000000001003/10000069207003/",
    "f418": "https://online.archives.ru/search/10000000001003/10000069343003/10000069362003/",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        try:
            html, text = fetch(url, wait=5.0)
        except Exception as e:
            print(f"\n=== {name}: {type(e).__name__}: {str(e)[:140]}")
            continue
        (OUT / f"{name}.html").write_text(html, encoding="utf-8")
        (OUT / f"{name}.txt").write_text(text, encoding="utf-8")
        lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 2]
        print(f"\n=== {name}  ({len(html)} б HTML, {len(lines)} строк текста)")
        print("    " + "\n    ".join(lines[:30]))
        time.sleep(3)
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
