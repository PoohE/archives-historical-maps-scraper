"""Адаптер: четыре пакета + разметка модели → notion_import.csv v1.6 для моста.

Решения пользователя 10–11.11.2026, по которым собирается этот импорт:
  1. вносим картографические И статистические источники; то, что не подходит ни под один
     из 25 типов каталога (заводская бухгалтерия, переписка, чертежи сооружений), — отсев
     со записью решения, а не удаление;
  2. территория берётся из заголовка, а при его молчании — **по фондообразователю**
     (уезд напечатан в названии фонда у шести фондов из восьми);
  3. административный уровень — по охвату САМОГО ДОКУМЕНТА, не по учреждению;
  4. масштаб прописывается только картографическим и только при чёткой привязке
     (у ГАСО-Урал — лишь там, где он напечатан в описи: 99 дел ф. 773);
  5. у территории и уровня ставится признак источника значения.

⚠️ У ГАСО-Урал НЕТ ссылки на дело: портал публикует только сканы описей, и у разных дел
одной описи страница скана одна. Мост дедуплицирует по «Ссылке на онлайн-архив», поэтому
к URL скана добавляется якорь с шифром дела — иначе дела схлопнутся в одну запись.

  python build_import_2026_11_11.py            # собрать CSV и отчёт
"""

import csv
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

import territory_resolve as tr  # noqa: E402

from territory_gate import classify  # noqa: E402

from common import env, fix_stdout, load_env  # noqa: E402

ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
TERR_DB = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"
REG_DB = "6c6a3cfb-8d87-491e-8ce6-da7194bc857b"

OUT = Path(__file__).resolve().parents[1] / "output"
WORK = OUT / "upload_2026-11-11"
TYPED = WORK / "typed.jsonl"
TYPE_CODES = WORK / "type_codes.json"
GASO_BASE = "https://opisi.gaso-ural.ru"
TODAY = "2026-11-11"

PACK_SRC = {
    "gaso": "gaso_ural/package.jsonl",
    "rgo": "work_2026-11-08/rgo_package.jsonl",
    "neb": "work_2026-11-08/neb_package.jsonl",
    "rgia380": "rgia380_ours/package_rgia380.jsonl",
}
#: пакет → метка держателя для справочника «Архивы»
HOLDER = {"gaso": "ГАСО-Урал", "rgo": "Картфонд РГО",
          "neb": "НЭБ", "rgia380": "РГИА"}

#: Территория по фондообразователю ГАСО-Урал. Уезд берётся ТОЛЬКО там, где он напечатан
#: в названии фонда; у ф. 160 (Гороблагодатский округ), ф. 148 (Лысьвенский) и ф. 64
#: (коллекция съёмок) уезд не назван — горный округ единица ведомственная, не
#: административная, округа пересекали уезды, поэтому ставим одну губернию.
FOND_TERR = {
    "773": ["Камышловский", "Пермская губерния"],
    "14": ["Екатеринбургский", "Пермская губерния"],
    "9": ["Екатеринбургский", "Пермская губерния"],
    "713": ["Ирбитский", "Пермская губерния"],
    "374": ["Красноуфимский", "Пермская губерния"],
    "160": ["Пермская губерния"],
    "148": ["Пермская губерния"],
    "64": ["Пермская губерния"],
}

#: «Год: источник значения» — приводим к значениям select каталога.
#: ⚠️ Без этой карты признак ЛЖЁТ: у РГО `year_src` = «из карточки РГО», в select такого
#: значения нет, и 320 записей получили бы «нет» при заполненном годе (поймано чек-листом
#: заполненности 11.11.2026). Для библиотечных карточек в select добавляется отдельное
#: значение «из карточки библиотеки» — его создаёт prepare_catalog_schema.py.
YEAR_SRC = {
    "из описи": "из карточки дела",
    "из карточки НЭБ": "из карточки библиотеки",
    "из карточки РГО": "из карточки библиотеки",
    "из библиографического описания РГО": "из карточки библиотеки",
    # имена, уже являющиеся значениями select, пропускаем как есть
    "из карточки дела": "из карточки дела",
    "из заголовка дела": "из заголовка дела",
    "по датировке серии": "по датировке серии",
    "по крайним датам описи": "по крайним датам описи",
    "нет": "нет", "None": "нет", None: "нет",
}
#: то же для масштаба
SCALE_SRC = {
    "из заголовка описи": "из заголовка описи",
    "с листа": "с листа",
    "из карточки НЭБ": "из карточки библиотеки",
    "из библиографического описания РГО": "из карточки библиотеки",
}
#: поля карточки НЭБ, лежащие в `sheets` словарём, → колонки каталога
NEB_CARD = {
    "Объем": "Листы / страницы",
    "Место издания": "Место создания",
    "Ответственность": "Автор / составитель",
}
YEAR_RE = re.compile(r"(1[5-9]\d{2}|20\d{2})")

