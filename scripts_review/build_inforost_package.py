"""Пакет каталога для библиотек на движке ИнфоРост (ГПИБ, ЭБИД) — один сборщик на оба.

Правило второго раза: `elib.shpl.ru` (ГПИБ) и `docs.historyrussia.org` (ЭБИД) — один
и тот же движок, карточки разбираются одним парсером, поэтому и пакет собирается одним
скриптом с параметром источника, а не двумя почти одинаковыми файлами.

ЧЕМ БИБЛИОТЕКА ОТЛИЧАЕТСЯ ОТ АРХИВА И МУЗЕЯ (почему гейт тут другой):
 1. Единица — ИЗДАНИЕ или ТОМ, а не лист карты. Поэтому принимаем два класса:
    `картография` (карта, атлас, план, межевание, съёмка) и `пространственное описание`
    (статистическое и топографическое описание, список населённых мест, памятная книжка,
    материалы для географии и статистики, военно-статистическое обозрение, труды
    губстаткомитета). Второй класс в проекте идёт наравне с картами.
 2. ⚠️ КАРТА ЧАСТО СПРЯТАНА В ПРИЛОЖЕНИИ ТОМА, и это самое ценное: «Т. 5… Вып. 1 :
    с приложением 8-ми генеральных поволостных планов». Такие тома помечаются
    `prilozhenie_karta = да`.
 3. Правило пользователя: для библиотек верхняя граница — 1989 год включительно.
 4. Территория проверяется по данным КАРТОЧКИ, а не по тексту запроса.

⚠️ ДВА ПОТОКА ЗАПИСЕЙ (устройство переделано 22.10.2026):
  * `--src` — карточки изданий и томов (`gpib_nodes.jsonl`);
  * `--maps` — САМИ КАРТЫ из разделов «Карты» (`gpib_maps.jsonl`). Их собирает
    `scripts_gpib/gpib_fetch_maps.py`: у ГПИБ карта лежит на третьем уровне
    (издание → том → раздел «Карты» → карта), и без второго потока в пакет попадала
    ровно ОДНА карта на 200 записей.
  * `--scans` — ссылки на сканы и число листов (`gpib_scans.jsonl`), чтобы у каждой
    принятой записи стояли `url_skana` и `stranic`.
  * `--raspoznano` — результат чтения одностраничных карт зрением (масштаб, год,
    объекты): правило пользователя «есть скан карты — поднять с него масштаб и год».

ПРАВИЛА ТЕРРИТОРИИ И КЛАССА ЖИВУТ В `scripts_review/scope_rules.py` — здесь их копий
НЕТ. Локальный дубль перечня губерний уже стоил ошибки: «Ярослав» без отрицательного
lookbehind ловился внутри «МалоЯРОСЛАВецкий» и вешал Ярославскую губернию на калужские
издания (node 78312/78313).

Запуск:
    python -B scripts_review/build_inforost_package.py \
        --src output/gpib_yandex_20261021/gpib_nodes.jsonl \
        --maps output/gpib_yandex_20261021/gpib_maps.jsonl \
        --scans output/gpib_yandex_20261021/gpib_scans.jsonl \
        --raspoznano output/gpib_yandex_20261021/gpib_maps_raspoznano.json \
        --out output/gpib_package_20261021 --istochnik ГПИБ
    python -B scripts_review/build_inforost_package.py --src output/ebid_20261021/ebid_nodes.jsonl --out output/ebid_package_20261021 --istochnik ЭБИД
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from false_carto import alien_hit, is_false_carto, not_a_place  # noqa: E402
from scope_rules import (  # noqa: E402
    CARTO,
    LIMIT,
    PRILOZHENIE,
    god_iz,
    klass,
    territories,
)

# Записи, снятые приёмкой пользователя поимённо. Держим списком с причиной: иначе
# при следующей пересборке пакета они возвращаются, и решение приходится принимать
# заново (21.10: «Торжественное заседание…» — мероприятие, а не источник).
RUCHNOJ_OTSEV = {
    "51969": "решение пользователя 21.10: торжественное заседание — мероприятие, не источник",
}


# Верхние разделы электронной библиотеки — в пути, а не тома.
RAZDELY_BIBLIOTEKI = {"9347", "9500", "10187", "9806", "9501", "9502"}


def _norm(s: object) -> str:
    return " ".join(str(s or "").split()).lower()


def tomov_v_izdanii(c: dict) -> int:
    """Сколько томов у издания.

    ⚠️ `deti` в карточке ИнфоРоста — НЕ список детей, а ПУТЬ СВЕРХУ ВНИЗ плюс
    дети в хвосте: [корень библиотеки, раздел, …промежуточные узлы…, РОДИТЕЛЬ,
    том, том, …]. Брать `len(deti)` нельзя: 24.10 claude-45 нашла, что у каждого
    тома «Статистического описания Калужской губернии» стояло 3 тома (это две
    крошки плюс родитель), а у корня 13 вместо 11.

    Длина пути переменная — между разделом и родителем попадаются узлы-коллекции
    («Симбирская губернская ученая архивная комиссия», «Сборник военно-исторических
    материалов (серия)»), поэтому фиксированным числом крошки не отсчитать.
    Границу задаёт родитель: всё до него включительно — путь, хвост — тома.
    Ищем его по `roditelskoe` ПО ВСЕМУ списку (сразу за разделами он не обязан
    стоять). Нет родителя — запись сама корень, путь из одних разделов.
    """
    deti = c.get("deti") or []
    if not deti:
        return int(c.get("deti_n") or 0)
    rod = _norm(c.get("roditelskoe"))
    if rod:
        klyuch = rod[:30]
        for i in range(len(deti) - 1, -1, -1):
            if _norm(deti[i].get("zagolovok")).startswith(klyuch):
                return len(deti) - i - 1
    i = 0
    while i < len(deti) and str(deti[i].get("node_id")) in RAZDELY_BIBLIOTEKI:
        i += 1
    return len(deti) - i


def load_jsonl(path: Path | None) -> list[dict]:
    if not path or not path.exists():
        return []
    out = []
    for ln in path.open(encoding="utf-8"):
        try:
            out.append(json.loads(ln))
        except Exception:  # noqa: BLE001, S112
            continue
    return out


def main() -> int:  # noqa: PLR0912, PLR0915
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--maps", default="")
    ap.add_argument("--scans", default="")
    ap.add_argument("--raspoznano", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--istochnik", required=True)
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    scans = {str(r["node_id"]): r for r in load_jsonl(Path(args.scans) if args.scans else None)}
    rasp = {}
    if args.raspoznano and Path(args.raspoznano).exists():
        rasp = {str(r["node_id"]): r
                for r in json.loads(Path(args.raspoznano).read_text(encoding="utf-8"))}

    # ⚠️ ЛИСТЫ КАРТ ОПОЗНАЮТСЯ ПО МЕСТУ, А НЕ ПО ЗАГОЛОВКУ. Карта в разделе «Карты»
    # часто подписана без картографического слова — «Соликамск Пермской губернии»,
    # «Екатеринбург». Такие записи гейт отсеивал как «ни картографии, ни описания»
    # (22.10: 391 «План Пермской губернии города Соликамска» — настоящая карта,
    # распознанная зрением, ушла в отсев). Лист карты = запись из раздела «Карты»,
    # у которой ОДНА страница либо картографическое слово в заголовке; многолистные
    # тома того же раздела («Труды архивной комиссии. Вып. 5», 144 с.) листами карт
    # не считаются и проходят обычный гейт.
    map_rows = load_jsonl(Path(args.maps) if args.maps else None)
    LIST_KART = {str(m.get("node_id", "")) for m in map_rows
                 if m.get("stranic") == 1
                 or CARTO.search(m.get("zagolovok") or "")}

    rows: list[dict] = []
    seen: set[str] = set()

    # --- поток 1: карточки изданий и томов -------------------------------------
    for c in load_jsonl(src):
        title = (c.get("zaglavie") or c.get("zagolovok") or "").strip()
        blob = " ".join(str(c.get(k, "")) for k in
                        ("zaglavie", "zagolovok", "bibl_opisanie", "roditelskoe",
                         "primechanie", "mesto", "kollekcii"))
        if not title and not blob.strip():
            continue
        gub = territories(blob)
        god, god_num = god_iz(blob, str(c.get("god") or ""), title)
        nid = str(c.get("node_id", ""))
        kl = klass(blob, carto_ok=not is_false_carto(blob))
        if nid in LIST_KART and not is_false_carto(title):
            kl = "картография"
        pril = bool(PRILOZHENIE.search(blob))
        rec = {
            "node_id": nid,
            "zagolovok": title,
            "roditelskoe": c.get("roditelskoe", ""),
            "god": god,
            "mesto": c.get("mesto", ""),
            "izdatel": c.get("izdatel", ""),
            "tip_izdaniya": c.get("tip_izdaniya", ""),
            "klass": kl,
            "prilozhenie_karta": "да" if pril else "",
            "territoriya": "; ".join(gub),
            "bibl_opisanie": (c.get("bibl_opisanie") or "")[:700],
            "url": c.get("url", ""),
            # ⚠️ не `len(deti)`: там лежит ПУТЬ сверху вниз вместе с детьми,
            # и том получал «3 тома» (две крошки + родитель). См. tomov_v_izdanii.
            "tomov": tomov_v_izdanii(c),
            "zapros": c.get("zapros", ""),
            "istochnik": args.istochnik,
            "uroven": "лист карты" if nid in LIST_KART else "издание/том",
        }
        rows.append(gate(rec, title, blob, kl, gub, god_num, pril))
        seen.add(nid)

    # --- поток 2: сами карты из разделов «Карты» --------------------------------
    for m in map_rows:
        nid = str(m.get("node_id", ""))
        if nid in seen:
            continue
        title = (m.get("zagolovok") or "").strip()
        blob = " ".join(str(m.get(k, "")) for k in
                        ("zagolovok", "bibl_opisanie", "iz_izdaniya", "izdanie_verhnee"))
        gub = m.get("territoriya") or ""
        gub = [g for g in gub.split("; ") if g] or territories(blob)
        god, god_num = god_iz(blob, str(m.get("god") or ""), title)
        kl = klass(blob, carto_ok=not is_false_carto(blob))
        if nid in LIST_KART and not is_false_carto(title):
            kl = "картография"
        rec = {
            "node_id": nid,
            "zagolovok": title,
            "roditelskoe": m.get("iz_izdaniya", ""),
            "god": god,
            "mesto": "",
            "izdatel": "",
            "tip_izdaniya": "карта (лист)",
            "klass": kl,
            "prilozhenie_karta": "",
            "territoriya": "; ".join(gub),
            "bibl_opisanie": (m.get("bibl_opisanie") or "")[:700],
            "url": m.get("url", ""),
            "tomov": 0,
            "zapros": "",
            "istochnik": args.istochnik,
            "uroven": "лист карты" if nid in LIST_KART else "раздел издания",
        }
        rows.append(gate(rec, title, blob, kl, gub, god_num, pril=False))
        seen.add(nid)

    # --- скан и число листов ----------------------------------------------------
    # Два источника ссылок: отдельный добор `gpib_scans.jsonl` (шёл по старому
    # пакету) и сам `gpib_maps.jsonl` — обход разделов «Карты» снимает page_id
    # прямо при чтении карточки. Без второго у листов карт ссылка пустая.
    from_maps = {str(m.get("node_id", "")): m for m in map_rows}
    for r in rows:
        s = scans.get(r["node_id"]) or from_maps.get(r["node_id"]) or {}
        r["stranic"] = s.get("stranic", "")
        r["url_skana"] = s.get("url_skana", "")
        r["original_px"] = s.get("original_px", "")

    # --- распознанное с карты (масштаб, год, объекты) ---------------------------
    for r in rows:
        d = rasp.get(r["node_id"])
        r["masshtab_s_karty"] = (d or {}).get("masshtab", "")
        r["god_s_karty"] = (d or {}).get("god_s_karty", "")
        r["sostavitel_s_karty"] = "; ".join(
            x for x in ((d or {}).get("sostavitel_izdatel", ""),
                        (d or {}).get("pechat", "")) if x)
        r["uslovnye_znaki"] = (d or {}).get("uslovnye_znaki", "")
        r["obekty_s_karty"] = (d or {}).get("obekty", "")
        r["primechanie_raspozn"] = (d or {}).get("primechanie", "")

    # --- поимённый ручной отсев -------------------------------------------------
    for r in rows:
        if r["node_id"] in RUCHNOJ_OTSEV:
            r["gate"] = "отсев"
            r["gate_reason"] = RUCHNOJ_OTSEV[r["node_id"]]

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]
    slug = args.istochnik.lower()

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        cols = list(dict.fromkeys(k for r in data for k in r))
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump(f"{slug}_accepted", acc)
    dump(f"{slug}_needs_human", nh)
    dump(f"{slug}_scope_drops", drop)

    print(f"{args.istochnik}: записей {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо уровням (принято):")
    for k, n in Counter(r["uroven"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпо классам (принято):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print(f"\nс картой в приложении: {sum(1 for r in acc if r['prilozhenie_karta'])}")
    print(f"со ссылкой на скан:    {sum(1 for r in acc if r['url_skana'])}")
    print(f"с распознанным масштабом: {sum(1 for r in acc if r['masshtab_s_karty'])}")
    print(f"с годом: {sum(1 for r in acc if r['god'])}")
    print(f"\n→ {out}")
    return 0


def gate(rec: dict, title: str, blob: str, kl: str, gub: list[str],
         god_num: int | None, pril: bool) -> dict:
    """Решение гейта по одной записи."""
    fc = is_false_carto(title)
    nap = not_a_place(blob)
    al = alien_hit(blob)
    if fc:
        rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
    elif not kl:
        rec["gate"], rec["gate_reason"] = "отсев", "ни картографии, ни пространственного описания"
    elif not gub:
        rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в карточке не названа"
    elif nap:
        rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
    elif al:
        rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
    elif god_num and god_num > LIMIT:
        rec["gate"], rec["gate_reason"] = "needs_human", f"издание {god_num} > {LIMIT}"
    else:
        rec["gate"] = "принято"
        rec["gate_reason"] = (f"{kl} + территория проекта"
                              + (" + карта в приложении" if pril else ""))
    return rec


if __name__ == "__main__":
    raise SystemExit(main())
