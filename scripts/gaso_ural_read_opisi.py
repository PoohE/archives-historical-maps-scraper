"""Распознавание сканов описей ГАСО-Урал пакетным Vision (Batch API, −50 %).

Портал ГАСО-Урал публикует описи СКАНАМИ, а не записями дел. Проверка 09.11.2026
на ф. 773 оп. 1 показала, что страницы описи — машинопись с таблицей из семи граф:
  1 № дела · 2 старый номер · 3 ЗАГОЛОВОК ДЕЛА · 4 крайние даты ·
  5 МАСШТАБ («100 саж. а. д. 1:8400») · 6 листов и РАЗМЕР в см · 7 примечание.
То есть опись даёт то, чего нам не хватает в каталоге: **масштаб прямо с описи**
и размер листа. Часть страниц — предметный и именной указатели, их надо отличать.

⚠️ Две особенности сканов, учтённые в промпте:
  * сильный «прозрачник» — просвечивает оборот листа; читать только основной слой;
  * числа в графе 6 на части строк вписаны ОТ РУКИ (129, 48, 20, 64) — модель должна
    помечать такие значения как рукописные, а не молча смешивать с машинописью.

Модель: Sonnet 5 и выше (память `feedback_haiku-hallucinates-on-handwriting`).

  python gaso_ural_read_opisi.py submit [--funds 773,64] [--limit N]
  python gaso_ural_read_opisi.py collect
"""

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import anthropic_client, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output" / "gaso_ural"
SCANS = ROOT / "scans"
BATCH = ROOT / "batches.json"
OUT = ROOT / "opisi_rows.jsonl"
MODEL = "claude-sonnet-5"

SYSTEM = """Ты читаешь СКАН СТРАНИЦЫ АРХИВНОЙ ОПИСИ Государственного архива
Свердловской области. Это машинопись середины XX века.

Отвечай ТОЛЬКО одним объектом JSON, без пояснений и без markdown-обёртки.

Схема:
{
 "page_kind": "опись" | "предметный указатель" | "именной указатель" | "титул" |
              "предисловие" | "иное",
 "page_no": "номер страницы, как напечатан, либо null",
 "rows": [
   {"delo": "№ дела (графа 1)",
    "old_no": "старый номер (графа 2) или null",
    "title": "заголовок дела (графа 3) ДОСЛОВНО, с сохранением орфографии",
    "dates": "крайние даты (графа 4) как напечатано",
    "scale": "масштаб (графа 5) как напечатано, напр. «100 саж. а. д. 1:8400»",
    "sheets": "число листов и размер (графа 6) как напечатано",
    "note": "примечание (графа 7) или null",
    "handwritten": ["имена граф, значение которых вписано ОТ РУКИ"]}
 ],
 "unreadable": ["что не удалось прочитать"]
}

ЖЁСТКИЕ ПРАВИЛА.
1. НИЧЕГО НЕ ДОДУМЫВАЙ. Не можешь прочесть — ставь null и пиши об этом в "unreadable".
2. На скане ПРОСВЕЧИВАЕТ ОБОРОТ листа. Читай только основной, чёткий слой;
   бледный зеркальный текст игнорируй полностью.
3. Часть чисел ВПИСАНА ОТ РУКИ. Такие значения записывай как есть и перечисляй
   имя графы в "handwritten".
4. Если страница — указатель, предисловие или титул, верни "rows": [] и правильный
   "page_kind". Не превращай строки указателя в дела.
5. Заголовок дела переноси ПОЛНОСТЬЮ, склеивая перенесённые строки, но не правя
   орфографию и не раскрывая сокращения."""


def pages(funds: list[str] | None) -> list[Path]:
    out: list[Path] = []
    for d in sorted(SCANS.glob("*_*")):
        if funds and d.name.split("_", 1)[0] not in funds:
            continue
        out.extend(sorted(d.glob("*.jpg")))
    return out


