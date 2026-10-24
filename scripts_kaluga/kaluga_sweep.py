"""Калужская ОНБ им. В. Г. Белинского: обход электронного каталога Веб-ИРБИС 64+.

⚠️ МАРШРУТ (разобран 23.10.2026; до этого источник числился тупиком — «SPA-оболочка
без результатов, нужна эмуляция интерфейса через CDP»). Браузер НЕ нужен, причин
неудачи было две, обе в запросе:

 1. ДРУГОЙ ИСПОЛНЯЕМЫЙ ФАЙЛ. Запросы слались на `cgiirbis_64_ft.exe` — он отвечает
    «Error request!» и редиректит. Рабочая точка входа лежит в редиректе со
    стартовой страницы `/irbis64r_plus/`:
        /cgi-bin/irbis64r_plus/irbis_webcgi.exe?C21COM=F&I21DBN=EK_FULLTEXT&P21DBN=EK&Z21ID=GUEST
 2. ФОРМА ОТПРАВЛЯЕТСЯ POST'ом С MULTIPART/FORM-DATA и ЖИВЫМ СЕАНСОМ. В атрибутах
    формы стоит `enctype="Multipart/form-data" method="POST"`, а поле `Z21ID` несёт
    идентификатор сеанса (вида `MTgyMVUyUzk5MVQ1RTdHNDE2`), который надо сперва снять
    со стартовой страницы. GET и обычный urlencoded-POST возвращают пустую оболочку —
    отсюда и вывод про «рендерится на клиенте».

⚠️ НАБОР ПАРАМЕТРОВ КРИТИЧЕН: без `S21ALL` и `CHECKINDEX` сервер отвечает
«FILE NOT EXISTS …frames_plus\\default\\search_search.frm» — не находит шаблон вывода.

ЧТО ОТДАЁТ СТРАНИЦА. По 20 записей (`S21CNR=20`), листание через `S21STN`
(1, 21, 41…). Каждая запись:
  * начинается с `<b>N.</b>`;
  * MFN — в ссылке «Напечатать» (`Z21MFN=195516`) и в `fulltext_search('195516')`;
  * шифр хранения — в жирном блоке перед автором (`К63.4 / К 83`);
  * инвентарный номер — в `value="К63.4/К 83-116065799"`;
  * «Экземпляры» — скрытый блок `id="EKZ<номер>"` с наличием по отделам.
Счётчика «найдено всего» в выдаче нет: листаем, пока страница отдаёт записи.

База `EK` — общий электронный каталог ОБЛАСТНОЙ библиотеки, то есть вперемешку
современные издания и краеведение. Гейт обязателен: по слову «карта» первым номером
приходит «Карта Магеллана: роман».

Запуск:
    python -B scripts_kaluga/kaluga_sweep.py --limit 2
    python -B scripts_kaluga/kaluga_sweep.py
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "kaluga_20261023"
DST = OUT / "kaluga_items.jsonl"
# ⚠️ журнал пройденных пар «запрос|страница»: без него каждый возобновлённый
# прогон начинает с первого запроса и впустую перечитывает сделанное
SHAGI = OUT / "shagi_done.txt"
CGI = "http://217.15.203.140:81/cgi-bin/irbis64r_plus/irbis_webcgi.exe"
START = CGI + "?C21COM=F&I21DBN=EK_FULLTEXT&P21DBN=EK&Z21ID=GUEST&S21CNR=5"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 1.0
NA_STRANICE = 20
MAX_STRANIC = 400  # до 8000 записей: «КАЛУЖСКАЯ» упёрлась в прежний потолок 110,
# «КАЛУЖСКОЙ» выдача идёт и на S21STN=1001, и обрывается лишь около 2000 —
# прежний потолок в 500 резал три самых урожайных запроса

TAGS = re.compile(r"<[^>]+>")
ZAPIS = re.compile(r"<b>\d+\.</b>")

# ⚠️ ЗАПРОСЫ ТОЛЬКО ОДНОСЛОВНЫЕ. Синтаксис ИРБИС `<.>K=СЛОВО<.>` ищет по словарю
# ключевых слов, а `*` между терминами — логическое И, и оно здесь режет насмерть:
#     <.>K=КАЛУЖСКОЙ<.>                 → выдача есть
#     <.>K=КАРТА<.>*<.>K=КАЛУЖСКОЙ<.>   → 1 запись
#     <.>K=КАРТА<.>*<.>K=ГУБЕРНИИ<.>    → 0
# Та же ловушка, что была на DSpace Президентской библиотеки («карта Пермской
# губернии» → 0, «Пермской губернии» → 200). Поэтому берём широкий невод из
# отдельных слов, а отсечение делает гейт при сборке пакета.
#
# Территориальные слова — в той форме, в какой они стоят в словаре ИРБИС
# (прилагательное, а не «уезд»): каталог краеведческий, дореволюционные издания
# описаны историческими названиями.
TERRITORII = ["КАЛУЖСКОЙ", "КАЛУЖСКАЯ", "КАЛУЖСКОГО", "БОРОВСКОГО", "БОРОВСК",
              "КОЗЕЛЬСКОГО", "КОЗЕЛЬСК", "МЕДЫНСКОГО", "МЕДЫНЬ", "МОСАЛЬСКОГО",
              "МОСАЛЬСК", "ТАРУССКОГО", "ТАРУСА", "ЖИЗДРИНСКОГО", "ЖИЗДРА",
              "МЕЩОВСКОГО", "МЕЩОВСК", "ПЕРЕМЫШЛЬСКОГО", "ПЕРЕМЫШЛЬ", "ЛИХВИНСКОГО",
              "ЛИХВИН", "МАЛОЯРОСЛАВЕЦКОГО", "МАЛОЯРОСЛАВЕЦ", "СЕРПЕЙСК", "ВОРОТЫНСК",
              "НАМЕСТНИЧЕСТВА"]
# Жанровые слова — для записей, где территория названа только в подзаголовке
ZHANRY = ["КАРТА", "КАРТЫ", "ПЛАН", "ПЛАНЫ", "АТЛАС", "МЕЖЕВАНИЕ", "МЕЖЕВОЙ",
          "ЧЕРТЕЖ", "ТОПОГРАФИЧЕСКОЕ", "КАРТОГРАФИЯ", "ЗЕМЛЕУСТРОЙСТВО"]


def zapros_stroki() -> list[str]:
    """Однословные термины: территории и жанры (см. комментарий выше)."""
    return list(dict.fromkeys(TERRITORII + ZHANRY))


def seans(s: requests.Session) -> str:
    """Снять идентификатор сеанса со стартовой страницы (без него поиск пуст).

    ⚠️ С повторами: сервер библиотеки периодически рвёт соединение
    (RemoteDisconnected), и необёрнутый запрос роняет весь прогон на середине.
    """
    for n in range(4):
        try:
            r = s.get(START, timeout=60)
            m = re.search(r"Z21ID=([A-Za-z0-9+/=]{10,40})", r.text)
            if m:
                return m.group(1)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 + 3 * n)
    return "GUEST"


_seans_kesh: dict[str, str] = {}


def iskat(s: requests.Session, stroka: str, stn: int, obnovit: bool = False) -> str | None:
    """Один POST поиска. Возвращает HTML страницы выдачи.

    Идентификатор сеанса кэшируется: стартовая страница весит 150 КБ, и тянуть её
    перед каждой страницей выдачи вдвое дороже самого поиска.
    """
    if obnovit or "z" not in _seans_kesh:
        _seans_kesh["z"] = seans(s)
    polya = {
        "Z21ID": _seans_kesh["z"], "LNG": "", "C21COM": "S", "I21DBN": "EK", "P21DBN": "EK",
        "S21FMT": "fullwebr", "S21CNR": str(NA_STRANICE), "S21STN": str(stn),
        "S21REF": "10", "S21SRW": "GOD", "S21SRD": "DOWN",
        "SEARCH_STRING": stroka, "USES21ALL": "1", "SEARCHIN": "ANYWHERE",
        # ⚠️ ИСКОМОЕ ЗАДАЁТ ИМЕННО S21ALL, а не SEARCH_STRING: поле формы сервер
        # игнорирует, и при жёстко зашитом термине все запросы возвращают одно и
        # то же (на этом я потерял первый прогон — два разных запроса дали
        # одинаковые 89 записей).
        "CHECKINDEX": "0", "S21ALL": f"<.>K={stroka}<.>",
    }
    for n in range(3):
        try:
            r = s.post(CGI, files={k: (None, v) for k, v in polya.items()}, timeout=90)
            # ВАЖНО: «FILE NOT EXISTS ... header_1.frm» сервер печатает ВСЕГДА -- у него
            # нет файлов оформления Веб-ИРБИС. Записи при этом отдаются штатно, поэтому
            # признаком неудачи служит отсутствие маркеров записи, а не эта строка.
            # На ней я сам потерял первый рабочий прогон (23.10).
            if r.ok and ZAPIS.search(r.text):
                return r.text
        except Exception:  # noqa: BLE001
            pass
        # пустой ответ может значить протухший сеанс — обновляем и пробуем снова
        _seans_kesh.pop("z", None)
        _seans_kesh["z"] = seans(s)
        polya["Z21ID"] = _seans_kesh["z"]
        time.sleep(2 + 2 * n)
    return None


def chistit(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", s))).replace("\xa0", " ").strip()


def razobrat(doc: str, zapros: str) -> list[dict]:
    """Записи со страницы выдачи."""
    kuski = ZAPIS.split(doc)[1:]  # первый кусок — шапка страницы
    out = []
    for k in kuski:
        mfn = (re.search(r"Z21MFN=(\d+)", k) or re.search(r"fulltext_search\('(\d+)'\)", k))
        if not mfn:
            continue
        mfn = mfn.group(1)
        inv = re.search(r'name="MFN"\s+value="([^"]+)"', k)
        txt = chistit(k.split("Экземпляры")[0])
        # шифр хранения стоит в начале записи до фамилии автора
        shifr = (inv.group(1).split("-")[0] if inv else "")
        ekz = re.search(r"Всего:\s*([^<]{0,60})", k)
        svob = re.search(r"Свободны:\s*</b>([^<]{0,60})", k)
        rubr = [chistit(x) for x in re.findall(r"S21P03=S=[^>]*>([^<]{3,120})</a>", k)]
        gody = re.findall(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", txt)
        out.append({
            "mfn": mfn,
            "shifr": shifr,
            "inv_nomer": inv.group(1) if inv else "",
            "opisanie": txt[:1200],
            "zagolovok": txt[:300],
            "god": gody[0] if gody else "",
            "rubriki": "; ".join(dict.fromkeys(rubr))[:400],
            "ekzemplyarov": chistit(ekz.group(1)) if ekz else "",
            "svobodny": chistit(svob.group(1)) if svob else "",
            "url": f"{CGI}?LNG=&P21DBN=EK&I21DBN=EK_PRINT&S21FMT=fullw_print&C21COM=F&Z21MFN={mfn}",
            "zapros": zapros,
            "istochnik": "Калужская ОНБ им. В. Г. Белинского (Веб-ИРБИС, база EK)",
        })
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="сколько запросов взять")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                done.add(json.loads(ln)["mfn"])
            except Exception:  # noqa: BLE001, S112
                continue

    zaprosy = zapros_stroki()
    if args.limit:
        zaprosy = zaprosy[: args.limit]
    print(f"запросов: {len(zaprosy)}, уже собрано записей: {len(done)}", flush=True)

    proideno: set[str] = set()
    if SHAGI.exists():
        proideno = {x for x in SHAGI.read_text(encoding="utf-8").splitlines() if x}
    print(f"шагов пройдено: {len(proideno)}", flush=True)

    s = requests.Session()
    s.headers["User-Agent"] = UA
    novyh = 0
    shlog = SHAGI.open("a", encoding="utf-8")
    with DST.open("a", encoding="utf-8") as fh:
        for i, q in enumerate(zaprosy, 1):
            vsego_q = 0
            if f"{q}|КОНЕЦ" in proideno:
                print(f"  {i:>3}/{len(zaprosy)} «{q[:40]}» — пройден ранее", flush=True)
                continue
            for stranica in range(MAX_STRANIC):
                stn = stranica * NA_STRANICE + 1
                if f"{q}|{stn}" in proideno:
                    continue
                doc = iskat(s, q, stn)
                if not doc:
                    break
                zapisi = razobrat(doc, q)
                if not zapisi:
                    break
                svezhih = 0
                for r in zapisi:
                    if r["mfn"] in done:
                        continue
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    done.add(r["mfn"])
                    novyh += 1
                    svezhih += 1
                fh.flush()
                shlog.write(f"{q}|{stn}" + "\n")
                shlog.flush()
                vsego_q += len(zapisi)
                time.sleep(DELAY)
                if len(zapisi) < NA_STRANICE:
                    shlog.write(f"{q}|КОНЕЦ" + "\n")
                    shlog.flush()
                    break
            print(f"  {i:>3}/{len(zaprosy)} «{q[:46]}» — записей {vsego_q:>4}, "
                  f"всего {len(done):>5}", flush=True)
    shlog.close()

    rows = []
    for ln in DST.open(encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:  # noqa: BLE001, S112
            continue
    if rows:
        cols = sorted({k for r in rows for k in r})
        with (OUT / "kaluga_items.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    print(f"\nновых за прогон: {novyh} | всего: {len(rows)}")
    print(f"→ {OUT / 'kaluga_items.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
