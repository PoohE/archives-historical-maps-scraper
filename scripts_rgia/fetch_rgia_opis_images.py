# -*- coding: utf-8 -*-
"""Скачивание постраничных образов описи РГИА (fgurgia.ru).

Маршрут (разобран 2026-10-04). Страница `object/{opis_id}` — пустой JS-шаблон; ссылка на
образы приходит карточкой `ajax/obj/{opis_id}/{search_index}` в поле `files[].url` как
`/imageViewer/img?url=<токен>`. Токен — base64 от строки параметров, побайтно XOR 0xFF:

    filename=380_21.pdf&totalPages=161&currentPage=1&ext=.pdf&object=2841185&attr=1588
    &serial=2450726061&size=5

Меняя `currentPage`, получаем любой лист: `/imageViewer/image?url=<токен>` отдаёт JPEG.
`size` — ступень качества (чем больше, тем крупнее; сайт отдаёт до size=5..7).
`search_index` сессионный — берётся заново при каждом запуске.

Запуск:
    python scripts_rgia/fetch_rgia_opis_images.py <opis_id> <страницы> [--out DIR] [--size N]
    python scripts_rgia/fetch_rgia_opis_images.py 2841185 5-7 --out input_rgia_opisi/f380_op21
"""
import argparse
import base64
import io
import re
import sys
import time
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://fgurgia.ru"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
PAUSE = 3


def xor_b64(s: str) -> str:
    return base64.b64encode(bytes(b ^ 0xFF for b in s.encode("utf-8"))).decode("ascii")


def unxor(tok: str) -> str:
    return bytes(b ^ 0xFF for b in base64.b64decode(tok)).decode("utf-8", "replace")


def pages_arg(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("opis_id")
    ap.add_argument("pages", help="например 5-7 или 5,6,12")
    ap.add_argument("--out", default="input_rgia_opisi")
    ap.add_argument("--size", type=int, default=None, help="ступень качества; по умолчанию как у сайта")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"})

    html = s.get(f"{BASE}/object/{args.opis_id}", timeout=40).text
    m = re.search(r'data-search-index="(\d+)"', html)
    if not m:
        print("search-index не найден — опись не отдаёт дерево")
        return
    ti = m.group(1)

    time.sleep(PAUSE)
    card = s.get(f"{BASE}/ajax/obj/{args.opis_id}/{ti}", params={"children": "false"}, timeout=60,
                 headers={"X-Requested-With": "XMLHttpRequest",
                          "Referer": f"{BASE}/object/{args.opis_id}"}).text
    fm = re.search(r'"url":"(?:\\/|/)imageViewer(?:\\/|/)img\?url=([^"]+)"', card)
    if not fm:
        print("ссылки на образы в карточке нет — у этой описи сканов не выложено")
        return
    params = unxor(fm.group(1).replace("\\/", "/"))
    print("параметры описи:", params)
    tm = re.search(r"totalPages=(\d+)", params)
    total = int(tm.group(1)) if tm else 0
    print("всего листов:", total or "не указано в карточке (ограничение снято)")

    for page in pages_arg(args.pages):
        if total and not 1 <= page <= total:
            print(f"лист {page} вне диапазона 1..{total}")
            continue
        p = re.sub(r"currentPage=\d+", f"currentPage={page}", params)
        # вьювер добавляет к параметрам карточки ступень качества; без неё сервер отдаёт пусто
        size = args.size or 5
        p = re.sub(r"size=\d+", f"size={size}", p) if "size=" in p else p + f"&size={size}"
        time.sleep(PAUSE)
        r = s.get(f"{BASE}/imageViewer/image", params={"url": xor_b64(p)}, timeout=120,
                  headers={"Referer": f"{BASE}/object/{args.opis_id}"})
        ct = r.headers.get("Content-Type", "")
        ext = ".jpg" if "jpeg" in ct or "jpg" in ct else (".png" if "png" in ct else ".bin")
        f = out / f"{args.opis_id}_p{page:04d}{ext}"
        f.write_bytes(r.content)
        print(f"  лист {page}: HTTP {r.status_code}, {ct}, {len(r.content)} байт → {f.name}")


if __name__ == "__main__":
    main()
