"""Серия «Карты и атласы наместничеств (1775–1796)»: план → привязка к карточке серии + заполнение
пустых полей серии (масштаб по Jeske 2023 / надписям, проекция, меридиан, техника, уровень, язык, DC Type).
Режимы и чекпойнт — как в mezh_batch_tag.py (plan / apply / verify, done.jsonl).

  python nam_batch_fill.py plan   --run nam_2026-11-05
  python nam_batch_fill.py apply  --run nam_2026-11-05
  python nam_batch_fill.py verify --run nam_2026-11-05
"""
import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mezh_batch_tag import ENV_PATH, EXPORT, SLEEP, col, join_rt, retry, rt  # noqa: E402

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

csv.field_size_limit(10**9)
HERE = Path(__file__).resolve().parent
SERIES_NAM = "40f0ba89-eabe-8169-972c-d64e12e6cfdd"  # Карты и атласы наместничеств
SERIES_GM = "3830ba89-eabe-815f-ae01-c2ded60fa802"
TOKEN = "Серийный массив: карты и атласы наместничеств 1775–1796 (производная ГМ)"

NAM = re.compile(r"(наместничеств|с (генеральных |геометрических )?уездных (межевых )?планов|сочинен\w+ с (генеральн|геометрическ)\w+ (уездн\w+ )?планов|по проложении всех границ)", re.I)
INCL = re.compile(r"(атлас|генеральн\w+ карт|геометрическ\w+ карт|топографическ\w+ (карт|описани)|описани\w+ и алфавит|описани\w+ к атласу|примечания о|примерн\w+ карт|карт\w+ .{0,40}(наместничеств|округ|уезд)|план\w* (границ|город\w*|уездн\w+ город|.{0,12}округ)|планы городов|карты с ведомостями|генеральн\w+ план\w* .{0,30}уезд|почтов\w+ карт)", re.I)
EXCL = re.compile(r"(план\w* дач|геометрич\w* спец|геом\.\s*спец|спец\.\s*план|специальн\w+ план|межев\w+ книг|выкопировк|сенн\w+ покос|покос|пустош|земел\w+ .{0,25}волост|однодворк|оброчн|Российской Атлас|по новейшему разделению|для употребления юношества|Карта Калужской губернии|Карта Смоленской губернии|Карта Пермской губернии|Карта Ярославской губернии|с нанесением границ: уездной)", re.I)
YEAR_FIX = [(re.compile(r"^Топографическое описание Калужского наместничества\. Издано", re.I), 1756, 1782), (re.compile(r"^Топографическое описание Калужскаго наместничества", re.I), 1737, 1785)]  # (название, ошибочный год, верный год)
PRINT_ARCH = ("РГБ", "ПБ", "ГПИБ", "Госкаталог", "НЭБ", "РНБ", "СОУНБ", "Картфонд")
MS_ARCH = ("РГВИА", "РГАДА", "ГАПК", "ГАЯО", "ГАКО", "ГАСО", "РГИА")
FIELDS = ["Картографическая проекция", "Нулевой меридиан", "Система координат", "Оригинальный масштаб", "Масштаб (знаменатель)",
          "Техника исполнения", "Административный уровень", "Язык", "DC Type"]


