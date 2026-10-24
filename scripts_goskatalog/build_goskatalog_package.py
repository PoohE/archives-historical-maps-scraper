"""Госкаталог: собрать найденные предметы в пакет каталога и прогнать гейтом.

Источник — Государственный каталог Музейного фонда РФ. Прогон 20.10: 28 запросов,
1406 уникальных предметов, 1398 со ссылками на изображения.

⚠️ Чем он отличается от архивов и библиотек:
 * это МУЗЕЙНЫЙ фонд — рядом с картами лежат почтовые карточки «Калужская губерния»,
   костюмы, этнографические снимки; предметный гейт обязателен;
 * у предметов ЕСТЬ сканы: `/muzfo-imaginator/rest/images/public/original/<id>/<id>.jpg`.
   В выдаче путь содержит `/350/` — это превью на 16 КБ; `original` даёт полный файл
   (137 КБ на пробе, в 8 раз крупнее). В каталог идёт `url_skana` (original), превью
   сохранено в `url_skana_preview`;
 * выдача отдаёт максимум 100 карточек на запрос, а «Найдено» бывает 2219 — то есть по
   широким запросам взята верхушка. Полнота НЕ доказана, расширяется дроблением запросов.

Гейт: общий `false_carto` (ловушки «карточка/картотека», «литературная карта»,
«чертёж родословного дерева», чужие территории) + картографический признак + губернии.

Запуск:
    python -B scripts_goskatalog/build_goskatalog_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from false_carto import alien_hit, is_false_carto, not_a_place  # noqa: E402
from scope_rules import (BUILDING, BUILDING_EXCEPT, MAP_COMPANION,  # noqa: E402
                         MEZHEVYE, TERRITORY, territories)

SRC = ROOT / "output" / "goskatalog_20261020" / "goskatalog_cards.jsonl"
OUT = ROOT / "output" / "goskatalog_package_20261021"

CARTO = re.compile(r"\bкарт[аыуеой]\b|\bкарты\b|\bкарт\b|\bплан[ыаеу]?\b|\bпланов\b|атлас"
                   r"|чертеж|чертёж|съемк|съёмк|топограф|межев|картосхем|план-схем"
                   r"|картограмм|глобус", re.I)
# ⚠️ ЛОКАЛЬНОГО ПЕРЕЧНЯ ГУБЕРНИЙ ЗДЕСЬ БОЛЬШЕ НЕТ (удалён 22.10). Копия жила
# своей жизнью и расходилась с общей: в ней «Ярослав» шёл без отрицательного
# lookbehind и ловился внутри «МалоЯРОСЛАВецкий», а «Ростовск» — без уездного
# контекста, то есть вместе с Ростовом-на-Дону. Территория берётся только из
# `scope_rules.territories()`.

# Листы, снятые приёмкой поимённо: заголовок не даёт гейту зацепки, решение
# принято человеком по содержанию листа.
RUCHNOJ_OTSEV = {
    "44288696": "серия «города-заводы Урала», лист 11: генплан завода и здание конторы — постройки (решение пользователя 22.10)",
    "44288693": "серия «города-заводы Урала», лист 13: церковь и ворота — постройки",
    "44288695": "серия «города-заводы Урала», лист 16: церковь и дом заводовладельца — постройки",
}

# Музейная специфика: предмет с названием губернии, но не карта
MUSEUM_NOT_MAP = re.compile(
    r"почтов\w+\s+карточк|открытк|костюм|фотограф|портрет|значок|медал|монет|марка"
    r"|сувенир|тарелк|платок|полотенц|вышивк|игрушк", re.I)
YEAR = re.compile(r"\b(1[5-9]\d{2}|19[0-8]\d)\b")
LIMIT = 1989  # правило пользователя: для библиотек и музеев верхняя граница 1989 г.


IMG = re.compile(r"/images/public/(?:original|350|\d+)/(\d+)/", re.I)


def skan_urls(card: dict) -> tuple[str, str]:
    """(ссылка на полный файл, ссылка на превью) из любой формы ссылки карточки.

    ⚠️ Добор клал в `url_skana` превью `/350/` — на вид ссылка есть, а ведёт она на
    картинку 16 КБ. Поэтому id изображения вынимается из ЛЮБОЙ ссылки карточки, а оба
    адреса собираются заново.
    """
    base = "https://goskatalog.ru/muzfo-imaginator/rest/images/public"
    for key in ("url_skana", "url_skana_preview"):
        m = IMG.search(str(card.get(key, "")))
        if m:
            img = m.group(1)
            return f"{base}/original/{img}/{img}.jpg", f"{base}/350/{img}/{img}.jpg"
    return "", ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="папка пакета (по умолчанию — исходная)")
    # ⚠️ Добор 21.10 довёл выборку с 1406 до 3433 предметов, а первые 1406 УЖЕ разобраны
    # и внесены (946 принято + 86 needs_human + 374 отсев). Чтобы приёмщик не получил
    # дубли, пакет добора собирается только по НОВЫМ id: сюда передаётся папка прежнего
    # пакета, все встреченные там predmet_id исключаются.
    ap.add_argument("--exclude-from", default="",
                    help="папка прежнего пакета: его predmet_id исключить из нового")
    args = ap.parse_args()
    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)

    seen_before: set[str] = set()
    if args.exclude_from:
        for f in Path(args.exclude_from).glob("*.jsonl"):
            for ln in f.open(encoding="utf-8"):
                try:
                    seen_before.add(str(json.loads(ln)["predmet_id"]))
                except Exception:  # noqa: BLE001, S112
                    continue
        print(f"исключаю уже разобранные ранее: {len(seen_before)} предметов")

    rows = []
    for ln in SRC.open(encoding="utf-8"):
        c = json.loads(ln)
        t = (c.get("zagolovok") or "").strip()
        if not t:
            continue
        if str(c["predmet_id"]) in seen_before:
            continue
        gub = territories(t)
        yy = YEAR.findall(t)
        rec = {
            "predmet_id": c["predmet_id"],
            "zagolovok": t,
            "data": max(yy) if yy else "",
            "territoriya": "; ".join(gub),
            "url": c["url"],
            "url_skana": skan_urls(c)[0],
            "url_skana_preview": skan_urls(c)[1],
            "sposob": "Госкаталог Музейного фонда РФ",
            "zapros": c.get("zapros", ""),
        }
        # Класс: межевые книги и сопроводительные документы о межевании — отдельно
        # (решение пользователя: вносить их не вместе с картами)
        rec["klass"] = ("межевые книги"
                        if MEZHEVYE.search(t) or re.search(r"землеустроительн\w+\s+работ|межев\w+\s+работ", t, re.I)
                        else "картография")
        # ⚠️ ПРАВИЛО МАСШТАБА ОБЪЕКТА: постройка — не источник, территория — источник
        is_building = bool(BUILDING.search(t)) and not BUILDING_EXCEPT.search(t)
        # Книга/брошюра берётся, только если она сопровождает карту или межевые работы
        is_book = bool(re.search(r"^(?:книга|брошюра)[.:]|сб(?:орник)?\.?\s+очерк|\[Текст\]", t, re.I))
        book_ok = bool(MAP_COMPANION.search(t)) or bool(TERRITORY.search(t) and re.search(r"план\w*\s+хозяйств", t, re.I))
        fc = is_false_carto(t)
        al = alien_hit(t)
        # Название губернии в титуле владельца («наместника Тульского и Калужского»)
        # территорию не задаёт — такие записи идут человеку, а не в каталог
        nap = not_a_place(t)
        if str(rec["predmet_id"]) in RUCHNOJ_OTSEV:
            rec["gate"] = "отсев"
            rec["gate_reason"] = RUCHNOJ_OTSEV[str(rec["predmet_id"])]
        elif is_building:
            rec["gate"], rec["gate_reason"] = "отсев", "план постройки/объекта, не территории (правило масштаба 21.10)"
        elif is_book and not book_ok:
            rec["gate"], rec["gate_reason"] = "отсев", "книга/брошюра не о карте и не о межевых работах"
        elif MUSEUM_NOT_MAP.search(t):
            rec["gate"], rec["gate_reason"] = "отсев", "музейный предмет, не карта (открытка, костюм и т.п.)"
        elif fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif not CARTO.search(t):
            rec["gate"], rec["gate_reason"] = "отсев", "картографического признака в названии нет"
        elif not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в названии не названа"
        elif nap:
            rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
        elif al:
            rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
        elif yy and int(max(yy)) > LIMIT:
            rec["gate"], rec["gate_reason"] = "needs_human", f"издание {max(yy)} > {LIMIT}"
        else:
            rec["gate"], rec["gate_reason"] = "принято", "карта + территория проекта"
        rows.append(rec)

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("goskatalog_accepted", acc)
    dump("goskatalog_needs_human", nh)
    dump("goskatalog_scope_drops", drop)

    print(f"предметов: {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print(f"\nсо ссылкой на скан: {sum(1 for r in acc if r['url_skana'])} из {len(acc)}")
    print(f"с датой: {sum(1 for r in acc if r['data'])}")
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
