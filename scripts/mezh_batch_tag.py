"""Пакетная пометка вида межевания и привязка к серии «Генеральное и специальное межевание».

Три режима, все возобновляемые (чекпойнт done.jsonl):
  plan   — по полной выгрузке каталога строит план: page_id → предлагаемая пометка
           «Вид межевания: …» + привязать ли к карточке серии. Ничего не пишет в Notion.
           Фильтры: --archive, --fund, --limit, --stratify (равномерно по годам).
  apply  — читает план, для каждой записи: GET страницы → дописывает токен в «Примечания»
           (если ещё нет) и добавляет карточку серии в «Серия / массив» (если ещё нет) → PATCH.
           Журнал «до/после» в done.jsonl; повторный запуск пропускает сделанное.
  verify — повторно читает страницы из плана и проверяет, что токен и связь на месте.

Запуск (из папки scripts):
  python mezh_batch_tag.py plan   --run pilot_gayo455 --archive ГАЯО --fund 455 --limit 200 --stratify
  python mezh_batch_tag.py apply  --run pilot_gayo455
  python mezh_batch_tag.py verify --run pilot_gayo455
Выход: output/mezh_tag_<run>/{plan.csv, plan_summary.md, done.jsonl, verify.csv}.
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

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

csv.field_size_limit(10**9)
HERE = Path(__file__).resolve().parent
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
EXPORT = HERE.parent / "output" / "notion_catalog_20261030_023643.csv"
SERIES_PAGE = "3830ba89-eabe-815f-ae01-c2ded60fa802"  # Генеральное и специальное межевание
TOKEN_PREFIX = "Вид межевания:"
SLEEP = 0.35
RETRIES = 6

SM = re.compile(r"(полюбовн|нарезочн|посредни(к|ческ)|по специальному (раз)?межеван|из дач специального|специальн\w{0,4}\s+(полюбовн\w+\s+)?(раз)?межеван|спец\.\s*межеван|участк\w*,? образовавш|(перв|втор|трет|четверт|пят|шест|седьм|восьм|девят|десят)\w+ (части|половин|мест)|\d+-?[йяеао]{0,2} (части|половин\w*|мест\w*|участк\w*)|части (дач|пустош|сель|дер|села|земл)|половин\w* (дач|пустош|дер|сель|села)|(вырезан|отрезан|вымежеван|отмежеван)\w* из дач|акт\w* о (раз)?межеван|коштн\w+ межеван|через уездн\w+ землемер)", re.I)
ZEMLE = re.compile(r"(отрубн|хутор|надельн\w+ земл|землеустро|укреплен\w+ в личн|выдел\w+ к одному месту|отвод\w* (земл|участк)\w* крестьян|земельн\w+ общест|сельск\w+ обществ\w+ .{0,30}надел)", re.I)
OSOB = re.compile(r"(башкир|въезж\w+ лес|казенн\w+ (пустопорожн\w+ )?лес\w+ дач|лесн\w+ дач|лесничеств|пожалованн\w+ земел)", re.I)
UEZD = re.compile(r"(генеральн\w+ (уездн\w+ )?план|уездн\w+ план-атлас|план-атлас|уездн\w+ генеральн)", re.I)
MGI = re.compile(r"(ведомств\w+ государственных имуществ|казенн\w+ палат|описани\w+ земель и лесов|реестр дачам|хозяйственн\w+ съемк|с показанием .{0,20}дач)", re.I)
EP = re.compile(r"(экономическ\w+ примечани|алфавит\w* (дач|владельц)|перечнев\w+ табел|губернск\w+ табел|экономическ\w+ журнал)", re.I)
GM = re.compile(r"(генеральн\w+ межеван|ген\. межеван|\bПГМ\b|план\w* дач|межев\w+ книг|полев\w+ запис|геометрическ\w+ (специальн\w+ )?план|межевой (конторы|канцеляри|экспедици)|межевая контора|обмежеван|размежеван|межеван)", re.I)
RGADA_MEZH = re.compile(r"^(1354|1355|1356|1294|1308|1313|1322|1327|1328|1337|1339|1349|1353)\b")


def decide(title, desc, note, year, arch, fund):
    """→ (вид, привязать_к_серии, уверенность, основание)"""
    txt = f"{title} | {desc} | {note}"
    y = year or 0
    if SM.search(txt):
        if y and y < 1836:
            return "специальное (коштное / через уездных землемеров, до 1836)", True, "слова+дата", "слова СМ"
        if y and y > 1890:
            return "специальное (через уездных землемеров / губернская чертёжная, после 1881)", True, "слова+дата", "слова СМ"
        return "специальное (полюбовное через посредников, 1836–1881)", True, "слова", "слова СМ"
    if ZEMLE.search(txt) and not UEZD.search(txt):
        return "землеустройство (1861–1917, не межевание)", False, "слова", "слова землеустройства"
    if OSOB.search(txt):
        return "особое (башкирские дачи / казённые лесные дачи / въезжие леса)", True, "слова", "слова особого межевания"
    if UEZD.search(txt) or (arch.startswith("РГАДА") and fund == "1356"):
        return "генеральное (сводный уездный план / план-атлас)", True, "слова", "уездный план"
    if EP.search(txt) or (arch.startswith("РГАДА") and fund == "1355"):
        return "генеральное (экономические примечания / алфавиты / табели)", True, "слова", "ЭП"
    if MGI.search(txt):
        return "генеральное (производная МГИ по казённым дачам, 1840–1860-е)", True, "слова", "МГИ"
    if GM.search(txt) or (arch.startswith("РГАДА") and RGADA_MEZH.match(fund)):
        if arch.startswith("РГАДА") and RGADA_MEZH.match(fund) and not y:
            return "генеральное", True, "фонд", "фонд РГАДА межевой"
        if y and y <= 1800:
            return "генеральное", True, "слова+дата", "ГМ-слова, ≤1800"
        if y and 1836 <= y <= 1890:
            return "специальное (полюбовное через посредников, 1836–1881) — по дате", True, "дата", "ГМ-слова, 1836–1890"
        if y and y > 1890:
            return "ГМ/СМ? (поздняя копия или землеустройство, по дате)", True, "дата?", "ГМ-слова, >1890"
        if y and 1801 <= y <= 1835:
            return "генеральное? (1801–1835: ГМ, коштное или через уездных землемеров)", True, "дата?", "ГМ-слова, 1801–1835"
        return "генеральное? (год не указан)", True, "слова?", "ГМ-слова, без даты"
    return None, False, "", ""


CARTO = re.compile(r"(план|карт[аы]|выкопиров|атлас|чертеж)", re.I)
TEXTDOC = re.compile(r"(межев\w+ книг|сказк|ведомост|описани|акт\w* о|дело|реестр|алфавит|примечани|журнал|приговор|прошени|указ)", re.I)
UEZD_MAP = re.compile(r"(генеральн\w+ (уездн\w+ )?план|уездн\w+ план|план-атлас|карт\w+ .{0,25}уезд)", re.I)
GUB_MAP = re.compile(r"(атлас\w* .{0,30}(губерни|наместничеств)|карт\w+ .{0,25}губерни)", re.I)
ARCH_MS = ("ГАЯО", "РГАДА", "ГАСО", "ГАКО", "ГАПК", "РГИА", "РГВИА")
SERIES_FIELDS = ["Картографическая проекция", "Нулевой меридиан", "Система координат", "Оригинальный масштаб", "Масштаб (знаменатель)",
                 "Техника исполнения", "Административный уровень", "Язык", "DC Type"]


def series_fields(title, kind, arch, current):
    """Предлагаемые значения полей, выводимых из серии и типа документа. Только для пустых полей.
    current — dict поле→текущее значение (из выгрузки)."""
    t = title or ""
    is_carto = bool(CARTO.search(t)) and not (TEXTDOC.search(t) and not CARTO.search(t[:40]))
    is_text = bool(TEXTDOC.search(t)) and not is_carto
    out = {}

    def put(field, value):
        if value is not None and not (current.get(field) or "").strip():
            out[field] = value
    if kind.startswith("землеустройство"):
        return out
    if is_carto:
        put("Картографическая проекция", "Не применима")
        put("Нулевой меридиан", "Отсутствует")
        put("Система координат", "нет; безопорная угломерная съёмка, ориентировка по магнитному меридиану (ГМ: московский на 13.06.1766)")
        put("DC Type", "StillImage")
        if GUB_MAP.search(t):
            put("Административный уровень", "Губерния")
        elif UEZD_MAP.search(t):
            put("Административный уровень", "Уезд")
            if kind.startswith("генеральное (производная МГИ"):
                put("Оригинальный масштаб", "4 версты в англ. дюйме (по типу серии, приближённо)")
                put("Масштаб (знаменатель)", 168000)
            else:
                put("Оригинальный масштаб", "500 саж. в англ. дюйме (по типу серии, приближённо)")
                put("Масштаб (знаменатель)", 42000)
        else:
            put("Административный уровень", "Дача")
            put("Оригинальный масштаб", "100 саж. в англ. дюйме (по типу серии, приближённо)")
            put("Масштаб (знаменатель)", 8400)
    elif is_text:
        put("DC Type", "Text")
        if re.search(r"(межев\w+ книг|сказк)", t, re.I):
            put("Административный уровень", "Дача")
    if arch.startswith(ARCH_MS):
        put("Техника исполнения", "Рукописная")
    put("Язык", "Русский")
    return out


def col(fields, name):
    return next((f for f in fields if f.strip().lower() == name.lower()), None)


def rt(s):
    """rich_text массив с разбиением по 2000 символов."""
    s = s or ""
    return [{"type": "text", "text": {"content": s[i:i + 2000]}} for i in range(0, max(len(s), 1), 2000)] if s else []


def join_rt(prop):
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


NET_ERR = ("getaddrinfo", "ConnectError", "ReadError", "RemoteProtocolError", "ConnectTimeout", "ReadTimeout", "WinError 10054", "Connection reset")


def retry(fn, *a, **kw):
    """Повтор: обычные ошибки — RETRIES попыток с экспоненциальной паузой; сетевые обрывы
    (DNS/VPN/сброс соединения) — ждать до 60 попыток по 60 с (час), не падать."""
    net_attempts = 0
    attempt = 0
    while True:
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if any(k in msg for k in NET_ERR):
                net_attempts += 1
                if net_attempts > 60:
                    raise
                time.sleep(60)
                continue
            attempt += 1
            if attempt >= RETRIES:
                raise
            delay = min(2 ** attempt, 30)
            if "rate" in msg.lower() or "429" in msg:
                delay = max(delay, 5)
            time.sleep(delay)


def cmd_plan(args, outdir, logger):
    with EXPORT.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        F = rd.fieldnames
        C = {k: col(F, k) for k in ["Название источника", "Описание", "Примечания", "Год создания (верхняя)", "Архив [авто]", "Фонд", "Опись", "Серия / массив", "№ п/п", "url", "page_id", "Статус приёмки", *SERIES_FIELDS]}
        field_counts = Counter()
        rows = []
        for r in rd:
            arch = (r.get(C["Архив [авто]"]) or "").split("(")[0].strip()
            fund = (r.get(C["Фонд"]) or "").strip()
            if args.archive and not arch.startswith(args.archive):
                continue
            if args.fund and fund != args.fund:
                continue
            if (r.get(C["Статус приёмки"]) or "") in ("отклонено", "отклонён"):
                continue
            try:
                y = int(float(r.get(C["Год создания (верхняя)"]) or 0))
            except ValueError:
                y = 0
            kind, link, conf, basis = decide(r.get(C["Название источника"]) or "", r.get(C["Описание"]) or "", r.get(C["Примечания"]) or "", y, arch, fund)
            if not kind:
                continue
            note = r.get(C["Примечания"]) or ""
            ser = r.get(C["Серия / массив"]) or ""
            already_tag = TOKEN_PREFIX in note
            already_link = ("Генеральное" in ser and "межевание" in ser) or SERIES_PAGE.replace("-", "") in ser.replace("-", "")
            action = []
            if link and not already_link:
                action.append("привязать")
            if not already_tag:
                action.append("пометить")
            cur = {k: (r.get(C[k]) or "") for k in SERIES_FIELDS if C.get(k)}
            fields = series_fields(r.get(C["Название источника"]) or "", kind, arch, cur)
            for k in fields:
                field_counts[k] += 1
            if fields:
                action.append(f"поля: {len(fields)}")
            if not action:
                action.append("ничего (уже есть)")
            rows.append({"page_id": r.get(C["page_id"]), "№": r.get(C["№ п/п"]), "url": r.get(C["url"]), "архив": arch[:30], "фонд": fund, "опись": (r.get(C["Опись"]) or "")[:16],
                         "год": y or "", "уровень": r.get(C["Административный уровень"]) or "", "вид межевания": kind, "привязать к серии": "да" if link else "нет",
                         "уверенность": conf, "основание": basis, "действие": "; ".join(action), "поля (предлагаемые)": json.dumps(fields, ensure_ascii=False),
                         "примечания (сейчас)": note[:120], "серия (сейчас)": ser[:60], "название": (r.get(C["Название источника"]) or "")[:220]})
    if args.stratify and args.limit and len(rows) > args.limit:
        rows.sort(key=lambda x: (x["год"] or 0))
        step = len(rows) / args.limit
        rows = [rows[int(i * step)] for i in range(args.limit)]
    elif args.limit:
        rows = rows[:args.limit]
    plan = outdir / "plan.csv"
    with plan.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    kinds = Counter(r["вид межевания"] for r in rows)
    acts = Counter(r["действие"] for r in rows)
    decades = Counter(((r["год"] // 10 * 10) if r["год"] else "—") for r in rows)
    md = [f"# План пометки — run {args.run}", "", f"Записей в плане: {len(rows)} (фильтр: архив={args.archive or '*'}, фонд={args.fund or '*'}, limit={args.limit}, stratify={args.stratify})", "",
          "## Вид межевания", *[f"- {k}: {v}" for k, v in kinds.most_common()], "", "## Действия", *[f"- {k}: {v}" for k, v in acts.most_common()], "",
          "## Десятилетия", *[f"- {k}: {v}" for k, v in sorted(decades.items(), key=lambda x: str(x[0]))], "",
          "## Поля серии к заполнению (только пустые)", *[f"- {k}: {v}" for k, v in field_counts.most_common()], "", f"Файл: {plan}"]
    (outdir / "plan_summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    logger.info("plan: %d rows -> %s", len(rows), plan)


def load_done(outdir):
    p = outdir / "done.jsonl"
    done = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done[d["page_id"]] = d
    return done


def cmd_apply(args, outdir, logger):
    load_env(ENV_PATH)
    from notion_client import Client
    client = Client(auth=env("NOTION_TOKEN", required=True))
    plan = list(csv.DictReader((outdir / "plan.csv").open(encoding="utf-8-sig", newline="")))
    done = load_done(outdir)
    todo = [r for r in plan if r["page_id"] not in done and r["действие"] != "ничего (уже есть)"]
    logger.info("apply: план %d, сделано %d, осталось %d", len(plan), len(done), len(todo))
    jl = (outdir / "done.jsonl").open("a", encoding="utf-8")
    n = 0
    try:
        for r in todo:
            pid = r["page_id"]
            page = retry(client.pages.retrieve, page_id=pid)
            props = page["properties"]
            note_before = join_rt(props.get("Примечания", {}))
            rel_before = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
            new_props = {}
            token = f"{TOKEN_PREFIX} {r['вид межевания']}"
            note_after = note_before
            if TOKEN_PREFIX not in note_before:
                note_after = (note_before.rstrip() + ("; " if note_before.strip() else "") + token)
                new_props["Примечания"] = {"rich_text": rt(note_after)}
            rel_after = rel_before
            if r["привязать к серии"] == "да" and SERIES_PAGE not in rel_before:
                rel_after = rel_before + [SERIES_PAGE]
                new_props["Серия / массив"] = {"relation": [{"id": i} for i in rel_after]}
            fields_set = {}
            for k, v in json.loads(r.get("поля (предлагаемые)") or "{}").items():
                p = props.get(k)
                if p is None:
                    continue
                if p["type"] == "select" and p.get("select") is None:
                    new_props[k] = {"select": {"name": v}}
                elif p["type"] == "number" and p.get("number") is None:
                    new_props[k] = {"number": v}
                elif p["type"] == "rich_text" and not join_rt(p).strip():
                    new_props[k] = {"rich_text": rt(v)}
                else:
                    continue
                fields_set[k] = v
            status = "skip (уже)"
            if new_props:
                retry(client.pages.update, page_id=pid, properties=new_props)
                status = "ok"
            rec = {"page_id": pid, "№": r["№"], "status": status, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "note_before": note_before, "note_after": note_after, "rel_before": rel_before, "rel_after": rel_after, "kind": r["вид межевания"],
                   "fields_set": fields_set}
            jl.write(json.dumps(rec, ensure_ascii=False) + "\n")
            jl.flush()
            n += 1
            if n % 25 == 0:
                logger.info("apply: %d/%d", n, len(todo))
            time.sleep(SLEEP)
    except KeyboardInterrupt:
        logger.warning("прервано пользователем после %d записей — журнал сохранён, повторный запуск продолжит", n)
    finally:
        jl.close()
    logger.info("apply: готово %d за этот запуск; всего в журнале %d", n, len(load_done(outdir)))


def cmd_verify(args, outdir, logger):
    load_env(ENV_PATH)
    from notion_client import Client
    client = Client(auth=env("NOTION_TOKEN", required=True))
    plan = list(csv.DictReader((outdir / "plan.csv").open(encoding="utf-8-sig", newline="")))
    out = []
    bad = 0
    for r in plan:
        page = retry(client.pages.retrieve, page_id=r["page_id"])
        props = page["properties"]
        note = join_rt(props.get("Примечания", {}))
        rel = [x["id"] for x in props.get("Серия / массив", {}).get("relation", [])]
        ok_tag = TOKEN_PREFIX in note
        ok_rel = (SERIES_PAGE in rel) if r["привязать к серии"] == "да" else True
        want = json.loads(r.get("поля (предлагаемые)") or "{}")
        missing = []
        for k in want:
            p = props.get(k, {})
            val = p.get("select", {}) and p["select"].get("name") if p.get("type") == "select" else (p.get("number") if p.get("type") == "number" else join_rt(p))
            if val in (None, ""):
                missing.append(k)
        ok = ok_tag and ok_rel and not missing
        bad += not ok
        out.append({"page_id": r["page_id"], "№": r["№"], "ok": "да" if ok else "НЕТ", "токен": "да" if ok_tag else "нет", "связь": "да" if ok_rel else "нет",
                    "поля пустые": "; ".join(missing), "примечания": note[-160:], "название": r["название"][:120]})
        time.sleep(SLEEP)
    with (outdir / "verify.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print(f"verify: {len(out)} проверено, расхождений {bad}; файл {outdir / 'verify.csv'}")
    logger.info("verify: %d checked, %d bad", len(out), bad)


def main():
    fix_stdout()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["plan", "apply", "verify"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--archive", default="")
    ap.add_argument("--fund", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stratify", action="store_true")
    args = ap.parse_args()
    outdir = HERE.parent / "output" / f"mezh_tag_{args.run}"
    outdir.mkdir(parents=True, exist_ok=True)
    logger = log("mezh_batch_tag")
    {"plan": cmd_plan, "apply": cmd_apply, "verify": cmd_verify}[args.mode](args, outdir, logger)


if __name__ == "__main__":
    main()
