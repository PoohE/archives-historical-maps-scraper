"""Проверка доступности площадок добора ПЕРЕД ночным прогоном.

Зачем. 12–13.11.2026 ночная цепочка встала целиком: исходящий IP оказался зарубежным,
и Yandex Search API, ГАПК, ПрБ, НЭБ, РГИА, УИАД, РГАДА и Смоленская стали недостижимы.
Чтобы не повторять, перед сборкой пакета прогоняем по одной живой ссылке на площадку
и собираем пакет только из того, что реально отвечает.

Запуск: python scripts/probe_routes.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}

# По одной РЕАЛЬНОЙ карточке на площадку — проверяем то, что будет качать прогон,
# а не главную страницу (главная может отвечать, когда карточки закрыты).
ROUTES = {
    "РГБ (search.rsl.ru)": "https://search.rsl.ru/ru/record/01009771730",
    "ПрБ (www.prlib.ru)": "https://www.prlib.ru/item/397242",
    "НЭБ (rusneb.ru)": "https://rusneb.ru/catalog/000199_000009_010294727/",
    "РГО (elib.rgo.ru)": "https://elib.rgo.ru/handle/123456789/236729",
    "ГПИБ (elib.shpl.ru)": "http://elib.shpl.ru/ru/nodes/79542",
    "Пермская краевая (lib.permkrai.ru)": "https://lib.permkrai.ru/node/34568",
    "ГАЯО (af.yar-archives.ru)": "https://af.yar-archives.ru/archive1/unit/10001016862",
    "РНБ-Vivaldi (vivaldi.nlr.ru)": "https://vivaldi.nlr.ru/cm000010008/details",
    "ГАПК описи (archives.permkrai.ru)": "https://archives.permkrai.ru/archive1/inventory/114902?page=42",
    "РГАДА (rgada.info)": "http://rgada.info/poisk/index.php?fund_number=271&Sk=30",
    "ГАСО-Урал (opisi.gaso-ural.ru)": "https://opisi.gaso-ural.ru/upload/images/lists_auto/59_1/010.jpg",
    "УИАД (рус. домен)": "http://xn--90ag.xn--80adcv1b.xn--p1ai/",
    "Смоленская ОУНБ": "http://elib.smolensklib.ru/main/last?page=1",
    "Белинка (elib.uraic.ru)": "https://elib.uraic.ru/",
    "БАН ИРБИС (ecatalog.rasl.ru)": "http://ecatalog.rasl.ru:8080/cgi-bin/irbis64r_11/cgiirbis_64.exe?C21COM=F&I21DBN=BAN&P21DBN=BAN",
}


def probe(url: str, timeout: int = 25) -> tuple[str, int]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            body = r.read(40000)
        ms = int((time.time() - t0) * 1000)
        low = body[:6000].decode("utf-8", "ignore").lower()
        if any(w in low for w in ("отключите vpn", "доступ ограничен", "заблокирован",
                                  "attention required", "just a moment", "verify access")):
            return "ЗАСЛОН", ms
        if len(body) < 900:
            return f"пусто {len(body)}б", ms
        return f"OK {r.status}", ms
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}", int((time.time() - t0) * 1000)
    except Exception as e:                                         # noqa: BLE001
        return type(e).__name__, int((time.time() - t0) * 1000)


def main() -> None:
    fix_stdout()
    out = {}
    print(f"{'площадка':<36}{'ответ':<14}{'мс':>7}")
    for name, url in ROUTES.items():
        st, ms = probe(url)
        out[name] = {"url": url, "status": st, "ms": ms}
        mark = "✅" if st.startswith("OK") else "⛔"
        print(f"{name:<36}{st:<14}{ms:>7}  {mark}")
        time.sleep(0.8)
    dst = ROOT / "output" / "probe_routes.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for v in out.values() if v["status"].startswith("OK"))
    print(f"\nдоступно: {ok} из {len(out)}  →  {dst}")


if __name__ == "__main__":
    main()
