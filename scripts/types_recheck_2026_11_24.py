"""Перепроверка типов с высокой долей ошибок (решение владельца 24.11.2026, «оба шага»).

Основание — выборочная проверка `types_audit_2026_11_24.py`: в типах A2, A1, A6, C2, C5, B2,
A5, B10, B6 неверный тип у 15–85 % записей. Шаг 1 (шаблон заголовка → A3) уже сделан отдельно;
здесь — остальные записи этих типов.

Правило замены: Sonnet и Opus ВСЛЕПУЮ (тип каталога не видят) размечают каждую запись; тип
меняется, только если обе модели независимо дали один и тот же код, он отличается от каталога
и обе уверены. Остальное не трогаем.

  python scripts/types_recheck_2026_11_24.py submit <слепок.csv>
  python scripts/types_recheck_2026_11_24.py collect
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_for_upload import SYSTEM2, answer_text, strip_fence  # noqa: E402
from types_batch2_2026_11_24 import CODES, body, item, snapshot  # noqa: E402
from common import anthropic_client, fix_stdout, load_env  # noqa: E402

TYPES = {"A2", "A1", "A6", "C2", "C5", "B2", "A5", "B10", "B6"}
MODELS = {"s": "claude-sonnet-5-5", "o": "claude-opus-5-5"}
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "types_recheck_2026-11-24"
STEP = 20


def submit(snap_path: str) -> None:
    snap = snapshot(snap_path)
    done = set()
    for p in (ROOT / "output" / "fixes").glob("*types*.csv"):
        done |= {r["page_id"] for r in csv.DictReader(open(p, encoding="utf-8"))}
    rows = [r for r in snap.values() if r["Статус приёмки"] == "принято" and r["Тип источника"] in TYPES
            and r["page_id"] not in done]
    items = [item(r) | {"cat": r["Тип источника"]} for r in rows]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "input.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
    load_env()
    client = anthropic_client()
    ids = {}
    for tag, model in MODELS.items():
        reqs = [{"custom_id": f"{tag}{k}", "params": {"model": model, "max_tokens": 6000, "system": SYSTEM2,
                 "messages": [{"role": "user", "content": body(items[k:k + STEP], k)}]}}
                for k in range(0, len(items), STEP)]
        ids[tag] = client.messages.batches.create(requests=reqs).id
    (WORK / "batches.json").write_text(json.dumps(ids), encoding="utf-8")
    print(f"записей {len(items)}: {dict(Counter(x['cat'] for x in items))}; пакеты {ids}")


def collect() -> None:
    load_env()
    client = anthropic_client()
    ids = json.loads((WORK / "batches.json").read_text(encoding="utf-8"))
    for tag, bid in ids.items():
        info = client.messages.batches.retrieve(bid)
        print(f"{tag}: {info.processing_status} {info.request_counts}")
        if info.processing_status != "ended":
            return
    items = [json.loads(x) for x in (WORK / "input.jsonl").open(encoding="utf-8")]
    ans = {t: {} for t in ids}
    for tag, bid in ids.items():
        for res in client.messages.batches.results(bid):
            try:
                for a in json.loads(strip_fence(answer_text(res.result.message))):
                    ans[tag][int(a["i"])] = a
            except (json.JSONDecodeError, AttributeError, KeyError, ValueError):
                continue
    fix, stat = [], Counter()
    note = ("Правка 24.11.2026 по выборочной проверке типов (решение владельца): тип {old} → {new} — "
            "Sonnet и Opus независимо и уверенно дали {new} ({w})")
    for i, x in enumerate(items):
        s, o = ans["s"].get(i), ans["o"].get(i)
        if not (s and o):
            stat["нет ответа"] += 1
            continue
        sc, oc = s.get("code"), o.get("code")
        if sc == oc == x["cat"]:
            stat["каталог подтверждён"] += 1
        elif sc == oc and sc in CODES and s.get("sure") and o.get("sure"):
            stat[f"{x['cat']}→{sc}"] += 1
            fix.append({"page_id": x["page_id"], "set": json.dumps({"Тип источника": sc}, ensure_ascii=False),
                        "note": note.format(old=x["cat"], new=sc, w=o.get("why", ""))})
        else:
            stat["модели не сошлись или не уверены"] += 1
    with (ROOT / "output" / "fixes" / "types_recheck_2026-11-24.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "set", "note"], lineterminator="\n")
        w.writeheader()
        w.writerows(fix)
    print(f"к правке {len(fix)}")
    for k, v in stat.most_common(30):
        print(f"  {v:6} {k}")


if __name__ == "__main__":
    fix_stdout()
    {"submit": lambda: submit(sys.argv[2]), "collect": collect}[sys.argv[1]]()
