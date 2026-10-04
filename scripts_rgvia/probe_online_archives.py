# -*- coding: utf-8 -*-
"""online.archives.ru — портал описей федеральных архивов Росархива: разведка по РГВИА.

Повод (2026-10-04): коллеги указали, что описи фондов 414, 416, 418 РГВИА доступны
онлайн ИМЕННО ЗДЕСЬ, а не в «Электронных описях» бд.ргвиа.рф, по которым мы делали вывод
о недоступности. Проверяем и исправляем решение.

Два препятствия, оба обходятся браузером:
  — сайт геоблокирует нероссийские IP (из VPN-туннеля TCP не устанавливается вовсе);
  — сертификат не проходит проверку (ERR_CERT_AUTHORITY_INVALID), поэтому нужен
    `ignore_https_errors=True`.
Chrome на машине пользователя выведен из туннеля, поэтому работаем Playwright-браузером.
"""
import asyncio
import io
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgvia_online_archives_20261004")
URLS = {
    "robots": "https://online.archives.ru/robots.txt",
    "f416_guide": "https://online.archives.ru/guide/10000000001003/10000069247003/",
    "f414_search": "https://online.archives.ru/search/10000000001003/10000069207003/",
    "f418_search": "https://online.archives.ru/search/10000000001003/10000069343003/10000069362003/",
}


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True)
        ctx = await br.new_context(ignore_https_errors=True, locale="ru-RU")
        page = await ctx.new_page()
        for name, url in URLS.items():
            try:
                r = await page.goto(url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(2500)
                html = await page.content()
                (OUT / f"{name}.html").write_text(html, encoding="utf-8")
                txt = re.sub(r"[ \t]+", " ", await page.inner_text("body"))
                (OUT / f"{name}.txt").write_text(txt, encoding="utf-8")
                lines = [ln.strip() for ln in txt.splitlines() if len(ln.strip()) > 2]
                print(f"\n=== {name}: HTTP {r.status if r else '—'}, {len(html)} б, строк текста {len(lines)}")
                print("   " + "\n   ".join(lines[:25]))
            except Exception as e:
                print(f"\n=== {name}: {type(e).__name__}: {str(e)[:160]}")
        await br.close()
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