COLUMNS = [
    "Название источника", "Год сведений", "BB восток", "BB запад", "BB север", "BB юг",
    "DC Type", "OCR (распознавание текста)", "RMSE оцифровки (м)", "Автор / составитель",
    "Автор внесения", "Административный уровень", "Библиографическое описание",
    "Библиотечный шифр", "Векторизация", "Возможность векторизации",
    "Геопривязка: RMSE (м)", "Геопривязка: метод", "Геопривязка: статус",
    "Год обновления / проверки", "Год оцифровки", "Год создания (верхняя)",
    "Год создания (нижняя)", "Дата внесения", "Единица хранения",
    "Картографическая проекция", "Качество сканирования", "Листы / страницы", "Лицензия",
    "Масштаб (знаменатель)", "Место создания", "Место хранения",
    "Наличие текстового / табличного формата", "Номер в серии", "Нулевой меридиан",
    "Описание", "Опись", "Организация оцифровки", "Оригинальный масштаб", "Примечания",
    "Примечания по оцифровке", "Прямая ссылка на файл изображения", "Путь / URL к файлу",
    "Размер листа (мм)", "Размер файла (МБ)", "Разрешение (DPI)",
    "Связанное издание: URL", "Связанное издание: автор / ответственность",
    "Связанное издание: библиографическое описание", "Связанное издание: год издания",
    "Связанное издание: название", "Связанное издание: тип", "Система координат",
    "Совместимые источники", "Статус приёмки", "Ссылка на онлайн-архив",
    "Статус доступа", "Техника исполнения", "Тип привязки", "Физическое состояние",
    "Фонд", "Формат файла", "Цветность скана", "Число GCP", "Язык",
]
#: новые свойства провенанса — их создаёт prepare_catalog_schema.py
PROV_COLUMNS = ["Масштаб: источник значения", "Год: источник значения",
                "Территория: источник значения",
                "Административный уровень: источник значения"]

SHEETS_RE = re.compile(r"^\s*(\d+)\s*(?:\(([\d]+)\s*[хx]\s*([\d]+)\))?")


def sheets_and_size(raw: str | None) -> tuple[str, str]:
    """«1(99х132)» → ("1", "990x1320"); «25» → ("25", ""). Размер в описи в САНТИМЕТРАХ."""
    if not raw:
        return "", ""
    m = SHEETS_RE.match(str(raw))
    if not m:
        return str(raw)[:40], ""
    n = m.group(1) or ""
    if m.group(2) and m.group(3):
        return n, f"{int(m.group(2)) * 10}x{int(m.group(3)) * 10}"
    return n, ""


def dc_type(code: str) -> str:
    return {"A": "StillImage", "B": "Text", "C": "Dataset"}.get(code[:1], "")


def api(method: str, url: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {env('NOTION_TOKEN')}",
        "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode()[:300]}") from e


def terr_hint_text(t: dict) -> str:
    """Дословная территория из заголовка, как её прочитала модель (для гейта)."""
    return str(t.get("terr") or "")


def title_terr_resolves(terr_text: str, stem_index: dict) -> bool:
    """Найдётся ли названная в заголовке территория в справочнике каталога.

    ⚠️ Без этой проверки признак провенанса лжёт: модель называет в `terr` то, что
    прочитала в заголовке («Гороблагодатский округ», «Сергинско-Уфалейский округ»), но
    горный округ — единица ведомственная, в справочнике территорий её нет, поле осталось
    бы пустым, а признак утверждал бы «из заголовка». Сверяем по тому же стему, которым
    матчит сам мост, и ставим признак по факту.
    """
    for part in re.split(r"[,;]|\sи\s", terr_text):
        part = re.sub(r"\(.*?\)", "", part).strip().rstrip(".")
        part = re.sub(r"\s+(уезд[а-я]*|губерни[яюи])$", "", part, flags=re.I).strip()
        if part and stem_index.get(tr.stem(part)):
            return True
    return False