def fields_for(title, year, arch, cur):
    t = title or ""
    out = {}

    def put(k, v):
        if v is not None and not (cur.get(k) or "").strip():
            out[k] = v
    is_text = bool(re.search(r"(описани|алфавит|примечания о|ведомост)", t, re.I)) and not re.search(r"карт\w+ с ведомост", t, re.I)
    is_city = bool(re.search(r"план\w* .{0,30}город|планы городов|^[А-Я][а-я]+ (Калужского|Смоленского|Ярославского|Пермского) Наместничества$", t, re.I)) or bool(re.search(r"^(Боровск|Белый|Борисоглебск|План (уездного )?города)", t))
    is_uezd = bool(re.search(r"(карт\w+ .{0,10}(№ \d+\. )?карт\w+ .{0,20}уезд|карта .{0,25}уезда|генеральн\w+ план\w* .{0,25}уезда|план\w* .{0,12}округ|карт\w+ .{0,20}округ|план границ)", t, re.I))
    is_gub = bool(re.search(r"(атлас|генеральн\w+ карт\w+ .{0,25}наместничеств|геометрическ\w+ карт\w+ .{0,25}наместничеств|топографическ\w+ карт\w+ .{0,25}наместничеств|карт\w+ .{0,10}наместничеств|карты с ведомостями|примерн\w+ карт)", t, re.I)) and not is_uezd
    kaluga1785 = (bool(re.search(r"Атлас Калужск\w+ наместничества", t, re.I)) and year == 1785) or bool(re.search(r"Топографическое описание Калужского наместничества", t, re.I))
    kaluga1782 = (not kaluga1785) and bool(re.search(r"(Атласа? Калужск\w+ наместничества|Калужского наместничества)", t, re.I)) and (not year or year <= 1783) and "1785" not in t
    # масштаб
    m = re.search(r"м-\s*(\d+)\s*в", t, re.I)
    if m:
        v = int(m.group(1))
        put("Оригинальный масштаб", f"{v} вёрст в дюйме (по надписи)")
        put("Масштаб (знаменатель)", v * 42000)
    elif re.search(r"8 верст", cur.get("Оригинальный масштаб") or "", re.I):
        put("Масштаб (знаменатель)", 336000)
    elif kaluga1785 and is_uezd:
        put("Оригинальный масштаб", "≈5,5 версты в дюйме (1:230 000; АН 1785, Jeske 2023, с. 54)")
        put("Масштаб (знаменатель)", 230000)
    elif kaluga1785:
        put("Оригинальный масштаб", "уездные карты 1:230 000, генеральная 1:630 000 (АН 1785; Jeske 2023, с. 54)")
    elif kaluga1782 and is_uezd:
        put("Оригинальный масштаб", "2 версты в англ. дюйме (атлас 1782; Jeske 2023, с. 52)")
        put("Масштаб (знаменатель)", 84000)
    elif kaluga1782 and is_city:
        put("Оригинальный масштаб", "50 или 100 саж. в дюйме (1:4 200 / 1:8 400; атлас 1782, Jeske 2023, с. 52)")
    elif kaluga1782 and is_gub and re.search(r"(генеральн|геометрическ)", t, re.I):
        put("Оригинальный масштаб", "8 вёрст в англ. дюйме (атлас 1782; Jeske 2023, с. 52)")
        put("Масштаб (знаменатель)", 336000)
    # проекция / меридиан — рукописные и листы атласа 1782
    if not is_text and (arch.startswith(MS_ARCH) or kaluga1782):
        put("Картографическая проекция", "Не применима")
        put("Нулевой меридиан", "Отсутствует")
        put("Система координат", "нет; сводка межевых планов, ориентировка по магнитному меридиану / розе ветров (без градусной сетки)")
    # техника
    if arch.startswith(MS_ARCH):
        put("Техника исполнения", "Рукописная")
    elif arch.startswith(PRINT_ARCH) and not is_text:
        put("Техника исполнения", "Литография" if re.search(r"литограф", t, re.I) else "Гравюра")
    # уровень, тип
    if is_city:
        put("Административный уровень", "Нас. пункт")
    elif is_uezd:
        put("Административный уровень", "Уезд")
    elif is_gub or is_text:
        put("Административный уровень", "Губерния")
    put("DC Type", "Text" if is_text else ("StillImage+Text" if re.search(r"атлас", t, re.I) else "StillImage"))
    put("Язык", "Русский")
    return out


