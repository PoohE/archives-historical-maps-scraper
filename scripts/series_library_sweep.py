"""Прогон библиотечных каталогов ПО НАЗВАНИЯМ СЕРИЙ (а не по губерниям).

Зачем. Прежние прогоны искали «карта <Губерния> губернии». У межгубернских серийных изданий
губерния в заголовке не фигурирует вовсе («Специальная карта западной части Российской
империи», «Российский атлас», «Подробная карта Российской империи…»), поэтому они
систематически не попадали в улов. Сверка 07.11.2026: в каталоге из 112 202 записей нет ни
одного листа десятивёрстки Шуберта, РНБ представлена тремя записями.

Ищем через Yandex Search API по сайтам каталогов, читаем только то, что robots разрешает.

  python series_library_sweep.py plan            # показать запросы
  python series_library_sweep.py run             # выполнить
  python series_library_sweep.py run --limit 5   # проба
"""

import argparse

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout, log  # noqa: E402

# ⚠️ `common.log` — ФАБРИКА логгеров, а не print: вызов log("текст") создавал
# логгер с таким именем и не печатал ничего. Из-за этого прогон добора полей
# 15.11.2026 отработал 71 минуту с ПУСТЫМ логом — следить было не за чем.
LOG = log("series_library_sweep")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "series_library_sweep"
SKILL = Path.home() / ".claude" / "skills" / "yandex-search-api"
BASH = next(
    (p for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe")
     if Path(p).exists()),
    "bash",
)

# Сайты каталогов, где robots разрешает карточки записей
SITES = [
    "search.rsl.ru",       # РГБ
    "nlr.ru",              # РНБ
    "primo.nlr.ru",        # РНБ, электронный каталог
    "rusneb.ru",           # НЭБ
    "prlib.ru",            # Президентская библиотека
    "elib.rgo.ru",         # библиотека РГО
    "kp.rusneb.ru",        # книжные памятники
    "elib.shpl.ru",        # ГПИБ
    "catalog.shpl.ru",     # ГПИБ, каталог
]

# Названия серий — как они звучат на титулах, с вариантами написания
SERIES_QUERIES = {
    "серия 8 — Шуберт, десятивёрстка": [
        "Специальная карта западной части Российской империи",
        "Специальная карта Западной части России Шуберта",
        "спец. карта зап. части России Шуберта",
    ],
    "серия 13 — Стрельбицкий": [
        "Специальная карта Европейской России Стрельбицкого",
        "Специальная карта Европейской России 10 вёрст",
    ],
    "серия 10 — трёхвёрстка": [
        "Военно-топографическая карта Западной России три версты",
        "Военно-топографическая карта Европейской России трёхвёрстная",
    ],
    "серия 5 — Вильбрехт": [
        "Российский атлас из сорока четырёх карт Вильбрехт",
        "Российский атлас состоящий из сорока трёх карт",
    ],
    "серия 5а — Столистовая": [
        "Подробная карта Российской империи и близлежащих заграничных владений",
        "Столистовая карта Российской империи",
    ],
    "серия 11 — Менде": [
        "Топографический межевой атлас Менде",
        "атлас Менде губернии одна верста",
    ],
    "серия 4 — атласы наместничеств": [
        "Атлас Калужского наместничества 1782",
        "атлас наместничества уездные карты планы городов",
    ],
    "серия 2 — Атлас Российский 1745": [
        "Атлас Российский Академии наук 1745 девятнадцать карт",
    ],
    "знаки и инструкции": [
        "Условные знаки для употребления на топографических географических и квартирных картах",
        "Условные знаки межевых планов 1838",
        "Условные знаки для планов и карт межевого ведомства Левитский",
        "Жарков условные знаки межевых и хозяйственных планов специальных карт атласов",
        "Инструкция о съёмке и составлении межевых планов Закавказском крае",
    ],
}