def cmd_submit(args: argparse.Namespace) -> None:
    funds = [x.strip() for x in args.funds.split(",") if x.strip()] or None
    todo = pages(funds)
    done: set[str] = set()
    if OUT.exists():
        for ln in OUT.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["cid"])
            except (json.JSONDecodeError, KeyError):
                continue
    todo = [p for p in todo if f"{p.parent.name}/{p.stem}" not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("нечего отправлять")
        return

    reqs = []
    for p in todo:
        cid = f"{p.parent.name}/{p.stem}"
        img = base64.b64encode(p.read_bytes()).decode()
        reqs.append({
            "custom_id": cid.replace("/", "__"),
            "params": {
                "model": MODEL,
                "max_tokens": 16000,
                "system": SYSTEM,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg", "data": img}},
                        {"type": "text", "text": (
                            f"Скан описи: фонд и опись — {p.parent.name.replace('_', ', оп. ')}, "
                            f"файл {p.name}. Верни JSON по схеме.")},
                    ],
                }],
            },
        })
    client = anthropic_client()
    batches = []
    for i in range(0, len(reqs), 100):
        b = client.messages.batches.create(requests=reqs[i:i + 100])
        batches.append({"id": b.id, "n": len(reqs[i:i + 100])})
        print(f"  пакет {b.id}: {len(reqs[i:i + 100])} страниц", flush=True)
    old = json.loads(BATCH.read_text(encoding="utf-8")) if BATCH.exists() else []
    BATCH.write_text(json.dumps(old + batches, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"отправлено страниц: {len(reqs)} в {len(batches)} пакетах → {BATCH}")


def cmd_collect(_: argparse.Namespace) -> None:
    if not BATCH.exists():
        sys.exit("нет отправленных пакетов")
    client = anthropic_client()
    batches = json.loads(BATCH.read_text(encoding="utf-8"))
    # дедуп: повторный collect по тому же пакету иначе дублирует страницы в файле
    have: set[str] = set()
    if OUT.exists():
        for ln in OUT.open(encoding="utf-8"):
            try:
                have.add(json.loads(ln)["cid"])
            except (json.JSONDecodeError, KeyError):
                continue
    rows = 0
    pages_ok = 0
    with OUT.open("a", encoding="utf-8") as f:
        for b in batches:
            info = client.messages.batches.retrieve(b["id"])
            st = info.processing_status
            print(f"  {b['id']}: {st}", flush=True)
            if st != "ended":
                continue
            for res in client.messages.batches.results(b["id"]):
                cid = res.custom_id.replace("__", "/")
                if cid in have:
                    continue
                have.add(cid)
                if res.result.type != "succeeded":
                    f.write(json.dumps({"cid": cid, "error": res.result.type},
                                       ensure_ascii=False) + chr(10))
                    continue
                txt = "".join(
                    c.text for c in res.result.message.content if c.type == "text"
                ).strip()
                txt = txt.removeprefix("```json").removeprefix("```").removesuffix("```")
                try:
                    data = json.loads(txt)
                except json.JSONDecodeError:
                    f.write(json.dumps({"cid": cid, "error": "не JSON",
                                        "raw": txt[:400]}, ensure_ascii=False) + chr(10))
                    continue
                data["cid"] = cid
                f.write(json.dumps(data, ensure_ascii=False) + chr(10))
                pages_ok += 1
                rows += len(data.get("rows") or [])
    print(f"страниц разобрано: {pages_ok}; строк описи получено: {rows}")
    print(f"→ {OUT}")


def main() -> None:
    fix_stdout()
    # без аргумента: берутся ~/.secrets/claude.env и .env проекта,
    # где и лежит ANTHROPIC_API_KEY (ENV_PATH из mezh_batch_tag — только Notion)
    load_env()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--funds", default="")
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(func=cmd_submit)
    c = sub.add_parser("collect")
    c.set_defaults(func=cmd_collect)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
