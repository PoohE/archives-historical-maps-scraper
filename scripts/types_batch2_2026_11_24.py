"""Тип источника для принятых записей без типа (пачка 2 сессии анализа, 24.11.2026).

Решение владельца 24.11: разметить классификатором 11.11 (`classify_for_upload.SYSTEM2`,
25 типов A1–C8), Sonnet пакетом. В каталог идут только уверенные ответы (`sure`), с отметкой
«тип размечен моделью» в «Примечаниях»; неуверенные и «нет» остаются пустыми и идут владельцу.

  python scripts/types_batch2_2026_11_24.py gold <слепок.csv>      # проверка на 50 записях с известным типом
  python scripts/types_batch2_2026_11_24.py submit <пачка2.csv> <слепок.csv>
  python scripts/types_batch2_2026_11_24.py collect
  python scripts/types_batch2_2026_11_24.py build                   # → output/fixes/batch2_types_*.csv
"""
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_for_upload import SYSTEM2, answer_text, strip_fence  # noqa: E402
from common import anthropic_client, fix_stdout, load_env  # noqa: E402

MODEL = "claude-sonnet-5-5"
PER_REQ = 25
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "types_batch2_2026-11-24"
CODES = {"A1", "A2", "A3", "A4", "A5", "A6", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9",
         "B10", "B11", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"}


def item(r: dict) -> dict:
    ctx = " ".join(x for x in (r.get("Архив [авто]", ""), r.get("Шифр архива", ""),
                               (r.get("Описание", "") or "")[:200]) if x)
    return {"page_id": r["page_id"], "title": r["Название источника"], "ctx": ctx}


def body(chunk: list[dict], k0: int) -> str:
    return "\n".join(f'{k0 + j}. ЗАГОЛОВОК: {r["title"]}' + (f'\n   ФОНД/СЕРИЯ: {r["ctx"][:200]}' if r["ctx"] else "")
                     for j, r in enumerate(chunk))


def snapshot(p: str) -> dict:
    csv.field_size_limit(10**9)
    return {r["page_id"]: r for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


def gold(snap_path: str) -> None:
    snap = snapshot(snap_path)
    pool = [r for r in snap.values() if r["Статус приёмки"] == "принято" and r["Тип источника"] in CODES]
    random.seed(20261124)
    by = {}
    for r in pool:
        by.setdefault(r["Архив [авто]"], []).append(r)
    # слои как в пачке 2: держатели с наибольшим числом записей без типа
    take = {"ГАЯО": 15, "РГБ": 8, "ПБ": 7, "НЭБ": 6, "ПГКБ": 5, "ГПИБ": 3, "ГАКО": 3, "РГИА": 3}
    rows = [x for h, n in take.items() for x in random.sample(by.get(h, []), min(n, len(by.get(h, []))))]
    items = [item(r) for r in rows]
    load_env()
    client = anthropic_client()
    got = {}
    for k in range(0, len(items), PER_REQ):
        msg = client.messages.create(model=MODEL, max_tokens=8000, system=SYSTEM2,
                                     messages=[{"role": "user", "content": body(items[k:k + PER_REQ], k)}])
        for a in json.loads(strip_fence(answer_text(msg))):
            got[int(a["i"])] = a
    ok = sure_n = sure_ok = 0
    for i, r in enumerate(rows):
        a = got.get(i, {})
        hit = a.get("code") == r["Тип источника"]
        ok += hit
        if a.get("sure"):
            sure_n += 1
            sure_ok += hit
        if not hit:
            print(f"  {r['Архив [авто]']:6s} было {r['Тип источника']:4s} модель {a.get('code')!s:4s} "
                  f"{'увер.' if a.get('sure') else 'неув.'} | {r['Название источника'][:80]}")
    print(f"совпало {ok}/{len(rows)}; среди уверенных {sure_ok}/{sure_n}")
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "gold.json").write_text(json.dumps({"ok": ok, "n": len(rows), "sure_ok": sure_ok, "sure_n": sure_n},
                                               ensure_ascii=False), encoding="utf-8")


def submit(batch_csv: str, snap_path: str) -> None:
    snap = snapshot(snap_path)
    ids = [r["page_id"] for r in csv.DictReader(open(batch_csv, encoding="utf-8-sig"))]
    items = [item(snap[i]) for i in ids if i in snap and not snap[i]["Тип источника"]]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "input.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
    reqs = [{"custom_id": f"t{k}", "params": {"model": MODEL, "max_tokens": 8000, "system": SYSTEM2,
             "messages": [{"role": "user", "content": body(items[k:k + PER_REQ], k)}]}}
            for k in range(0, len(items), PER_REQ)]
    load_env()
    client = anthropic_client()
    b = client.messages.batches.create(requests=reqs)
    (WORK / "batch.json").write_text(json.dumps({"id": b.id, "n": len(reqs)}), encoding="utf-8")
    print(f"записей {len(items)} (из {len(ids)} в пачке), запросов {len(reqs)}, пакет {b.id}")


def collect() -> None:
    load_env()
    client = anthropic_client()
    b = json.loads((WORK / "batch.json").read_text(encoding="utf-8"))
    info = client.messages.batches.retrieve(b["id"])
    print(f"статус: {info.processing_status} {info.request_counts}")
    if info.processing_status != "ended":
        return
    items = [json.loads(x) for x in (WORK / "input.jsonl").open(encoding="utf-8")]
    out, bad = [], 0
    for res in client.messages.batches.results(b["id"]):
        if res.result.type != "succeeded":
            bad += 1
            continue
        try:
            answers = json.loads(strip_fence(answer_text(res.result.message)))
        except json.JSONDecodeError:
            # битый ответ на одну пачку — её записи уходят в остаток, а не роняют сборку
            bad += 1
            k0 = int(res.custom_id[1:])
            out += [{**x, "code": None, "sure": False, "why": "битый ответ модели"}
                    for x in items[k0:k0 + PER_REQ]]
            continue
        for a in answers:
            i = int(a["i"])
            out.append({**items[i], "code": a.get("code"), "sure": bool(a.get("sure")), "why": a.get("why", "")})
    with (WORK / "typed.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in out)
    print(f"ответов {len(out)} из {len(items)}; неудачных запросов {bad}")
    print(Counter((x["code"], x["sure"]) for x in out).most_common(30))


def build() -> None:
    rows = [json.loads(x) for x in (WORK / "typed.jsonl").open(encoding="utf-8")]
    note = "Тип размечен моделью 24.11.2026 по заголовку (пачка 2 сессии анализа; классификатор 11.11, {m}): {c} — {w}"
    fix = [{"page_id": r["page_id"], "set": json.dumps({"Тип источника": r["code"]}, ensure_ascii=False),
            "note": note.format(m=MODEL, c=r["code"], w=r["why"])}
           for r in rows if r["sure"] and r["code"] in CODES]
    rest = [r for r in rows if not (r["sure"] and r["code"] in CODES)]
    p = ROOT / "output" / "fixes" / (sys.argv[2] if len(sys.argv) > 2 else "batch2_types_2026-11-24.csv")
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "set", "note"], lineterminator="\n")
        w.writeheader()
        w.writerows(fix)
    with (WORK / "vladeltsu.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "title", "ctx", "code", "sure", "why"])
        w.writeheader()
        w.writerows(rest)
    print(f"в каталог: {len(fix)} → {p}; владельцу: {len(rest)}")


OPUS = "claude-opus-5-5"


def opus_submit() -> None:
    """Второе мнение (решение владельца 24.11): неуверенные ответы Sonnet независимо размечает Opus."""
    rows = [json.loads(x) for x in (WORK / "typed.jsonl").open(encoding="utf-8")]
    items = [r for r in rows if r["code"] in CODES and not r["sure"]]
    (WORK / "opus_input.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items),
                                           encoding="utf-8")
    reqs = [{"custom_id": f"o{k}", "params": {"model": OPUS, "max_tokens": 4000, "system": SYSTEM2,
             "messages": [{"role": "user", "content": body(items[k:k + 10], k)}]}}
            for k in range(0, len(items), 10)]
    load_env()
    b = anthropic_client().messages.batches.create(requests=reqs)
    (WORK / "opus_batch.json").write_text(json.dumps({"id": b.id, "n": len(reqs)}), encoding="utf-8")
    print(f"записей {len(items)}, запросов {len(reqs)}, пакет {b.id}")


def opus_collect() -> None:
    load_env()
    client = anthropic_client()
    b = json.loads((WORK / "opus_batch.json").read_text(encoding="utf-8"))
    info = client.messages.batches.retrieve(b["id"])
    print(f"статус: {info.processing_status} {info.request_counts}")
    if info.processing_status != "ended":
        return
    items = [json.loads(x) for x in (WORK / "opus_input.jsonl").open(encoding="utf-8")]
    agree, differ, bad = [], [], 0
    for res in client.messages.batches.results(b["id"]):
        try:
            answers = json.loads(strip_fence(answer_text(res.result.message)))
        except (json.JSONDecodeError, AttributeError):
            bad += 1
            continue
        for a in answers:
            r = items[int(a["i"])]
            (agree if a.get("code") == r["code"] else differ).append({**r, "opus": a.get("code"),
                                                                       "opus_why": a.get("why", "")})
    note = ("Тип размечен моделью 24.11.2026 по заголовку (пачка 2 сессии анализа): {c} — Sonnet "
            "предположительно, Opus независимо дал тот же тип ({w})")
    with (ROOT / "output" / "fixes" / "batch2_types_opus_2026-11-24.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "set", "note"], lineterminator="\n")
        w.writeheader()
        w.writerows({"page_id": r["page_id"], "set": json.dumps({"Тип источника": r["code"]}, ensure_ascii=False),
                     "note": note.format(c=r["code"], w=r["opus_why"])} for r in agree)
    with (WORK / "opus_differ.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(differ[0]) if differ else ["page_id"])
        w.writeheader()
        w.writerows(differ)
    print(f"совпало {len(agree)}, разошлось {len(differ)}, битых ответов {bad}")
    print(Counter((r["code"], r["opus"]) for r in differ).most_common(12))


def retry() -> None:
    """Повтор пачек с битым ответом — синхронно, мелкими порциями по 10 записей."""
    rows = [json.loads(x) for x in (WORK / "typed.jsonl").open(encoding="utf-8")]
    todo = [r for r in rows if r["why"] == "битый ответ модели"]
    load_env()
    client = anthropic_client()
    got = {}
    for k in range(0, len(todo), 10):
        chunk = todo[k:k + 10]
        msg = client.messages.create(model=MODEL, max_tokens=4000, system=SYSTEM2,
                                     messages=[{"role": "user", "content": body(chunk, 0)}])
        for a in json.loads(strip_fence(answer_text(msg))):
            got[chunk[int(a["i"])]["page_id"]] = a
    for r in rows:
        a = got.get(r["page_id"])
        if a:
            r.update(code=a.get("code"), sure=bool(a.get("sure")), why=a.get("why", ""))
    with (WORK / "typed.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
    print(f"повтор: {len(got)} из {len(todo)}; {Counter((a.get('code'), bool(a.get('sure'))) for a in got.values()).most_common(12)}")


if __name__ == "__main__":
    fix_stdout()
    cmd = sys.argv[1]
    {"gold": lambda: gold(sys.argv[2]), "submit": lambda: submit(sys.argv[2], sys.argv[3]),
     "collect": collect, "build": build, "retry": retry, "opus_submit": opus_submit, "opus_collect": opus_collect}[cmd]()