# --- расширение 08.11.2026: серии, которых не было в первом наборе, и варианты написания
SERIES_QUERIES.update({
    "серия 1 — писцовые книги": [
        "писцовые книги издание Археографической комиссии",
        "писцовые книги Московского государства Калачов",
        "писцовые межевые дозорные книги уезда публикация",
    ],
    "серия 3 — Генеральное межевание": [
        "планы дач Генерального межевания уезда",
        "экономические примечания к планам Генерального межевания",
        "атлас уездный межевой план губернии Генеральное межевание",
    ],
    "серия 6 — военно-пограничная 4 версты": [
        "военная пограничная карта четыре версты в дюйме",
        "Военно-топографическое депо пограничная карта 4 версты",
    ],
    "серия 7 — семитопографические губернские": [
        "Топографическая карта Санкт-Петербургской губернии Шуберт пять вёрст",
        "семитопографическая карта Новгородской губернии Безкорнилович",
        "топографическая карта Московской губернии пять вёрст 1862",
        "семитопографическая карта губернии пять вёрст в дюйме",
    ],
    "серия 9 — Кавказский край": [
        "Карта Кавказского края Генеральный штаб Отдельного Кавказского корпуса 1847",
        "пятивёрстная карта Кавказского края военно-топографический отдел",
        "Пагирев алфавитный указатель к пятиверстной карте Кавказского края",
        "Подозерский ледники Кавказского хребта военно-топографический отдел",
    ],
    "серия 12 — Закаспийская область": [
        "пятивёрстная карта Закаспийской области",
    ],
    "серия 14 — Туркестанский военный округ": [
        "десятивёрстная карта Туркестанского военного округа",
    ],
    "серия 15 — Омский военно-топографический отдел": [
        "Специальная десятивёрстная карта Омского военного округа",
        "сорокавёрстная карта Омского военного округа",
    ],
    "серия 16 — Азиатская Россия": [
        "Специальная карта Азиатской России десять вёрст",
    ],
    "серия 17 — карты Генерального штаба РККА": [
        "топографическая карта Генерального штаба РККА губернии",
    ],
})

# Дополнительные варианты написания к уже бывшим группам
SERIES_QUERIES["серия 8 — Шуберт, десятивёрстка"] += [
    "Специальная карта западной части Российской империи Шуберт 1832",
    "карта Шуберта десять вёрст в дюйме лист",
]
SERIES_QUERIES["серия 13 — Стрельбицкий"] += [
    "Стрельбицкий специальная карта Европейской России лист",
    "Исчисление поверхности Российской империи Стрельбицкий",
]
SERIES_QUERIES["серия 10 — трёхвёрстка"] += [
    "военно-топографическая карта Смоленской губернии трёхвёрстная",
    "трёхвёрстная карта Калужской губернии военно-топографическая",
]
SERIES_QUERIES["серия 4 — атласы наместничеств"] += [
    "Атлас Ярославского наместничества",
    "Атлас Смоленского наместничества",
    "Топографическое описание наместничества с картами",
]
SERIES_QUERIES["серия 5а — Столистовая"] += [
    "Подробная карта Российской империи Депо карт 1816 лист",
]
SERIES_QUERIES["знаки и инструкции"] += [
    "Адрианов условные знаки военно-топографических карт 1912",
    "Скрицкий руководство инструкции межевание Закавказском крае",
    "условные знаки для планов и карт по ведомству министерства земледелия",
]

# --- расширение 12.11.2026: серии 18–24, ландкарты 1720–40-х, 12 карточек справочника
# и 26 статистико-экономических серий Г1–Г26. Обоснование и состав — series_queries_2026_11_12.py
from series_queries_2026_11_12 import EXT  # noqa: E402

for _k, _v in EXT.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]


# --- расширение 15.11.2026: запросы по разобранным позициям раздела Г (статистико-
# экономические серии). Состав и обоснование — series_queries_G_2026_11_14.py.
# Площадки дополнены областными библиотеками и ГПНТБ России (выявлена при разборе Г23:
# через неё лежит оцифровка горной и технической статистики). robots ГПНТБ прочитан
# 15.11.2026: на www.gpntb.ru закрыты только служебные пути Joomla, на ecology.gpntb.ru
# закрыт /search/ — учитывать при чтении карточек, на site:-запросы не влияет.
from series_queries_G_2026_11_14 import GQ, SITES_EXTRA  # noqa: E402

for _k, _v in GQ.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]
SITES += [s for s in SITES_EXTRA if s not in SITES]


# --- расширение 15.11.2026 (вторая порция): четыре позиции, под которые фраз не было —
# Г10+Г11, Г24–Г26, земские картограммы, кандидат «Картография МПС».
from series_queries_G2_2026_11_15 import GQ2  # noqa: E402

