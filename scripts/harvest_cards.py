"""Добор карточек: полное название, масштаб, шифр хранения, выходные данные.

Вход  — по умолчанию output/work_2026-11-08/work.jsonl (список, замороженный 08.11.2026);
        для текущего улова — `--queue output/harvest_queue_<ДАТА>/queue.jsonl`, который
        собирает scripts/build_harvest_queue.py.
Выход — harvested.jsonl рядом со входом, построчно, с возобновлением по ключу.

Маршруты и вежливость (сверено пробой 16.11.2026 — один запрос на площадку):
  РГБ   search.rsl.ru/ru/record/...     — robots разрешает /ru/record, пауза 1,2 с
  ПБ    www.prlib.ru/item/N             — robots разрешает /item/, Crawl-delay 2
  КП    kp.rusneb.ru                    — пауза 1,5 с
  НЭБ   rusneb.ru                       — 200 прямым запросом с 13.11, пауза 4 с
  РГО   elib.rgo.ru                     — 200, пауза 2,5 с
  ГАЯО  af.yar-archives.ru/archiveN/... — 200, заголовок и шифр Ф/Оп/Д прямо в <title>.
                                          ⚠️ капча по квоте сессии (~60—70 обращений на
                                          PHPSESSID, память reference_gayo-rate-limit-captcha):
                                          гонять порциями, пауза 3 с
  ГПИБ  elib.shpl.ru/ru/nodes/N         — 200; h1 даёт только последний уровень («№ 158,
                                          10 июня»), полное название собирается из цепочки
                                          родителей — иначе заголовок бессмысленный
  Пермь lib.permkrai.ru/node/N          — 200, название в JSON-LD schema.org
  РНБ-В vivaldi.nlr.ru/<id>/details     — 200, но отдаёт ТОЛЬКО заглавие; полное
                                          библиографическое описание подгружается отдельно
  BnF   catalogue.bnf.fr/ark:/...        — HTML из нашей сети не открывается, зато работает
                                          SRU API: UNIMARC с названием, годом, cote (930$a)
                                          и авторами. Ходим в API, не в страницу

НЕ ходим (BLOCKED, причина пишется в статус записи — чтобы «пропущено» не было молчаливым):
  РГИА  fgurgia.ru      — robots: `User-agent: anthropic-ai → Disallow: /` (строка 678,
                          сверено 16.11.2026). Тот же случай, что ГАКО: не обходим,
                          только официальный запрос. РЕШЕНИЕ ВЛАДЕЛЬЦА.
  РНБ   primo.nlr.ru    — robots: Disallow: / для всех агентов
  Gallica, LoC          — Cloudflare 403 и на страницу, и на OAI/JSON API
  Rumsey                — анти-бот «Verify Access» (память feedback_rumsey-iiif-measure-scale:
                          IIIF читается из Chrome, скриптом — нет)
  ГАПК  archive.perm.ru — карточка за авторизацией, фондовый обход только видимым Chrome
  Госкаталог            — SPA, карточки нет в HTML (нужен muzfo-rest API), и их всего 67
  РГАДА rgada.info      — ключ улова = номер ФОНДА, а не дела (дефект RECORD_RE в
                          series_library_sweep.py): добирать нечего, нужен обходчик описи

Хост, трижды подряд не ответивший, отключается до конца прогона — иначе таймауты
съедают всё время (на первом заходе 25 строк за 9 минут из-за лежащего РГО).

  python harvest_cards.py                                   # старый список, с возобновлением
  python harvest_cards.py --queue output/harvest_queue_20261116/queue.jsonl --limit 20
  python harvest_cards.py --queue ... --hosts elib.shpl.ru   # одна площадка
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
WORK = DIR / "work.jsonl"
OUT = DIR / "harvested.jsonl"

UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)"}
DELAY = {"search.rsl.ru": 1.2, "www.prlib.ru": 2.0, "kp.rusneb.ru": 1.5,
         "rusneb.ru": 4.0, "elib.rgo.ru": 4.0,   # 19.11: при 2,5 с треть обращений уходила в таймаут
         # 16.11.2026, новые площадки. ГАЯО — 3 с: портал режет сессию капчей по квоте
         # обращений, медленнее ходить дешевле, чем ловить капчу на 60-й записи.
         "af.yar-archives.ru": 3.0, "yar-archives.ru": 3.0, "elib.shpl.ru": 1.5,
         "lib.permkrai.ru": 1.5, "vivaldi.nlr.ru": 1.5, "catalogue.bnf.fr": 1.5}

# Площадки, куда НЕ ходим, и причина — она попадает в статус записи, чтобы отказ был
# виден в журнале, а не выглядел как «не ответил». Сверено пробой 16.11.2026.
BLOCKED = {
    "fgurgia.ru": "robots запрещает anthropic-ai (Disallow: /) — только официальный запрос",
    "primo.nlr.ru": "robots: Disallow: / для всех агентов",
    "gallica.bnf.fr": "Cloudflare 403 (и страница, и OAI) — нужен scrape.do или Chrome",
    "loc.gov": "Cloudflare 403 (и страница, и ?fo=json) — нужен scrape.do",
    "www.loc.gov": "Cloudflare 403 (и страница, и ?fo=json) — нужен scrape.do",
    "davidrumsey.com": "анти-бот «Verify Access» — только Chrome/IIIF",
    "www.davidrumsey.com": "анти-бот «Verify Access» — только Chrome/IIIF",
    "archive.perm.ru": "карточка за авторизацией; обход только видимым Chrome",
    "www.archive.perm.ru": "карточка за авторизацией; обход только видимым Chrome",
    "goskatalog.ru": "SPA: карточки нет в HTML, нужен muzfo-rest API",
    "web.goskatalog.ru": "SPA: карточки нет в HTML, нужен muzfo-rest API",
    "rgada.info": "ключ улова — номер фонда, не дела (дефект RECORD_RE): нужен обходчик описи",
}

BNF_SRU = ("https://catalogue.bnf.fr/api/SRU?version=1.2&operation=searchRetrieve"
           "&maximumRecords=1&recordSchema=unimarcxchange&query=")
SKIP_HOLDERS: set[str] = set()         # 13.11.2026: маршрут открылся (split tunneling),
# прямой запрос к rusneb.ru и elib.rgo.ru отдаёт HTTP 200 — проверено на карточках
# 000202_000006_1276940 (43 756 байт) и handle РГО (17 996 байт). Платный scrape.do
# для НЭБ больше не нужен. Прежде здесь было {"НЭБ", "РГО"} — 403 и лежащий хост.
DEAD_AFTER = 3
# Площадки, которым 15 с мало. elib.rgo.ru отдаёт страницы по 70-90 КБ и на
# зарубежном выходе VPN укладывается в 20-35 с — при timeout=15 это выглядело
# как «молчит», хотя сайт жив.
TIMEOUT = {"elib.rgo.ru": 40}
_walls: dict[str, int] = {}   # заслоны ПОДРЯД по хосту (сбрасывается удачей)
# 20.11.2026: КАРАНТИН вместо казни. Прежде DEAD_AFTER отказов выключали площадку
# «до конца прогона», и на десятичасовом прогоне это приговор без пересмотра: 403
# у www.prlib.ru и таймаут у rusneb.ru были всплеском частоты — через час оба
# отвечали 200 за 0,5-2 с, но 1 379 их карточек уже помечены без запроса.
# Теперь хост уходит в карантин на нарастающий срок и пробуется снова.
_quarantine: dict[str, float] = {}   # хост -> время, до которого не трогаем
_q_round: dict[str, int] = {}        # сколько раз уже уходил в карантин
QUARANTINE_MIN = (10, 20, 40, 60)    # минуты по кругам, дальше — последний

_last: dict[str, float] = {}
_fails: dict[str, int] = {}

SC = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
SHELF = re.compile(r"((?:FB|KGR|OMF|IZO|MK|ZV|NTO)\s+[^\s][\w\s/\-.№]{2,34}?)"
                   r"\s+(?:Читать|Заказать|Marc21)")
NAV_SHPL = ("Электронная библиотека ГПИБ", "Главная", "Книжные издания",
            "Периодические издания", "Газеты", "Журналы", "Картографические издания")
TAILS = (" - Search RSL", " | Президентская библиотека имени Б.Н. Ельцина",
         " | Президентская библиотека", " имени Б.Н. Ельцина")


# Признаки страницы-заслона вместо карточки. Без этой проверки прогон пишет «добрано»
# по капче: у ГАЯО квота обращений на сессию (~60—70), и 61-я страница выглядит как
# обычный ответ 200 (память reference_gayo-rate-limit-captcha, разбор 16.11.2026).
WALL = ("введите код с картинки", "подтвердите, что вы не робот", "recaptcha",
        "verify access", "attention required", "just a moment", "cf-browser-verification",
        # 19.11.2026: было голое «авторизация» — и ложно срабатывало на ссылке
        # «Авторизация» в шапке DSpace у elib.rgo.ru, то есть на КАЖДОЙ его странице.
        # Нужны формулировки самого заслона, а не слово из навигации.
        "требуется авторизация", "войдите в систему", "необходимо войти",
        "доступ только для зарегистрированных")


_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>|<link[^>]*>|<noscript[^>]*>.*?</noscript>",
                        re.S | re.I)


def is_wall(body: str) -> bool:
    """Заслон ищем в ВИДИМОМ тексте, а не в разметке.

    19.11.2026: признак «recaptcha» срабатывал на подключении reCAPTCHA v3
    (`<script src=".../recaptcha/api.js?render=...">`), которое у elib.rgo.ru висит
    на КАЖДОЙ странице при свободно отдаваемом содержимом. Из-за этого первая же
    карточка РГО читалась как капча и выключала площадку целиком. То же устройство
    защиты у ГАЯО: reCAPTCHA в разметке ≠ закрытая страница.
    """
    head = _SCRIPT_RE.sub(" ", body[:40000])[:4000].lower()
    return any(w in head for w in WALL)


def blocked_reason(url: str) -> str | None:
    """Причина отказа по площадке — или None, если площадка открыта."""
    host = url.split("/")[2].lower() if "//" in url else ""
    for h, why in BLOCKED.items():
        if host == h or host.endswith("." + h):
            return why
    return None


def route(row: dict) -> str | None:
    """Адрес, по которому снимается карточка: сама страница либо API площадки.

    Решение — по ХОСТУ ссылки, а не по метке держателя: метки в журналах разных прогонов
    расходятся («ПБ» в списке от 08.11 против «ПрБ» в очереди от 16.11), и привязка к ним
    молча теряла целые площадки.
    """
    holder, url = row["key"].split(":", 1)[0], row["url"]
    if holder in SKIP_HOLDERS or blocked_reason(url):
        return None
    host = url.split("/")[2].lower() if "//" in url else ""

    if "search.rsl.ru" in host or "rusneb.ru" in host:
        m = re.search(r"000199_000009_(\d{9})", url) or re.search(r"record/0?1?(\d{9})", url)
        if m:                                    # карточка РГБ в любой из трёх форм ссылки
            return f"https://search.rsl.ru/ru/record/01{m.group(1)}"
        return url                               # прочие записи НЭБ — прямым запросом
    if "prlib.ru" in host:
        return url.replace("https://prlib.ru/", "https://www.prlib.ru/")
    if "elib.rgo.ru" in host:
        # 19.11.2026: в очередь попали ссылки вида /handle/N/M/simple-search?… и
        # /handle/N/M?offset=50 (97 из 1 152). Это страницы ПОИСКА внутри раздела,
        # а не карточки: заголовок с них снимался как «…: Поиск». Режем до handle.
        m = re.match(r"(https?://elib\.rgo\.ru/handle/\d+/\d+)", url)
        return m.group(1) if m else url
    if "kp.rusneb.ru" in host:
        return url
    if "yar-archives.ru" in host:                # ГАЯО: карточка живёт на поддомене af.
        return re.sub(r"https?://(?:af\.)?yar-archives\.ru",
                      "https://af.yar-archives.ru", url)
    if "elib.shpl.ru" in host:
        return url
    if "lib.permkrai.ru" in host:
        return url.split("?")[0]                 # ?fragment=page-1 — просмотрщик, не карточка
    if "vivaldi.nlr.ru" in host:
        return url
    if "catalogue.bnf.fr" in host:
        m = re.search(r"(ark:/\d+/cb\d+\w?)", url)
        return BNF_SRU + quote(f'bib.persistentid all "{m.group(1)}"') if m else None
    if holder == "КП":
        return url
    return None


def _send_to_quarantine(host: str, why: str) -> None:
    """Увести площадку в карантин на нарастающий срок вместо выключения насовсем."""
    rnd = _q_round.get(host, 0)
    mins = QUARANTINE_MIN[min(rnd, len(QUARANTINE_MIN) - 1)]
    _q_round[host] = rnd + 1
    _quarantine[host] = time.time() + mins * 60
    print(f"  !! {host}: {why} — карантин {mins} мин (круг {rnd + 1})", flush=True)


def fetch(url: str) -> str | None:
    host = url.split("/")[2]
    until = _quarantine.get(host, 0.0)
    if until:
        if time.time() < until:
            return None                        # ещё в карантине — не трогаем
        # срок вышел: снимаем карантин и даём площадке новый шанс
        _quarantine.pop(host, None)
        _fails[host] = 0
        _walls[host] = 0
        print(f"  ~~ {host}: карантин истёк, пробую снова", flush=True)
    gap = DELAY.get(host, 1.5)
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=TIMEOUT.get(host, 15)) as r:
            body = r.read().decode("utf-8", "ignore")
        _fails[host] = 0
        return body
    except urllib.error.HTTPError as e:
        # 19.11.2026: «карточки нет» — не отказ площадки. Прежде три 404 подряд
        # выключали хост на весь прогон: у РГО в очереди именно такие ссылки идут
        # первыми, и 1 152 карточки терялись при живом сайте (проверено вручную:
        # те же handle отдают 200 на 70-90 КБ).
        if e.code in (404, 410):
            return None
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] >= DEAD_AFTER:
            _send_to_quarantine(host, f"отвечает {e.code} {DEAD_AFTER} раза")
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] >= DEAD_AFTER:
            _send_to_quarantine(host, f"молчит {DEAD_AFTER} раза")
        return None


def flat(html: str) -> str:
    """Текст страницы без разметки и скриптов — одной строкой."""
    no_js = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", no_js)))


#: «1д : 4в», «1 д. : 2 в.», «в 1 дюйме 2 версты» — старая запись через вёрсты в дюйме.
#: 1 верста = 500 саженей = 1 066,8 м; 1 дюйм = 2,54 см, поэтому знаменатель = вёрст × 42 000.
VERST = re.compile(r"(?:в\s*)?1\s*(?:д|дюйм\w*)\.?\s*[:\-]?\s*(\d{1,3}(?:[.,]\d)?)\s*(?:в|верст\w*)\.?",
                   re.I)


def find_scale(text: str) -> dict:
    """Масштаб и его контекст — общий приём для всех площадок."""
    w = re.search(r"[Мм]асштаб[^.;]{0,160}", text)
    s = SC.search(w.group(0)) if w else None
    if s:
        return {"scale": int(re.sub(r"\D", "", s.group(1))), "scale_ctx": w.group(0).strip()[:120]}
    # 21.11.2026: у ГАЯО масштаб записан по-старому — «Масштаб 1д : 4в 1см : 1,68км»,
    # знаменателя в записи нет вовсе, и общий шаблон давал ноль на всех 538 карточках.
    # окно под вёрсты шире: шаблон выше обрывается на первой точке, а запись
    # «Масштаб 1 д. : 2 в.» этих точек содержит две
    w2 = re.search(r"[Мм]асштаб.{0,120}", text, re.S)
    if w2:
        v = VERST.search(w2.group(0))
        if v:
            verst = float(v.group(1).replace(",", "."))
            if 0 < verst <= 200:
                return {"scale": int(round(verst * 42000)),
                        "scale_ctx": " ".join(w2.group(0).split())[:120]}
    return {}


def parse_yar(html: str) -> dict:
    """ГАЯО: в <title> лежат и заголовок дела, и шифр — «… — Ф.560 Оп.1Т-2 Д.760 / ГБУ ЯО …»."""
    out: dict = {}
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        return out
    t = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    t = t.split(" / ")[0].strip()                      # хвост с названием архива
    shelf = re.search(r"(Ф\.\s*[^\s]+\s*Оп\.\s*[^\s]+\s*Д\.\s*[^\s]+)", t)
    if shelf:
        out["shelf"] = shelf.group(1).strip()
        t = t[: shelf.start()].rstrip(" .—-")
    if t:
        out["zagolovok_polnyi"] = t
    txt = flat(html)
    out.update(find_scale(txt))
    d = re.search(r"Даты?[^:]{0,12}:\s*([^|<]{3,40})", txt)
    if d:
        out["daty"] = d.group(1).strip()
    return out


def parse_shpl(html: str) -> dict:
    """ГПИБ: h1 — только последний уровень дерева, поэтому заголовок собираем с родителями.

    Без цепочки получается «№ 158, 10 июня» или «Матвеев А. С.» — запись, по которой
    нельзя понять, что это за источник (проба 16.11.2026 на шести узлах).
    """
    out: dict = {}
    h1 = re.search(r'<h1[^>]*node-title[^>]*>([^<]{1,200})', html)
    chain = [unescape(x).strip() for x in
             re.findall(r'nodes/\d+[^"]*"[^>]*>([^<]{3,120})', html)[:8]]
    # Первые уровни — навигация самой библиотеки, они ничего не говорят об источнике.
    # Верхние уровни — рубрики самой библиотеки («Книжные издания», «Газеты»): в название
    # источника они не входят, но в put_v_dereve остаются, чтобы путь не терялся.
    chain = [c for c in chain if c not in NAV_SHPL]
    full_chain = [unescape(x).strip() for x in
                  re.findall(r'nodes/\d+[^"]*"[^>]*>([^<]{3,120})', html)[:8]]
    parts = chain + ([unescape(h1.group(1)).strip()] if h1 else [])
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    if seen:
        out["zagolovok_polnyi"] = " / ".join(seen)[:400]
        out["put_v_dereve"] = " / ".join(full_chain)[:300]
    txt = flat(html)
    out.update(find_scale(txt))
    return out


def parse_permkrai(html: str) -> dict:
    """Пермская краевая: название лежит в JSON-LD schema.org — надёжнее, чем <title>."""
    out: dict = {}
    m = re.search(r'"@type"\s*:\s*"[^"]*"\s*,\s*"name"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
    if m:
        try:
            out["zagolovok_polnyi"] = json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            out["zagolovok_polnyi"] = m.group(1)
    if not out.get("zagolovok_polnyi"):
        t = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        if t:
            out["zagolovok_polnyi"] = unescape(re.sub(r"\s+", " ", t.group(1))).split("|")[0].strip()
    txt = flat(html)
    out.update(find_scale(txt))
    return out


def parse_vivaldi(html: str) -> dict:
    """РНБ (Vivaldi): страница /details отдаёт только заглавие и фонд-держатель."""
    out: dict = {}
    txt = flat(html)
    m = re.search(r"Заглавие:\s*(.{3,300}?)\s*(?:Библиотечный фонд:|Полное библиограф"
                  r"|Физическое описание:|Год издания:|Авторы?:|Доступные права)", txt)
    if m:
        out["zagolovok_polnyi"] = m.group(1).strip()
    else:
        h1 = re.search(r"<h1[^>]*>([^<]{3,200})", html)
        if h1:
            out["zagolovok_polnyi"] = unescape(h1.group(1)).strip()
    f = re.search(r"Библиотечный фонд:\s*([^|]{3,80}?)\s*(?:Полное|Доступные)", txt)
    if f:
        out["fond_derzhatel"] = f.group(1).strip()
    out.update(find_scale(txt))
    return out


def parse_bnf(xml: str) -> dict:
    """BnF: UNIMARC из SRU. 200 — заглавие, 300 — название по-французски, 210$d — год,
    206$a — масштаб картографического документа, 930$a — cote (шифр), 7xx — авторы."""
    out: dict = {}
    fields: dict[str, list[list[tuple[str, str]]]] = {}
    for m in re.finditer(r'<([\w:]*datafield)[^>]*tag="(\d+)"[^>]*>(.*?)</\1>', xml, re.S):
        subs = [(c, unescape(v).strip()) for c, v in
                re.findall(r'code="(\w)"[^>]*>([^<]*)<', m.group(3))]
        fields.setdefault(m.group(2), []).append(subs)

    def sub(tag: str, code: str) -> str:
        for subs in fields.get(tag, []):
            for c, v in subs:
                if c == code and v:
                    return v
        return ""

    title = sub("200", "a")
    rest = " ; ".join(v for c, v in (fields.get("200", [[]])[0]) if c in ("e", "f") and v)
    if title:
        out["zagolovok_polnyi"] = f"{title} ; {rest}"[:400] if rest else title
    fr = sub("300", "a")
    if fr:
        out["zagolovok_fr"] = fr
    year = sub("210", "d")
    if year:
        out["god"] = year
    cote = sub("930", "a")
    if cote:
        out["shelf"] = cote
        place = sub("930", "c")
        if place:
            out["mesto_hraneniya"] = place
    sc = sub("206", "a") or sub("123", "a")
    if sc:
        m = SC.search(sc)
        if m:
            out["scale"] = int(re.sub(r"\D", "", m.group(1)))
        out["scale_ctx"] = sc[:120]
    authors = []
    for tag in ("700", "701", "702", "703", "712"):
        for subs in fields.get(tag, []):
            a = dict(subs)
            name = " ".join(x for x in (a.get("a", ""), a.get("b", "")) if x).strip()
            if name:
                authors.append(name)
    if authors:
        out["avtory"] = "; ".join(dict.fromkeys(authors))[:300]
    phys = sub("215", "a")
    if phys:
        out["opisanie_fiz"] = phys
    return out


def parse_rgo(html: str) -> dict:
    """DSpace библиотеки РГО: карточка узнаётся по citation_title.

    19.11.2026. Общий parse() берёт <title>, а у РГО это «Библиотека Русского
    географического общества: <раздел>» — поэтому страницы РАЗДЕЛОВ коллекции
    («Карты», «Книги», «1845-1917», «Вход») уходили в журнал со статусом
    «добрано» и пустым содержанием. Карточку от раздела отличает мета-тег
    citation_title: у разделов его нет. Нет тега — возвращаем пустой разбор,
    и вызывающий код сам помечает запись как «карточка пуста».
    """
    out: dict = {}
    m = re.search(r'<meta\s+[^>]*name="citation_title"[^>]*content="([^"]+)"', html, re.I)
    if not m:
        return out                                   # раздел коллекции, не запись
    out["zagolovok_polnyi"] = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    d = re.search(r'<meta\s+[^>]*name="citation_date"[^>]*content="([^"]+)"', html, re.I)
    if d:
        out["god"] = d.group(1).strip()
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    w = re.search(r"Масштаб[^.;]{0,160}", txt)
    sc = SC.search(w.group(0)) if w else SC.search(out["zagolovok_polnyi"])
    if sc:
        out["scale"] = int(re.sub(r"\D", "", sc.group(1)))
        out["scale_ctx"] = (w.group(0) if w else sc.group(0)).strip()[:120]
    sh = SHELF.search(txt)
    if sh:
        out["shelf"] = sh.group(1).strip()
    return out


PARSERS = {
    "elib.rgo.ru": parse_rgo,
    "yar-archives.ru": parse_yar,
    "elib.shpl.ru": parse_shpl,
    "lib.permkrai.ru": parse_permkrai,
    "vivaldi.nlr.ru": parse_vivaldi,
    "catalogue.bnf.fr": parse_bnf,
}


def parse_for(src: str, body: str) -> dict:
    """Разбор карточки парсером своей площадки; для РГБ/ПрБ/НЭБ/РГО — общий parse()."""
    host = src.split("/")[2].lower() if "//" in src else ""
    for key, fn in PARSERS.items():
        if key in host:
            return fn(body)
    return parse(body)


def parse(html: str) -> dict:
    out: dict = {}
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if m:
        t = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        for tail in TAILS:
            if t.endswith(tail):
                t = t[: -len(tail)]
        t = re.sub(r"\s*имени Б\.Н\. Ельцина\s*$", "", t).strip(" .|—-")
        if t:
            out["zagolovok_polnyi"] = t
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    w = re.search(r"Масштаб[^.;]{0,160}", txt)
    s = SC.search(w.group(0)) if w else None
    if s:
        out["scale"] = int(re.sub(r"\D", "", s.group(1)))
        out["scale_ctx"] = w.group(0).strip()[:120]
    elif out.get("zagolovok_polnyi") and (s := SC.search(out["zagolovok_polnyi"])):
        out["scale"] = int(re.sub(r"\D", "", s.group(1)))
        out["scale_ctx"] = s.group(0)
    m = SHELF.search(txt)
    if m:
        out["shelf"] = m.group(1).strip()
    return out




def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--retry-unavailable",
        action="store_true",
        help="перезайти на карточки, помеченные «хост недоступен»: 13.11.2026 маршрут "
             "открылся и rusneb.ru с elib.rgo.ru отвечают 200 — прежняя пометка больше "
             "не отражает факт",
    )
    ap.add_argument("--queue", type=str, default="",
                    help="файл очереди (по умолчанию output/work_2026-11-08/work.jsonl); "
                         "журнал добора пишется рядом с ним")
    ap.add_argument("--hosts", type=str, default="",
                    help="через запятую: обходить только эти хосты/держателей")
    args = ap.parse_args()

    work, out_path = WORK, OUT
    if args.queue:
        work = Path(args.queue)
        if not work.exists():
            raise SystemExit(f"нет файла очереди: {work}")
        out_path = work.with_name("harvested.jsonl")

    rows = [json.loads(ln) for ln in work.open(encoding="utf-8")]
    if args.hosts:
        want = {h.strip().lower() for h in args.hosts.split(",") if h.strip()}
        rows = [r for r in rows
                if any(w in r["url"].lower() or w in r.get("holder", "").lower() for w in want)]
    done: set[str] = set()
    if out_path.exists():
        for ln in out_path.open(encoding="utf-8"):
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if "key" not in rec:
                continue
            st = str(rec.get("status", ""))
            # 14.11.2026: под флагом перезаходим и на «не ответил» — у НЭБ прямым
            # маршрутом 424 таких из 493 при 69 успешных, то есть это троттлинг хоста,
            # а не отсутствие карточки; лечится увеличенной паузой, а не отказом.
            # 19.11.2026: «заслон» тоже снимается флагом — иначе запись, помеченная
            # ложной капчей, не переспрашивается уже никогда.
            if args.retry_unavailable and ("недоступ" in st or st == "не ответил"
                                           or st.startswith("заслон")):
                continue
            # Заслон (капча/авторизация) — всегда возвращаем в очередь, без флага:
            # это состояние хоста в тот момент, а не свойство карточки.
            if st.startswith("заслон"):
                continue
            done.add(rec["key"])
    todo = [r for r in rows if r["key"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"всего в работе: {len(rows)} | уже добрано: {len(done)} | к обходу: {len(todo)}",
          flush=True)

    got = skipped = 0
    with out_path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            src = route(r)
            if not src:
                # Причина отказа пишется словами: «пропущено» без причины уже дважды
                # маскировало то, что у площадки просто нет маршрута (11.11 и 16.11.2026).
                r["status"] = blocked_reason(r["url"]) or "нет маршрута в route()"
                skipped += 1
            else:
                body = fetch(src)
                if body and is_wall(body):
                    # Заслон — это не пустая карточка: запись остаётся в очереди на
                    # следующий заход. 19.11.2026: раньше ОДНА стена ставила
                    # _fails[host] = DEAD_AFTER, то есть выключала площадку до конца
                    # прогона, и остальные её карточки метились «не ответил» вообще
                    # без запроса — у РГО так потерялось 1 151 из 1 152 при живом
                    # сайте. Теперь хост выключается только после DEAD_AFTER стен
                    # ПОДРЯД: разовая стена на одной карточке не хоронит остальные.
                    h = src.split("/")[2]
                    _walls[h] = _walls.get(h, 0) + 1
                    r["status"] = "заслон (капча/авторизация) — повторить позже"
                    if _walls[h] >= DEAD_AFTER:
                        _send_to_quarantine(h, f"{DEAD_AFTER} заслона подряд")
                    skipped += 1
                elif body:
                    _walls[src.split("/")[2]] = 0      # страница взята — серия стен прервана
                    r.update(parse_for(src, body))
                    r["istochnik_kartochki"] = src
                    r["status"] = "добрано" if r.get("zagolovok_polnyi") else "карточка пуста"
                    got += 1
                else:
                    r["status"] = "не ответил"
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} — добрано {got}, пропущено {skipped}", flush=True)

    print(f"\nдобрано карточек: {got}; пропущено по недоступности: {skipped}")
    print(f"файл: {out_path}")


if __name__ == "__main__":
    main()
