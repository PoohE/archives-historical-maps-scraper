"""Проба: можно ли скачать скан описи ГАСО без браузера (JSF-postback).

Контекст: на портале нет прямой ссылки на PDF. Превью скана — PrimeFaces CommandLink,
клик по нему уходит POST-ом с javax.faces.ViewState. Если postback воспроизводится
обычным HTTP-клиентом, сборщик сканов пишется просто; если нет — нужен браузер (CDP)
или пакет от Codex.

Проба делается на одной описи (ф. 259 оп. 1, id=155) — той самой, чей PDF у нас уже есть,
так что результат можно сверить побайтово с `input_gaso/document.pdf`.

Запуск из корня проекта:
    python -B scripts_gaso/probe_scan_download.py
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://portal.gaso-smolensk.ru/page/portal/opisView.jsf?id=155"
HAVE = ROOT / "input_gaso" / "document.pdf"
OUT = ROOT / "output" / "gaso_scan_probe_20261008"
AGENT = "Mozilla/5.0 (compatible; IGIS-research/1.0)"


def build_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    op = build_opener()
    req = urllib.request.Request(URL, headers={"User-Agent": AGENT})
    with op.open(req, timeout=40) as r:
        html = r.read().decode("utf-8", "replace")
        base = r.geturl()
    print(f"страница получена: {len(html)} байт")

    vs = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html)
    form = re.search(r'<form[^>]+id="(form)"[^>]+action="([^"]+)"', html)
    links = re.findall(r'PrimeFaces\.cw\("CommandLink","[^"]+",\{id:"(form:[^"]*dataPreview[^"]*)"', html)
    print(f"ViewState: {'есть' if vs else 'НЕТ'}")
    print(f"form action: {form.group(2) if form else 'НЕ найден'}")
    print(f"CommandLink превью: {links[:3] if links else 'НЕ найдены'}")
    if not (vs and form and links):
        print("\nВЫВОД: postback не собрать из HTML — нужен браузер или пакет Codex.")
        return 1

    action = urllib.parse.urljoin(base, form.group(2))
    src = links[0]
    data = {
        "form": "form",
        "javax.faces.ViewState": vs.group(1),
        src: src,
        "javax.faces.source": src,
        "javax.faces.partial.ajax": "false",
    }
    body = urllib.parse.urlencode(data).encode()
    req2 = urllib.request.Request(action, data=body, headers={
        "User-Agent": AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": URL,
    })
    try:
        with op.open(req2, timeout=90) as r2:
            ctype = r2.headers.get("Content-Type", "")
            disp = r2.headers.get("Content-Disposition", "")
            payload = r2.read()
    except Exception as e:
        print(f"\nPOST упал: {type(e).__name__}: {e}")
        print("ВЫВОД: нужен браузер (CDP) или пакет Codex.")
        return 1

    print(f"\nответ: {len(payload)} байт | Content-Type: {ctype} | Disposition: {disp[:70]}")
    if payload[:5] == b"%PDF-":
        p = OUT / "probe_259_1.pdf"
        p.write_bytes(payload)
        got = hashlib.sha256(payload).hexdigest()
        print(f"PDF получен → {p}")
        print(f"sha256 скачанного: {got[:32]}…")
        if HAVE.exists():
            have = hashlib.sha256(HAVE.read_bytes()).hexdigest()
            print(f"sha256 нашего:     {have[:32]}…")
            print("СОВПАДАЕТ" if got == have else "РАЗЛИЧАЮТСЯ (возможно, другая версия файла)")
        print("\nВЫВОД: postback воспроизводится — сборщик сканов пишется без браузера.")
        return 0

    head = payload[:400].decode("utf-8", "replace")
    print(f"не PDF. начало ответа:\n{head[:300]}")
    print("\nВЫВОД: простой postback не отдаёт файл — нужен браузер (CDP) или пакет Codex.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
