# -*- coding: utf-8 -*-
"""Проба новых площадок для серийного прогона: архивы, Госкаталог, зарубежные каталоги.

Зачем проба, а не сразу прогон. 15.11.2026 три площадки (ГПНТБ, Смоленская ОУНБ, Белинка)
были добавлены в `SITES` по догадке и дали только шум — шахматный центр, вебмейл, патентный
ретрофонд, газета 1982 года. Отсюда правило проекта: **площадку добавляем по подтверждённой
выдаче, а не по следу идентификатора**. Здесь каждая площадка проверяется тремя запросами,
и в прогон идут только те, у которых выдача ведёт на карточки записей, а не на разделы сайта.

Геопорталы (Руниверс, Retromap, ЭтоМесто, Q-map, SouthKlad) в пробу НЕ включены — решение
владельца 16.11.2026: по ним отдельная работа позже, там не каталожный поиск, а слои.

⚠️ Запускать, когда основной прогон НЕ идёт: у обоих один Yandex Search API, а `run_query`
при отказе возвращает пустой список — прогон пометит запрос выполненным и потеряет улов.

  python scripts/probe_sites_2026_11_16.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import fix_stdout, log  # noqa: E402
from series_library_sweep import run_query  # noqa: E402

LOG = log("probe_sites")
OUT = HERE.parents[0] / "output" / "series_library_sweep"

# Кандидаты по строке Б1.6 чек-листа, без геопорталов
CANDIDATES = {
    # федеральные архивы
    "fgurgia.ru": "РГИА, электронная опись",
    "rgada.info": "РГАДА",
    "rgvia.ru": "РГВИА",
    "statearchive.ru": "ГАРФ",
    "garf-nika.ru": "ГАРФ, система НИКА",
    # региональные архивы наших губерний
    "archive.perm.ru": "ГАПК (Пермский край)",
    "yar-archives.ru": "ГАЯО (Ярославская)",
    "gaso-ural.ru": "ГАСО-Урал (Свердловск)",
    "arhiv.admin-smolensk.ru": "ГАСО (Смоленск)",
    "gako.kaluga.ru": "ГАКО (Калужская)",
    # музейный фонд
    "goskatalog.ru": "Госкаталог музейного фонда РФ",
    # зарубежные каталоги
    "gallica.bnf.fr": "BnF Gallica",
    "catalogue.bnf.fr": "BnF, каталог",
    "davidrumsey.com": "David Rumsey Map Collection",
    "loc.gov": "Library of Congress",
    "rasl.ru": "БАН (Библиотека Академии наук)",
}

# Запросы пробы: две общие формулы серий и одна узкая — чтобы увидеть и объём, и точность
PROBE = [
    "Специальная карта Западной части Российской империи",
    "атлас губернии уездные карты",
    "план генерального межевания уезда",
]
PROBE_EN = [
    "Russian Empire map atlas 1800s",
    "Strelbitsky special map European Russia",
    "Mende atlas survey Russia",
]


def main() -> None:
    fix_stdout()
    report = []
    for host, name in CANDIDATES.items():
        foreign = host.endswith((".fr", ".gov", ".com"))
        urls: list[str] = []
        titles: list[str] = []
        for ph in (PROBE_EN if foreign else PROBE):
            res = run_query(f"site:{host} {ph}", results=20)
            for r in res:
                u = r.get("url") or ""
                if host in u:
                    urls.append(u)
                    titles.append((r.get("title") or "")[:90])
        paths = Counter(re.sub(r"\d+", "N", re.sub(r"^https?://[^/]+", "", u).split("?")[0])
                        for u in urls)
        LOG.info(f"{host:26} {name:34} строк {len(urls):3}")
        for p, n in paths.most_common(4):
            LOG.info(f"      {n:3}×  {p[:72]}")
        for t in titles[:3]:
            LOG.info(f"      «{t}»")
        report.append({"host": host, "имя": name, "строк": len(urls),
                       "формы_пути": paths.most_common(6), "примеры": titles[:5],
                       "ссылки": urls[:8]})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "проба_площадок_2026-11-16.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    LOG.info(f"→ {OUT / 'проба_площадок_2026-11-16.json'}")
    live = [r["host"] for r in report if r["строк"] >= 5]
    LOG.info(f"площадок с содержательной выдачей (≥5 строк): {len(live)} — {', '.join(live)}")


if __name__ == "__main__":
    main()