def main() -> None:  # noqa: PLR0912, PLR0915 — один линейный сборщик на четыре пакета
    fix_stdout()
    load_env(ENV)
    stem_index, _gub, _reg = tr.load_indexes(api, TERR_DB, REG_DB)
    print(f"справочник территорий: {len(stem_index)} стемов")
    typed = [json.loads(ln) for ln in TYPED.open(encoding="utf-8") if ln.strip()]
    codes = json.loads(TYPE_CODES.read_text(encoding="utf-8"))
    src = {p: [json.loads(ln) for ln in (OUT / rel).open(encoding="utf-8") if ln.strip()]
           for p, rel in PACK_SRC.items()}

    rows_by_pack: dict[str, list[dict]] = defaultdict(list)
    rels_by_pack: dict[str, list[dict]] = defaultdict(list)
    dropped: list[dict] = []
    stat: Counter = Counter()

    for t in typed:
        pack, n = t["pack"], t["n"]
        r = src[pack][n]
        code = str(t.get("code") or "нет")
        if code not in codes:
            stat[f"отсев: {pack}"] += 1
            dropped.append({"pack": pack, "n": n, "title": t["title"][:160],
                            "class": t.get("class"), "code": code,
                            "why": t.get("code_why") or t.get("why") or ""})
            continue

        # ⚠️ РГИА ф. 380: из 62 новых записей чистые только четыре дела оп. 28.
        # Шесть дел оп. 39 — позиции В15–В17 реестра: многогубернские обзорные карты,
        # по которым нужно решение (отклонить формально или внести как «Европейскую
        # Россию»), плюс ложное срабатывание гейта — д. 1821 «реки Вагай и Демидовка»:
        # это ТОБОЛЬСКАЯ губерния, гейт взял её через город Демидов Смоленской.
        # Дела оп. 21 (52) заголовков не имеют: расшифровка описи ложится лишь на 20,
        # и у всех двадцати стоит метка «нужны глаза». Всё это — в спорные, не в каталог.
        if pack == "rgia380" and str(r.get("opis")) != "28":
            stat["отложено: rgia380 оп. 39 (спорные В15–В17)"] += 1
            dropped.append({"pack": pack, "n": n, "title": t["title"][:160],
                            "code": code, "why": "оп. 39 — решение пользователя, "
                                                 "спорные позиции В15–В17 реестра"})
            continue

        # ⚠️ ТЕРРИТОРИАЛЬНЫЙ ГЕЙТ для библиотечных карточек РГО и НЭБ.
        # Вопрос о ТИПЕ источника территории не касается (иначе модель браковала
        # общероссийские карты — поймано 11.11.2026), поэтому территорию отсекает
        # отдельный штатный гейт `territory_gate.classify`. Без него в каталог ушли бы
        # «Atlas zur Geographie des Herodot», «Album dei Porti» и «Hsi-Ngan-Fu»:
        # картографические по типу, но к четырём губерниям отношения не имеющие.
        #   наша   → территория из заголовка;
        #   общая  → «Европейская Россия» по правилу межгубернских карт;
        #   чужая  → отсев с записью решения;
        #   нет    → НЕ вносим автоматом: территория не названа, нужны глаза.
        terr_verdict = ""
        if pack in ("rgo", "neb"):
            blob = " ".join(str(r.get(k) or "") for k in
                            ("title", "description", "series")) + " " + terr_hint_text(t)
            terr_verdict, why_terr = classify(blob)
            if terr_verdict in ("чужая", "нет"):
                stat[f"отложено: {pack} территория «{terr_verdict}»"] += 1
                dropped.append({"pack": pack, "n": n, "title": t["title"][:160],
                                "code": code, "terr_verdict": terr_verdict,
                                "why": f"территориальный гейт: {why_terr}"})
                continue

        row = dict.fromkeys(COLUMNS + PROV_COLUMNS, "")
        row["Автор внесения"] = "Агент"
        row["Дата внесения"] = TODAY
        row["Статус приёмки"] = "кандидат"
        row["Язык"] = "Русский"
        row["DC Type"] = dc_type(code)
        row["Название источника"] = t["title"][:1900]

        level = str(t.get("level") or "")
        if level in ("Губерния", "Уезд", "Волость", "Нас. пункт", "Дача"):
            row["Административный уровень"] = level
            row["Административный уровень: источник значения"] = "из заголовка"
        else:
            row["Административный уровень: источник значения"] = "не установлен"

        terr_from_title = str(t.get("terr") or "").strip()
        # территория считается взятой из заголовка только если она реально матчится
        # со справочником каталога — иначе признак провенанса лгал бы (см. функцию)
        title_ok = bool(terr_from_title) and (
            title_terr_resolves(terr_from_title, stem_index)
            or any(s in terr_from_title.lower().replace("ё", "е")
                   for s in ("калуж", "перм", "смолен", "ярослав")))
        hints: list[str] = []
        note: list[str] = []

        if pack == "gaso":
            fond = str(r.get("fond") or "")
            row["Фонд"] = fond
            row["Опись"] = str(r.get("opis") or "")
            row["Единица хранения"] = str(r.get("delo") or "")
            row["Описание"] = (f"{r.get('fond_name') or ''} "
                               f"Крайние даты по описи: {r.get('dates') or '—'}.")[:1900]
            page = str(r.get("page") or "")
            row["Ссылка на онлайн-архив"] = (
                f"{GASO_BASE}/upload/images/lists_auto/{page}.jpg"
                f"#ф{fond}-о{r.get('opis')}-д{r.get('delo')}" if page else "")
            note.append("Ссылка ведёт на СКАН СТРАНИЦЫ ОПИСИ: портал ГАСО-Урал записей "
                        "дел не публикует, дела не оцифрованы.")
            row["Статус доступа"] = "Только метаданные"
            sh, size = sheets_and_size(r.get("sheets"))
            row["Листы / страницы"] = sh
            row["Размер листа (мм)"] = size
            if r.get("old_no"):
                note.append(f"Старый номер дела: {r['old_no']}.")
            if r.get("handwritten"):
                note.append("Часть значений в описи вписана ОТ РУКИ: "
                            + ", ".join(map(str, r["handwritten"]))[:200] + ".")
            if r.get("title_expanded"):
                note.append("Заголовок развёрнут из конвенции «То же» предыдущей строки "
                            "описи — проверить при сверке.")
            if r.get("year_fix"):
                note.append(f"Исправлена опечатка века в датах описи: {r['year_fix']}.")
            if r.get("note"):
                note.append(f"Примечание описи: {r['note']}.")
            if not title_ok:
                hints = FOND_TERR.get(fond, [])
        elif pack == "rgo":
            row["Описание"] = str(r.get("description") or "")[:1900]
            row["Автор / составитель"] = str(r.get("author") or "")[:300]
            row["Библиотечный шифр"] = str(r.get("shelf") or "")[:300]
            row["Ссылка на онлайн-архив"] = str(r.get("url") or "")
            row["Путь / URL к файлу"] = str(r.get("pdf") or "")
            row["Статус доступа"] = "Открытый доступ" if r.get("pdf") else "Только метаданные"
        elif pack == "neb":
            # ⚠️ У НЭБ в поле `sheets` лежит СЛОВАРЬ полей карточки (объём, год издания,
            # место издания, издательство, ответственность, библиотека), а не число листов.
            # Складывать его целиком в «Описание» значит потерять четыре отдельных поля.
            card = r.get("sheets") if isinstance(r.get("sheets"), dict) else {}
            for src_key, col in NEB_CARD.items():
                if card.get(src_key):
                    row[col] = str(card[src_key])[:300]
            row["Описание"] = " ".join(filter(None, [
                str(r.get("series") or ""),
                f"Издательство: {card['Издательство']}." if card.get("Издательство") else "",
                str(card.get("Язык Русский Еще Свернуть Общее примечание") or ""),
                f"Источник карточки: {r.get('source_card')}" if r.get("source_card") else "",
            ]))[:1900]
            row["Место хранения"] = str(r.get("holder") or card.get("Библиотека") or "")[:300]
            row["Ссылка на онлайн-архив"] = str(r.get("url") or "")
            row["Статус доступа"] = "Открытый доступ"
            if not r.get("year_lo") and card.get("Год издания"):
                yy = YEAR_RE.findall(str(card["Год издания"]))
                if yy:
                    r = {**r, "year_lo": int(yy[0]), "year_hi": int(yy[-1]),
                         "year_src": "из карточки НЭБ"}
            if r.get("scale_ctx"):
                note.append(f"Контекст масштаба в карточке: {r['scale_ctx']}.")
        else:  # rgia380
            row["Фонд"] = "380"
            row["Опись"] = str(r.get("opis") or "")
            row["Единица хранения"] = str(r.get("delo") or "")
            row["Описание"] = str(r.get("opis_annotation") or "")[:1900]
            row["Ссылка на онлайн-архив"] = str(r.get("url") or "")
            row["Статус доступа"] = "Только метаданные"
            if r.get("date_raw"):
                note.append(f"Даты по описи: {r['date_raw']}.")

        # --- год
        # У пакета РГИА полей года нет — разбираем даты описи сами. Квадратные скобки
        # в описи РГИА означают датировку, выведенную архивом, а широкий интервал у
        # позиции «планового архива» — крайние даты собрания, не дата дела.
        if pack == "rgia380" and r.get("date_raw") and not r.get("year_lo"):
            yy = [int(x) for x in YEAR_RE.findall(str(r["date_raw"]))]
            if yy:
                r = {**r, "year_lo": min(yy), "year_hi": max(yy),
                     "year_src": ("по крайним датам описи"
                                  if (max(yy) - min(yy)) > 25 else "из описи")}
        lo, hi = r.get("year_lo"), r.get("year_hi")
        if lo:
            row["Год создания (нижняя)"] = str(lo)
        if hi:
            row["Год создания (верхняя)"] = str(hi)
        row["Год: источник значения"] = YEAR_SRC.get(str(r.get("year_src")), "нет")

        # --- масштаб: только картографическим и только из описи/карточки
        if code.startswith("A") and r.get("scale"):
            row["Масштаб (знаменатель)"] = str(r["scale"])
            row["Оригинальный масштаб"] = str(r.get("scale_raw") or "")[:200]
            row["Масштаб: источник значения"] = SCALE_SRC.get(
                str(r.get("scale_src")), "не установлен")
        else:
            row["Масштаб: источник значения"] = "не установлен"
            if r.get("scale") and not code.startswith("A"):
                note.append("Масштаб в описи указан, но тип источника не картографический "
                            "— в числовое поле не писан.")

        # --- территория и её провенанс
        if terr_verdict == "общая" and not title_ok:
            # правило межгубернских карт: охват шире одной губернии → «Европейская Россия»
            hints = ["Европейская Россия"]
            row["Территория: источник значения"] = "по правилу межгубернских"
            note.append("Охват шире одной губернии — территория «Европейская Россия» "
                        "по правилу межгубернских карт.")
        elif title_ok:
            row["Территория: источник значения"] = "из заголовка"
        elif hints:
            row["Территория: источник значения"] = "по фондообразователю"
            note.append("Территория определена ПО ФОНДООБРАЗОВАТЕЛЮ "
                        f"({'; '.join(hints)}): в заголовке дела она не названа.")
        else:
            row["Территория: источник значения"] = "не установлена"

        note.append(f"Тип и уровень размечены моделью {TODAY} (код {code}"
                    + ("" if t.get("code_sure") is not False else ", предположительно")
                    + f"): {t.get('code_why') or ''}".rstrip(": "))
        row["Примечания"] = " ".join(note)[:1900]

        rows_by_pack[pack].append(row)
        rels_by_pack[pack].append({
            "url": row["Ссылка на онлайн-архив"],
            "relations": [
                {"property": "Архив хранения", "source_label": HOLDER[pack]},
                {"property": "Тип источника",
                 "target_url": "https://www.notion.so/" + codes[code].replace("-", "")},
            ],
            "territory_hints": hints,
        })
        stat[f"вносим: {pack}"] += 1
        stat[f"код {code}"] += 1

    WORK.mkdir(parents=True, exist_ok=True)
    for pack, rows in rows_by_pack.items():
        d = WORK / f"{pack}_review_run"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS + PROV_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        (d / "export_review.json").write_text(
            json.dumps({"records": rels_by_pack[pack]}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"{pack:8s} → {len(rows):5d} записей  {d}")

    with (WORK / "dropped.jsonl").open("w", encoding="utf-8") as f:
        for d in dropped:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"\nотсев: {len(dropped)} → {WORK / 'dropped.jsonl'}")
    print("\n--- сводка")
    for k, v in sorted(stat.items()):
        print(f"  {v:6d}  {k}")


if __name__ == "__main__":
    main()
