"""Атрибуция серий: какая из 58 карточек «Серийных массивов» стоит за записью каталога.

Зачем отдельный проход. Поле «Серия / массив» заполнено у 72 % каталога, а у записей,
внесённых 21–22.11 (3 003 шт.), оно пусто намеренно: метка `seriya` в улове — это след
СЛОВАРЯ ПОИСКА, а не атрибуция. Проверено на примерах: «Памятная книжка Смоленской
губернии» помечена «серия 10 — трёхвёрстка», ПСЗ — «серия 5 — Вильбрехт»; у 539 записей
меток сразу 3–5. Перенос такой метки дал бы массив ложных связей.

Решает модель по смыслу заголовка, а не подстрокой: названия серий в карточках и в
библиотечных описаниях расходятся («Волости и гмины 1890 года» против «Статистика
Российской империи. Т. 22»), и сходство строк тут не работает.

  python attribute_series.py submit [--limit N]
  python attribute_series.py collect
  python attribute_series.py apply [--dry-run]     # проставить relation в каталоге
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import anthropic_client, fix_stdout, load_env  # noqa: E402

OUT = ROOT / "output"
WORK = OUT / "series_attr_2026-11-22"   # переопределяется флагом --work
SPRAV = OUT / "serii_spravochnik.json"
RUNS = [OUT / "upload_2026-11-21" / "review_run",
        OUT / "upload_2026-11-21-obzor" / "review_run"]
MODEL = "claude-sonnet-5"
PER_REQ = 20

SYSTEM_TMPL = """Ты относишь ЗАПИСИ каталога исторических географических источников
(Калужская, Пермская, Смоленская, Ярославская губернии, XVIII — начало XX в.)
к СЕРИЙНЫМ МАССИВАМ — изданиям и съёмкам, выходившим по единой программе.

СПИСОК СЕРИЙ (код, годы, название, алиасы):
{SERIES}

ПРАВИЛА.
1. Серию ставь, только если запись — ЧАСТЬ этого массива: лист, том, выпуск, губернский
   том издания. Совпадение темы или губернии серией НЕ является.
2. Годы записи должны укладываться в хронологию серии; выход за границы — сигнал ошибки.
3. Одна запись — одна серия. Если подходят две, выбирай ТУ, ЧТО НЕСЁТ БОЛЬШЕ СОДЕРЖАНИЯ
   О САМОМ ИСТОЧНИКЕ: масштаб, единицу деления, условные знаки, охват, норму точности.
   Связь с серией нужна, чтобы запись унаследовала это знание, а не ради библиографии.
4. ИЗДАТЕЛЬСКУЮ ОБОЛОЧКУ НЕ СТАВЬ, ПОКА ЕСТЬ ПОДХОДЯЩАЯ СЕРИЯ. «Статистика Российской империи», «Временник
   ЦСК МВД», «Статистический временник Российской империи» — это переплёт, под которым
   ЦСК выпускал разные работы, а не серия по содержанию. У них заполнено 3 поля из 9
   против 9 из 9 у картографических серий, разрыв в содержании двенадцатикратный.
   Принадлежность к оболочке наследуется через поле «Входит в оболочку» у самой серии.
   Запись «Волости и гмины 1890 года… (Статистика Российской империи; 22)» относится
   к серии «Волости и гмины 1890 года», и только к ней.
   Если же СВОЕЙ серии у записи нет (в списке её просто не завели), оболочку поставить
   можно — она хотя бы фиксирует издание и номер тома. Такие случаи важны: каждый из них
   указывает на ПРОБЕЛ в справочнике серий и идёт отдельным списком на заведение карточки.
5. Исключение к правилу 3: если лист существует и как рукописный ОРИГИНАЛ съёмки, и как
   ИЗДАННАЯ карта, выбирай происхождение листа, а не издание, — даже если карточка
   изданной серии разобрана подробнее. Содержательность не отменяет провенанс.
6. Сомневаешься — ставь "нет". Пустое поле честнее неверной связи: ложную связь потом
   не отличить от верной, а пустую легко долить.
7. sure=true только когда в заголовке есть прямое указание на издание серии
   (название серии, её номер тома/выпуска, узнаваемая формула). Иначе sure=false.

