"""Серия «Российский атлас А. М. Вильбрехта (1792–1800)»: привязка записей каталога к карточке серии,
заполнение пустых полей и ЗАМЕНА шаблонного масштаба «по типу издания (~1:2 520 000)» на оценку
по размеру листа и протяжённости губернии (канон §2.3, путь А). Режимы plan / apply / verify, чекпойнт.

  python vil_batch_fill.py plan   --run vil_2026-11-05
  python vil_batch_fill.py apply  --run vil_2026-11-05
  python vil_batch_fill.py verify --run vil_2026-11-05
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
SERIES = "40f0ba89-eabe-8122-8a8e-d670c9b0c8f4"  # Российский атлас Вильбрехта
TOKEN = "Серийный массив: Российский атлас Вильбрехта 1792–1800 (производная карт наместничеств и ГМ)"
SEL = re.compile(r"(Вильбрехт|Вильдбрехт|Российск\w+ атлас\w* из сорока|из «Российского атласа|сочиненн\w+ для [Аа]тласа 1800)", re.I)
# заменяемые строки масштаба: шаблон «по типу издания» (прогон 1) и наша же оценка «по размеру листа» (прогон 2 → измеренные)
TEMPLATE_SCALE = re.compile(r"по типу издания|по размеру листа", re.I)
# измерено 05.11.2026 по сканам Rumsey 1800 (IIIF): градусная рамка широты + линейка, ≈600 dpi, ±4 % (РАЗБОР 5.8-тер)
MEAS = "измерено по градусной рамке и линейке листа 1800 г., скан Rumsey IIIF ≈600 dpi, ±4 %; 05.11.2026"
GUB_SCALE = {
    "Калужск": (f"≈11 вёрст в дюйме ({MEAS}; на листе линейка 5–35 вёрст)", 465000),
    "Ярославск": (f"≈14 вёрст в дюйме ({MEAS})", 575000),
    "Смоленск": (f"≈18 вёрст в дюйме ({MEAS})", 770000),
    "Пермск": (f"≈40 вёрст в дюйме ({MEAS}; подписи рамки через 2°)", 1700000),
}
ATLAS_SCALE = "масштабы разные по листам: губернские листы наших губерний 11–40 вёрст в дюйме (измерено по Rumsey 1800), генеральная карта ≈175 в/дюйм (1:7,4 млн, РНБ)"
MERIDIAN = "Ферро"
FIELDS = ["Оригинальный масштаб", "Масштаб (знаменатель)", "Техника исполнения", "Административный уровень", "Язык", "DC Type", "Нулевой меридиан"]


def decide(title, cur):
    t = title or ""
    is_text = bool(re.search(r"описани", t, re.I))
    is_atlas = bool(re.search(r"^Российск\w+ атлас", t, re.I))
    fill, overwrite = {}, {}

    def put(k, v):
        if v is not None and not (cur.get(k) or "").strip():
            fill[k] = v
    put("Техника исполнения", "Печатная" if is_text else "Гравюра")
    put("Административный уровень", "Губерния")
    put("Язык", "Русский")
    put("DC Type", "Text" if is_text else ("StillImage+Text" if is_atlas else "StillImage"))
    if not is_text:
        put("Нулевой меридиан", MERIDIAN)  # по рамкам четырёх листов 1800 г. (Rumsey); только в пустое поле
        gub = next((k for k in GUB_SCALE if re.search(k, t, re.I)), None)
        if gub and not is_atlas:
            txt, den = GUB_SCALE[gub]
            if TEMPLATE_SCALE.search(cur.get("Оригинальный масштаб") or ""):
                overwrite["Оригинальный масштаб"] = txt
                overwrite["Масштаб (знаменатель)"] = den
            else:
                put("Оригинальный масштаб", txt)
                put("Масштаб (знаменатель)", den)
        elif is_atlas:
            txt = ATLAS_SCALE
            if TEMPLATE_SCALE.search(cur.get("Оригинальный масштаб") or ""):
                overwrite["Оригинальный масштаб"] = txt
                overwrite["Масштаб (знаменатель)"] = None
            else:
                put("Оригинальный масштаб", txt)
    return fill, overwrite


def cmd_plan(args, outdir, logger):
    with EXPORT.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        F = rd.fieldnames
        C = {k: col(F, k) for k in ["Название источника", "Описание", "Автор / составитель", "Год создания (верхняя)", "Архив [авто]", "Серия / массив", "url", "page_id", "Статус приёмки", *FIELDS]}
        rows = []
        for r in rd:
            title = r.get(C["Название источника"]) or ""
            blob = " | ".join(str(r.get(C[k]) or "") for k in ("Название источника", "Описание", "Автор / составитель"))
            if not SEL.search(blob) or (r.get(C["Статус приёмки"]) or "") in ("отклонено", "отклонён"):
                continue
            if re.search(r"для употребления юношества|по новейшему разделению|Атлас Российской Империи Ѣ", title):
                continue
            cur = {k: (r.get(C[k]) or "") for k in FIELDS if C.get(k)}
            fill, overwrite = decide(title, cur)
            rows.append({"page_id": r.get(C["page_id"]), "url": r.get(C["url"]), "архив": (r.get(C["Архив [авто]"]) or "").split("(")[0].strip()[:30],
                         "год": r.get(C["Год создания (верхняя)"]) or "", "масштаб (сейчас)": (cur.get("Оригинальный масштаб") or "")[:60],
                         "заполнить": json.dumps(fill, ensure_ascii=False), "заменить": json.dumps(overwrite, ensure_ascii=False),
                         "серия (сейчас)": (r.get(C["Серия / массив"]) or "")[:50], "название": title[:200]})
    plan = outdir / "plan.csv"
    with plan.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    md = [f"# План серии 5 — run {args.run}", "", f"Записей: {len(rows)}", "## По архивам", *[f"- {k}: {v}" for k, v in Counter(r["архив"] for r in rows).most_common()],
          "## Заполнить (пустые)", *[f"- {k}: {v}" for k, v in Counter(k for r in rows for k in json.loads(r["заполнить"])).most_common()],
          "## Заменить (шаблонный масштаб)", *[f"- {k}: {v}" for k, v in Counter(k for r in rows for k in json.loads(r["заменить"])).most_common()], "", f"Файл: {plan}"]
    (outdir / "plan_summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


def load_done(outdir):
    p = outdir / "done.jsonl"
    return {json.loads(line)["page_id"]: 1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip()} if p.exists() else {}


def set_prop(props, k, v):
    p = props.get(k)
    if p is None:
        return None
    if p["type"] == "select":
        return {"select": {"name": v}} if v is not None else {"select": None}
    if p["type"] == "number":
        return {"number": v}
    if p["type"] == "rich_text":
        return {"rich_text": rt(v or "")}
    return None


def is_empty(p):
    if p["type"] == "select":
        return p.get("select") is None
    if p["type"] == "number":
        return p.get("number") is None
    if p["type"] == "rich_text":
        return not join_rt(p).strip()
    return False


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
            props = retry(client.pages.retrieve, page_id=pid)["properties"]
            new, changed = {}, {}
            note = join_rt(props.get("Примечания", {}))
            note_after = note
            if TOKEN not in note:
                note_after = note.rstrip() + ("; " if note.strip() else "") + TOKEN
            rel = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
            if SERIES not in rel:
                new["Серия / массив"] = {"relation": [{"id": i} for i in rel + [SERIES]]}
            for k, v in json.loads(r["заполнить"]).items():
                if k in props and is_empty(props[k]):
                    sp = set_prop(props, k, v)
                    if sp:
                        new[k] = sp
                        changed[k] = v
            ow = json.loads(r["заменить"])
            if not ow:  # план строился по старой выгрузке: поле уже заполнено оценкой 1-го прогона → заменить измеренным
                fl = json.loads(r["заполнить"])
                ow = {k: fl[k] for k in ("Оригинальный масштаб", "Масштаб (знаменатель)") if k in fl}
            if ow:
                live = join_rt(props.get("Оригинальный масштаб", {}))
                if TEMPLATE_SCALE.search(live):
                    for k, v in ow.items():
                        sp = set_prop(props, k, v)
                        if sp:
                            new[k] = sp
                            changed[k] = v
                    how = "измерено по Rumsey IIIF" if "по размеру листа" in live else "оценка по размеру листа"
                    note_after += f" (масштаб заменён 05.11.2026: было «{live[:70]}» → {how})"
            if note_after != note:
                new["Примечания"] = {"rich_text": rt(note_after)}
            status = "skip"
            if new:
                retry(client.pages.update, page_id=pid, properties=new)
                status = "ok"
            jl.write(json.dumps({"page_id": pid, "status": status, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note_before": note, "note_after": note_after, "changed": changed}, ensure_ascii=False) + "\n")
            jl.flush()
            n += 1
            time.sleep(SLEEP)
    except KeyboardInterrupt:
        logger.warning("прервано после %d", n)
    finally:
        jl.close()
    logger.info("apply: готово %d", n)


def cmd_verify(args, outdir, logger):
    load_env(ENV_PATH)
    from notion_client import Client
    client = Client(auth=env("NOTION_TOKEN", required=True))
    plan = list(csv.DictReader((outdir / "plan.csv").open(encoding="utf-8-sig", newline="")))
    bad = 0
    for r in plan:
        props = retry(client.pages.retrieve, page_id=r["page_id"])["properties"]
        rel = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
        want = {**json.loads(r["заполнить"]), **json.loads(r["заменить"])}
        missing = [k for k in want if k in props and is_empty(props[k]) and want[k] is not None]
        tmpl = TEMPLATE_SCALE.search(join_rt(props.get("Оригинальный масштаб", {}))) is not None
        ok = SERIES in rel and not missing and not (json.loads(r["заменить"]) and tmpl)
        bad += not ok
        if not ok:
            print("НЕТ:", r["название"][:80], "| связь", SERIES in rel, "| пусто", missing, "| шаблон", tmpl)
        time.sleep(SLEEP)
    print(f"verify: {len(plan)} проверено, расхождений {bad}")


def main():
    fix_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["plan", "apply", "verify"])
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    outdir = HERE.parent / "output" / f"vil_fill_{args.run}"
    outdir.mkdir(parents=True, exist_ok=True)
    {"plan": cmd_plan, "apply": cmd_apply, "verify": cmd_verify}[args.mode](args, outdir, log("vil_batch_fill"))


if __name__ == "__main__":
    main()