for _k, _v in GQ2.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]


# --- расширение 16.11.2026 (третья порция): девять карточек справочника, по которым в
# словарях не было НИ ОДНОЙ фразы. Выявлены `series_coverage_check.py` — сверкой по
# содержанию запросов, а не по первым знакам названия (прежний признак давал 24 позиции,
# из них 13 на деле покрыты). Две позиции вне территориального скоупа в прогон не берём.
from series_queries_2026_11_16 import GQ3  # noqa: E402

for _k, _v in GQ3.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]


# --- расширение 24.11.2026: серия 17 (РККА), пачка 13 сессии анализа, решение владельца
from series_queries_rkka_2026_11_24 import GQ4  # noqa: E402

for _k, _v in GQ4.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]


# --- расширение 24.11.2026: пачка 14 — ярославская земская оценка (после РККА, по очереди)
from series_queries_yar_zem_2026_11_24 import GQ5  # noqa: E402

for _k, _v in GQ5.items():
    SERIES_QUERIES.setdefault(_k, [])
    SERIES_QUERIES[_k] += [x for x in _v if x not in SERIES_QUERIES[_k]]

# --- расширение площадок 16.11.2026 (строка Б1.6 чек-листа). Добавлены ТОЛЬКО те, у кого
# проба `probe_sites_2026_11_16.py` показала форму КАРТОЧКИ ЗАПИСИ, а не раздел сайта.
# Не добавлены, хотя выдача есть: statearchive.ru (ГАРФ) и gaso-ural.ru — в выдаче разделы
# сайта и PDF-путеводители; garf-nika.ru — 9 строк, одни новости: НИКА отдаёт данные
# POST-запросами и в индекс не попадает, её берут своим клиентом, а не site:-поиском.
# Пустая выдача: rgvia.ru (сайта нет), arhiv.admin-smolensk.ru, gako.kaluga.ru.
SITES += [s for s in (
    "fgurgia.ru",        # РГИА, электронная опись: /object/N
    "rgada.info",        # РГАДА: /dela/<фонд>/
    "yar-archives.ru",   # ГАЯО: /archiveN/unit/N — единицы хранения
    "archive.perm.ru",   # ГАПК: /catalog/N-N/N-N/
    "goskatalog.ru",     # Госкаталог музейного фонда
    "gallica.bnf.fr",    # BnF Gallica
    "catalogue.bnf.fr",  # BnF, каталог
    "davidrumsey.com",   # David Rumsey Map Collection
    "loc.gov",           # Library of Congress
    "rasl.ru",           # БАН, ИРБИС
) if s not in SITES]