ФОРМАТ ОТВЕТА - по строке на запись, ничего лишнего:
<номер>|<код серии или нет>|<true/false>|<обоснование до 60 знаков>
"""


def series_block() -> tuple[str, dict[str, str]]:
    """Список серий для промпта и карта «код -> page_id»."""
    rows = json.loads(SPRAV.read_text(encoding="utf-8"))
    lines, by_code = [], {}
    for i, s in enumerate(rows, 1):
        code = "S%02d" % i
        by_code[code] = s["id"]
        years = "%s-%s" % (s["lo"] or "?", s["hi"] or "?")
        alias = (s["alias"] or "").replace("\n", " ")[:150]
        line = "%s [%s] %s" % (code, years, s["name"])
        if alias:
            line += " | алиасы: " + alias
        lines.append(line)
    return "\n".join(lines), by_code


def rows_to_do() -> list[dict]:
    """Записи, внесённые 21-22.11: page_id из журналов, заголовок из пакетов.

    ⚠️ ЖУРНАЛ ЗАЛИВКИ БЫВАЕТ НЕПОЛНЫМ — на этот сборщик нельзя опираться слепо.
    22.11.2026 убитый системой прогон успел создать страницу и не успел записать строку
    (`lib.permkrai.ru/node/14035` лежит в базе с 12:01, строки в `created_pages.jsonl` нет),
    а сам журнал содержал 484 пары дублей: мост повторял запрос создания после таймаута.
    Поэтому для набора 4.1 вход собирался в обход этой функции — из `pages_state.jsonl`
    (опрос каждой страницы по её номеру, `verify_pages_by_id_2026_11_22.py`) с исключением
    снятых в корзину и 270 отклонённых вне скоупа. Готовый `input.jsonl` кладётся в папку
    прогона, и `submit` берёт его, а не пересобирает (см. комментарий в submit).

    Правило на будущее: состав атрибуции брать из сверки по номерам страниц, а журнал
    заливки считать подсказкой, а не источником истины
    (память `feedback_upload-acceptance-by-page-id-journal`).
    """
    meta = {}
    for pack in (OUT / "upload_2026-11-21" / "paket_k_zalivke.jsonl",
                 OUT / "upload_2026-11-21-obzor" / "paket_k_zalivke.jsonl"):
        if not pack.exists():
            continue
        for ln in pack.open(encoding="utf-8"):
            r = json.loads(ln)
            u = (r.get("istochnik_kartochki") or r.get("url") or "").rstrip("/")
            meta[u] = r
    out = []
    for run in RUNS:
        jr = run / "created_pages.jsonl"
        if not jr.exists():
            continue
        for ln in jr.open(encoding="utf-8"):
            try:
                j = json.loads(ln)
            except Exception:
                continue
            r = meta.get((j.get("url") or "").rstrip("/"))
            if not r:
                continue
            year = "%s-%s" % (r.get("год_нижний") or "", r.get("год_верхний") or "")
            out.append({"page_id": j["page_id"],
                        "title": (r.get("zagolovok_polnyi") or "")[:300],
                        "year": year.strip("-"),
                        "klass": r.get("class", "")})
    return out


def submit(limit: int | None) -> None:
    load_env()
    client = anthropic_client()
    block, _ = series_block()
    # 22.11.2026: если в папке прогона уже лежит input.jsonl — берём его, а не пересобираем.
    # Иначе повторная атрибуция подмножества молча превращается в прогон по всему набору
    # (так ушло 153 запроса вместо 8).
    inp = WORK / "input.jsonl"
    rows = ([json.loads(x) for x in inp.open(encoding="utf-8")] if inp.exists()
            else rows_to_do())
    if inp.exists():
        print("взят готовый вход: %s" % inp)
    if limit:
        rows = rows[:limit]
    print("записей к атрибуции: %d" % len(rows))
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "input.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    reqs = []
    for k in range(0, len(rows), PER_REQ):
        chunk = rows[k:k + PER_REQ]
        body = "\n".join(
            "%d. [%s] [%s] %s" % (k + j, r["klass"], r["year"] or "год не указан", r["title"])
            for j, r in enumerate(chunk))
        reqs.append({"custom_id": "s%d" % k,
                     "params": {"model": MODEL, "max_tokens": 4000,
                                "system": SYSTEM_TMPL.replace("{SERIES}", block),
                                "messages": [{"role": "user", "content": body}]}})
    batches = []
    for i in range(0, len(reqs), 100):
        b = client.messages.batches.create(requests=reqs[i:i + 100])
        batches.append({"id": b.id, "n": len(reqs[i:i + 100])})
        print("  пакет %s: %d запросов" % (b.id, len(reqs[i:i + 100])))
    (WORK / "batches.json").write_text(json.dumps(batches, ensure_ascii=False), encoding="utf-8")
    print("отправлено %d запросов" % len(reqs))


def collect() -> None:
    load_env()
    client = anthropic_client()
    rows = [json.loads(x) for x in (WORK / "input.jsonl").open(encoding="utf-8")]
    res: dict[int, dict] = {}
    pending = 0
    for b in json.loads((WORK / "batches.json").read_text(encoding="utf-8")):
        info = client.messages.batches.retrieve(b["id"])
        if info.processing_status != "ended":
            print("  %s: %s" % (b["id"], info.processing_status))
            pending += 1
            continue
        for item in client.messages.batches.results(b["id"]):
            if item.result.type != "succeeded":
                continue
            # у модели с размышлением content[0] — ThinkingBlock, текста в нём нет:
            # берём первый блок типа "text", иначе падаем на AttributeError (21.11.2026)
            text = next((b.text for b in item.result.message.content
                         if getattr(b, "type", "") == "text"), "")
            for line in text.splitlines():
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3 or not parts[0].isdigit():
                    continue
                res[int(parts[0])] = {"code": parts[1],
                                      "sure": parts[2].lower() == "true",
                                      "why": parts[3] if len(parts) > 3 else ""}
    if pending:
        print("ещё обрабатывается пакетов: %d" % pending)
    with (WORK / "attributed.jsonl").open("w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            r.update(res.get(i, {}))
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    got = [r for r in rows if r.get("code") and r["code"].lower() != "нет"]
    print("\nразмечено %d из %d" % (len(res), len(rows)))
    print("серия определена: %d | уверенно: %d"
          % (len(got), sum(1 for r in got if r.get("sure"))))
    print("топ серий:", dict(Counter(r["code"] for r in got).most_common(8)))


def apply(dry: bool) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "nu", ROOT / "scripts" / "notion_upload_candidates.py")
    nu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nu)
    _, by_code = series_block()
    rows = [json.loads(x) for x in (WORK / "attributed.jsonl").open(encoding="utf-8")]
    # 22.11.2026 (решение владельца): связь ставим ТОЛЬКО с настоящей серией.
    # Издательская оболочка («Статистика Российской империи» и подобные) в поле не идёт —
    # она несёт 3 заполненных поля из 9 против 9 из 9 у картографических серий, то есть
    # меняет содержательную связь на библиографическую. Записи, у которых своей серии в
    # справочнике нет, откладываются списком кандидатов на заведение новых карточек.
    sprav = {("S%02d" % (i + 1)): x for i, x in
             enumerate(json.loads(SPRAV.read_text(encoding="utf-8")))}
    todo, shells = [], []
    for r in rows:
        if not (r.get("sure") and r.get("code") in by_code):
            continue
        (shells if sprav[r["code"]]["type"] == "издательская оболочка" else todo).append(r)
    if shells:
        (WORK / "kandidaty_novyh_seriy.json").write_text(
            json.dumps([{"title": x["title"], "page_id": x["page_id"],
                         "shell": sprav[x["code"]]["name"]} for x in shells],
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print("отложено как кандидаты в новые серии: %d" % len(shells))
    # уже проставленное не трогаем: journal applied.jsonl — источник правды о сделанном
    jpath = WORK / "applied.jsonl"
    done_ids = set()
    if jpath.exists():
        for ln in jpath.open(encoding="utf-8"):
            try:
                done_ids.add(json.loads(ln)["page_id"])
            except Exception:
                continue
    before = len(todo)
    todo = [r for r in todo if r["page_id"] not in done_ids]
    if before != len(todo):
        print("уже проставлено ранее: %d" % (before - len(todo)))
    print("к проставлению (только уверенные): %d" % len(todo))
    done, err = 0, 0
    with (WORK / "applied.jsonl").open("a", encoding="utf-8") as jrn:
        for r in todo:
            if dry:
                done += 1
                continue
            try:
                nu.api("PATCH", "https://api.notion.com/v1/pages/" + r["page_id"],
                       {"properties": {"Серия / массив":
                                       {"relation": [{"id": by_code[r["code"]]}]}}})
                jrn.write(json.dumps({"page_id": r["page_id"], "code": r["code"]},
                                     ensure_ascii=False) + "\n")
                jrn.flush()
                done += 1
                if done % 100 == 0:
                    print("  %d/%d" % (done, len(todo)), flush=True)
            except Exception as e:
                err += 1
                if err <= 3:
                    print("  ошибка %s: %s" % (r["page_id"][:8], str(e)[:90]))
    print("%sпроставлено: %d | ошибок: %d" % ("DRY-RUN " if dry else "", done, err))


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "collect", "apply"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--work", help="папка прогона (по умолчанию series_attr_2026-11-22)")
    a = ap.parse_args()
    if a.work:
        global WORK
        WORK = OUT / a.work
    if a.cmd == "submit":
        submit(a.limit)
    elif a.cmd == "collect":
        collect()
    else:
        apply(a.dry_run)


if __name__ == "__main__":
    main()
