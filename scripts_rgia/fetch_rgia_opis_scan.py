"""Скачивание сканов описей РГИА (fgurgia.ru) — постранично, для Vision-разбора.

Механика, измеренная 09.10.2026 (ошибочно считал, что сканов нет; их не видно простым GET):

1. На странице описи `/object/{opis_id}` есть блок `#fileView` — он рисуется скриптом с
   задержкой, ссылка выглядит как `/imageViewer/img?url=<base64>`, слово «pdf» стоит ТОЛЬКО
   в атрибуте `title` (напр. `380_21.pdf`). Поиск по тексту ссылки и по href его не находит.
2. Страница просмотрщика содержит JS-массив токенов страниц. **Имя массива генерируется
   случайно при каждом запросе**, поэтому берём его из строки
   `img.src = hostPath + '/image?url=' + <ИМЯ>`.
3. Страница отдаётся как JPEG по `/imageViewer/image?url=<токен>`.

Нумерация: один скан = РАЗВОРОТ, номер листа проставлен на правой странице.
Для описи 39 измерено: скан 54 → лист 49, то есть **скан = лист + 5**. Смещение у каждой
описи своё — калибровать по одному скану (`--probe N`), а не предполагать.

Запуск:
    python -B scripts_rgia/fetch_rgia_opis_scan.py --opis 2841221 --probe 54
    python -B scripts_rgia/fetch_rgia_opis_scan.py --opis 2841221 --scans 55-58,108-110,136
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://fgurgia.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
OUT_ROOT = Path(r"C:\arch\output")
DELAY = 1.2


def get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return r.read()


def viewer_url(opis_id: str) -> tuple[str, str]:
    """Со страницы описи взять ссылку просмотрщика и имя файла (`380_21.pdf`).

    Блок рисуется скриптом, но сам HTML страницы его уже содержит в разметке шаблона —
    если не нашли, значит у описи скана нет.
    """
    html = get(f"{BASE}/object/{opis_id}").decode("utf-8", errors="replace")
    m = re.search(r'href="([^"]*imageViewer/img\?url=[^"]+)"[^>]*title="([^"]+\.pdf)"', html)
    if not m:
        m = re.search(r'title="([^"]+\.pdf)"[^>]*href="([^"]*imageViewer/img\?url=[^"]+)"', html)
        if m:
            return m.group(2), m.group(1)
        raise SystemExit(f"у описи {opis_id} ссылка на скан не найдена в HTML "
                         f"(проверить в браузере: блок #fileView)")
    return m.group(1), m.group(2)


def page_tokens(viewer: str) -> list[str]:
    """Токены страниц из кода просмотрщика. Имя массива случайное — берём из img.src."""
    html = get(viewer).decode("utf-8", errors="replace")
    m = re.search(r"img\.src\s*=\s*hostPath\s*\+\s*'/image\?url='\s*\+\s*([A-Za-z_]\w*)", html)
    if not m:
        raise SystemExit("не найдена строка img.src — формат просмотрщика изменился")
    name = m.group(1)
    mm = re.search(re.escape(name) + r"\s*=\s*\[(.*?)\];", html, re.S)
    if not mm:
        raise SystemExit(f"не найден массив {name}")
    return re.findall(r"'([^']+)'", mm.group(1))


def parse_scans(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opis", help="object_id описи на fgurgia (ссылку ищем в HTML)")
    ap.add_argument("--viewer", help="ссылка просмотрщика /imageViewer/img?url=… — взять из "
                                     "браузера, если блок #fileView рисуется скриптом")
    ap.add_argument("--name", default="opis", help="имя файла для --viewer, напр. 380_39")
    ap.add_argument("--scans", help="номера сканов: 55-58,108-110,136")
    ap.add_argument("--probe", type=int, help="скачать один скан для калибровки нумерации")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.viewer:
        viewer, fname = args.viewer, f"{args.name}.pdf"
    elif args.opis:
        viewer, fname = viewer_url(args.opis)
    else:
        print("нужен --opis или --viewer")
        return 1
    toks = page_tokens(viewer)
    stem = fname.replace(".pdf", "")
    out = Path(args.out) if args.out else OUT_ROOT / f"rgia_opis_scan_{stem}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"{fname}: страниц {len(toks)} → {out}")
    (out / "VIEWER.json").write_text(json.dumps(
        {"opis_object_id": args.opis, "file": fname, "viewer": viewer,
         "pages": len(toks), "fetched": time.strftime("%Y-%m-%d %H:%M")},
        ensure_ascii=False, indent=2), encoding="utf-8")

    want = [args.probe] if args.probe else parse_scans(args.scans or "")
    if not want:
        print("укажите --scans или --probe")
        return 1
    for n in want:
        if not 1 <= n <= len(toks):
            print(f"  скан {n}: вне диапазона 1..{len(toks)}")
            continue
        dest = out / f"{stem}_s{n:04d}.jpg"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  скан {n}: уже есть")
            continue
        t = urllib.parse.quote(toks[n - 1], safe="")
        blob = get(f"{BASE}/imageViewer/image?url={t}")
        if not blob.startswith(b"\xff\xd8"):
            print(f"  скан {n}: не JPEG ({blob[:16]!r})")
            continue
        dest.write_bytes(blob)
        print(f"  скан {n}: {len(blob):,} байт → {dest.name}")
        time.sleep(DELAY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