RECORD_RE = {
    "search.rsl.ru": re.compile(r"search\.rsl\.ru/ru/record/(\d+)"),
    "rusneb.ru": re.compile(r"rusneb\.ru/catalog/([0-9A-Za-z_]+)"),
    "prlib.ru": re.compile(r"prlib\.ru/item/(\d+)"),
    "elib.rgo.ru": re.compile(r"elib\.rgo\.ru/handle/([0-9/]+)"),
    # --- 16.11.2026: четыре хоста давали записи, но не распознавались как каталожные,
    # и весь их улов выпадал из подсчётов. Формы URL сняты по фактической выдаче прогона.
    "elib.shpl.ru": re.compile(r"elib\.shpl\.ru/(?:ru/)?nodes/(\d+)"),        # ГПИБ, 5 417 строк
    "lib.permkrai.ru": re.compile(r"lib\.permkrai\.ru/node/(\d+)"),          # Пермская краевая
    "primo.nlr.ru": re.compile(r"primo\.nlr\.ru/primo-explore/fulldisplay\?[^\s]*docid=([0-9A-Za-z_]+)"),
    "vivaldi.nlr.ru": re.compile(r"vivaldi\.nlr\.ru/([a-z]{2}\d{9})/details"),  # РНБ, оцифровка
    # --- формы карточек новых площадок, сняты по фактической выдаче пробы 16.11.2026
    "fgurgia.ru": re.compile(r"fgurgia\.ru/object/(\d+)"),
    # 16.11.2026: прежний шаблон `dela/(\d+)/` снимал номер ФОНДА, поэтому страница
    # фонда считалась записью, а 257 ссылок улова сворачивались в один ключ.
    # Формы сняты по фактической выдаче: образы дела (`kueh`), страницы и PDF описи,
    # географические материалы. Страницы выдачи `poisk/db.php` записью НЕ считаются —
    # это листалка базы дел, вход в неё описан в scripts_rgada/rgada_fund_opisi.py.
    "rgada.info": re.compile(
        r"rgada\.info/(?:"
        r"kueh/\d+/(?P<delo>\d+_\d+_[\w-]+)"            # образы дела: фонд_опись_дело
        r"|dela/\d+/[\w-]+/(?P<opis_img>\d+-opis_[\w-]+)"  # постраничная опись
        r"|opisi/(?P<opis_pdf>\d+-(?:opis|ukaz)_[\w.-]+)\.pdf"  # PDF описи
        r"|geos\d*/orig/(?P<geo>\d+)"                     # географические материалы
        r")"),
    "yar-archives.ru": re.compile(r"yar-archives\.ru/archive\d+/unit/(\d+)"),
    "archive.perm.ru": re.compile(r"archive\.perm\.ru/catalog/([\d\-/]+)"),
    "goskatalog.ru": re.compile(r"goskatalog\.ru/(?:portal/)?#?!?/?object/id=(\d+)"),
    "gallica.bnf.fr": re.compile(r"gallica\.bnf\.fr/ark:/(\d+/[a-z0-9]+)"),
    "catalogue.bnf.fr": re.compile(r"catalogue\.bnf\.fr/ark:/(\d+/cb\d+)"),
    "davidrumsey.com": re.compile(r"davidrumsey\.com/luna/servlet/detail/(RUMSEY~[^\s\"]+)"),
    "loc.gov": re.compile(r"loc\.gov/item/([\w\.]+)/?"),
    "rasl.ru": re.compile(r"rasl\.ru/cgi-bin/irbis\w*/cgiirbis_\d+\.exe\?[^\s]*"),
}


def queries() -> list[tuple[str, str]]:
    out = []
    for series, phrases in SERIES_QUERIES.items():
        for ph in phrases:
            for site in SITES:
                out.append((series, f"site:{site} {ph}"))
    return out


def run_query(q: str, results: int = 30) -> list[dict]:
    script = SKILL / "scripts" / "web_search_sync.sh"
    cmd = [BASH, str(script), "--query", q, "--region-id", "225", "--results", str(results)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, encoding="utf-8")
    except subprocess.TimeoutExpired:
        return []
    if p.returncode != 0:
        return []
    # скрипт печатает в конце: «  JSON: <путь к .json>»
    m = re.search(r"JSON:\s*(\S+\.json)", p.stdout)
    if not m:
        return []
    path = Path(m.group(1))
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else data.get("results", [])


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="plan", choices=["plan", "run"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    qs = queries()
    if args.limit:
        qs = qs[: args.limit]

    if args.mode == "plan":
        print(f"запросов: {len(qs)} ({len(SERIES_QUERIES)} серий × фразы × {len(SITES)} сайтов)")
        for s, q in qs[:25]:
            print(f"  [{s}] {q}")
        if len(qs) > 25:
            print(f"  … ещё {len(qs) - 25}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    hits_path = OUT / "hits.jsonl"
    seen_path = OUT / "queries_done.txt"
    seen = set(seen_path.read_text(encoding="utf-8").splitlines()) if seen_path.exists() else set()

    total = 0
    with hits_path.open("a", encoding="utf-8") as hf, seen_path.open("a", encoding="utf-8") as sf:
        for i, (series, q) in enumerate(qs, 1):
            if q in seen:
                continue
            res = run_query(q)
            kept = 0
            for r in res:
                url = r.get("url", "")
                site = next((s for s in RECORD_RE if s in url), None)
                hf.write(json.dumps({
                    "серия": series, "запрос": q, "url": url,
                    "title": r.get("title", ""), "snippet": (r.get("snippet") or "")[:300],
                    "каталожный": bool(site),
                }, ensure_ascii=False) + "\n")
                kept += 1
            hf.flush()
            sf.write(q + "\n")
            sf.flush()
            total += kept
            LOG.info(f"[{i}/{len(qs)}] {q[:70]} → {kept}")
            time.sleep(1.0)

    LOG.info(f"всего строк выдачи: {total}; файл: {hits_path}")


if __name__ == "__main__":
    main()