def cmd_plan(args, outdir, logger):
    with EXPORT.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        F = rd.fieldnames
        C = {k: col(F, k) for k in ["Название источника", "Описание", "Примечания", "Год создания (верхняя)", "Архив [авто]", "Фонд", "Опись", "Единица хранения", "Серия / массив", "№ п/п", "url", "page_id", "Статус приёмки", *FIELDS]}
        rows = []
        for r in rd:
            title = r.get(C["Название источника"]) or ""
            desc = r.get(C["Описание"]) or ""
            if not NAM.search(title + " | " + desc):
                continue
            if not INCL.search(title) or EXCL.search(title):
                continue
            if (r.get(C["Статус приёмки"]) or "") in ("отклонено", "отклонён"):
                continue
            arch = (r.get(C["Архив [авто]"]) or "").split("(")[0].strip()
            try:
                y = int(float(r.get(C["Год создания (верхняя)"]) or 0))
            except ValueError:
                y = 0
            num = str(r.get(C["№ п/п"]) or "")
            yfix = next((good for rx, bad, good in YEAR_FIX if rx.search(title) and y == bad), None)
            cur = {k: (r.get(C[k]) or "") for k in FIELDS if C.get(k)}
            fields = fields_for(title, yfix or y, arch, cur)
            ser = r.get(C["Серия / массив"]) or ""
            relink = "Генеральное" in ser and re.search(r"наместничеств", title, re.I) is not None
            rows.append({"page_id": r.get(C["page_id"]), "№": num, "url": r.get(C["url"]), "архив": arch[:30], "фонд": r.get(C["Фонд"]) or "", "опись": (r.get(C["Опись"]) or "")[:12],
                         "дело": (r.get(C["Единица хранения"]) or "")[:16], "год": y or "", "год → исправить": yfix or "", "перепривязать с ГМ": "да" if relink else "",
                         "поля (предлагаемые)": json.dumps(fields, ensure_ascii=False), "серия (сейчас)": ser[:60], "название": title[:200]})
    plan = outdir / "plan.csv"
    with plan.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    fc = Counter(k for r in rows for k in json.loads(r["поля (предлагаемые)"]))
    ac = Counter(r["архив"] for r in rows)
    md = [f"# План серии 4 — run {args.run}", "", f"Записей: {len(rows)}; перепривязать с ГМ: {sum(1 for r in rows if r['перепривязать с ГМ'])}; исправить год: {sum(1 for r in rows if r['год → исправить'])}", "",
          "## По архивам", *[f"- {k}: {v}" for k, v in ac.most_common()], "", "## Поля к заполнению (только пустые)", *[f"- {k}: {v}" for k, v in fc.most_common()], "", f"Файл: {plan}"]
    (outdir / "plan_summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


def load_done(outdir):
    p = outdir / "done.jsonl"
    return {json.loads(line)["page_id"]: json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()} if p.exists() else {}


def cmd_apply(args, outdir, logger):
    load_env(ENV_PATH)
    from notion_client import Client
    client = Client(auth=env("NOTION_TOKEN", required=True))
    plan = list(csv.DictReader((outdir / "plan.csv").open(encoding="utf-8-sig", newline="")))
    done = load_done(outdir)
    todo = [r for r in plan if r["page_id"] not in done]
    logger.info("apply: план %d, сделано %d, осталось %d", len(plan), len(done), len(todo))
    jl = (outdir / "done.jsonl").open("a", encoding="utf-8")
    n = 0
    try:
        for r in todo:
            pid = r["page_id"]
            page = retry(client.pages.retrieve, page_id=pid)
            props = page["properties"]
            new = {}
            note = join_rt(props.get("Примечания", {}))
            note_after = note
            if TOKEN not in note:
                note_after = note.rstrip() + ("; " if note.strip() else "") + TOKEN
            rel = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
            rel_after = [x for x in rel if not (r["перепривязать с ГМ"] and x == SERIES_GM)]
            if SERIES_NAM not in rel_after:
                rel_after.append(SERIES_NAM)
            if rel_after != rel:
                new["Серия / массив"] = {"relation": [{"id": i} for i in rel_after]}
            if r["год → исправить"]:
                yb = props.get("Год создания (верхняя)", {}).get("number")
                new["Год создания (верхняя)"] = {"number": int(r["год → исправить"])}
                note_after += f" (год создания исправлен 05.11.2026: было {yb}, по изданию {r['год → исправить']})"
            if note_after != note:
                new["Примечания"] = {"rich_text": rt(note_after)}
            fields_set = {}
            for k, v in json.loads(r["поля (предлагаемые)"]).items():
                p = props.get(k)
                if p is None:
                    continue
                if p["type"] == "select" and p.get("select") is None:
                    new[k] = {"select": {"name": v}}
                elif p["type"] == "number" and p.get("number") is None:
                    new[k] = {"number": v}
                elif p["type"] == "rich_text" and not join_rt(p).strip():
                    new[k] = {"rich_text": rt(v)}
                else:
                    continue
                fields_set[k] = v
            status = "skip (уже)"
            if new:
                retry(client.pages.update, page_id=pid, properties=new)
                status = "ok"
            jl.write(json.dumps({"page_id": pid, "№": r["№"], "status": status, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "note_before": note, "note_after": note_after, "rel_before": rel, "rel_after": rel_after, "fields_set": fields_set}, ensure_ascii=False) + "\n")
            jl.flush()
            n += 1
            time.sleep(SLEEP)
    except KeyboardInterrupt:
        logger.warning("прервано после %d — повторный запуск продолжит", n)
    finally:
        jl.close()
    logger.info("apply: готово %d; в журнале %d", n, len(load_done(outdir)))


def cmd_verify(args, outdir, logger):
    load_env(ENV_PATH)
    from notion_client import Client
    client = Client(auth=env("NOTION_TOKEN", required=True))
    plan = list(csv.DictReader((outdir / "plan.csv").open(encoding="utf-8-sig", newline="")))
    out = []
    bad = 0
    for r in plan:
        props = retry(client.pages.retrieve, page_id=r["page_id"])["properties"]
        rel = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
        missing = []
        for k in json.loads(r["поля (предлагаемые)"]):
            p = props.get(k, {})
            val = (p.get("select") or {}).get("name") if p.get("type") == "select" else (p.get("number") if p.get("type") == "number" else join_rt(p))
            if val in (None, ""):
                missing.append(k)
        ok = SERIES_NAM in rel and not missing
        bad += not ok
        out.append({"№": r["№"], "ok": "да" if ok else "НЕТ", "связь": "да" if SERIES_NAM in rel else "нет", "поля пустые": "; ".join(missing), "название": r["название"][:120]})
        time.sleep(SLEEP)
    with (outdir / "verify.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"verify: {len(out)} проверено, расхождений {bad}")


def main():
    fix_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["plan", "apply", "verify"])
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    outdir = HERE.parent / "output" / f"nam_fill_{args.run}"
    outdir.mkdir(parents=True, exist_ok=True)
    logger = log("nam_batch_fill")
    {"plan": cmd_plan, "apply": cmd_apply, "verify": cmd_verify}[args.mode](args, outdir, logger)


if __name__ == "__main__":
    main()
