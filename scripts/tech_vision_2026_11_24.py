"""Техника исполнения карт Госкаталога по скану (пачка 8 сессии анализа; решение владельца 24.11.2026).

Карточный интерфейс Госкаталога для скриптов закрыт (403 даже на robots.txt), превью сканов
открыты. Sonnet смотрит превью 800 px и называет технику. В каталог — только уверенные ответы,
с отметкой «техника определена моделью по скану».

  python scripts/tech_vision_2026_11_24.py fetch <слепок.csv> <пачка8.csv>   # скачать превью (1 с пауза)
  python scripts/tech_vision_2026_11_24.py gold                             # проверка на записях с известной техникой
  python scripts/tech_vision_2026_11_24.py submit
  python scripts/tech_vision_2026_11_24.py collect                          # → output/fixes/batch8_tech_*.csv
"""
import base64
import csv
import json
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_for_upload import answer_text, strip_fence  # noqa: E402
from common import anthropic_client, fix_stdout, load_env  # noqa: E402

MODEL = "claude-sonnet-5-5"
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "tech_vision_2026-11-24"
IMG = WORK / "img"
UA = {"User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347)"}
MAP = {"рукописная": "Рукописная", "гравюра": "Гравюра", "литография": "Литография",
       "хромолитография": "Хромолитография", "типографская": "Печатная", "фото": "Фотокопия"}
SYSTEM = """Ты специалист по историческим картам и планам XVIII — начала XX в. На изображении —
предмет музейного фонда (карта, план, чертёж или их фотография). Определи ТЕХНИКУ ИСПОЛНЕНИЯ
самого изображённого листа. Признаки: рукописная — неровные линии от руки, тушь, акварельная
раскраска, рукописные подписи; гравюра — тонкие штрихи резца, штриховка, гравированные надписи;
литография — мягкие линии, ровные печатные шрифты, часто с раскраской; хромолитография —
многоцветная печать; типографская — наборный текст, современная печать (офсет); фото — фотоотпечаток
или фотонегатив листа.
Ответь ТОЛЬКО JSON: {"tech": "рукописная"|"гравюра"|"литография"|"хромолитография"|"типографская"|"фото"|"не видно",
"sure": true|false, "why": "<до восьми слов>"}"""


def snap(p: str) -> dict:
    csv.field_size_limit(10**9)
    return {r["page_id"]: r for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


def preview(url: str) -> str:
    return re.sub(r"/public/(original|\d+)/", "/public/800/", url)


def fetch(snap_path: str, batch_csv: str) -> None:
    s = snap(snap_path)
    gk = [r for r in s.values() if r["Архив [авто]"].startswith("Госкаталог")]
    want = {r["page_id"] for r in csv.DictReader(open(batch_csv, encoding="utf-8-sig"))}
    todo = [r for r in gk if r["page_id"] in want]
    gold = [r for r in gk if r["Техника исполнения"] in ("Гравюра", "Печатная")][:25]
    gold += [r for r in gk if not r["Техника исполнения"] and re.search(r"рукописн", r["Название источника"] + r["Описание"], re.I)][:25]
    IMG.mkdir(parents=True, exist_ok=True)
    meta = []
    for r in gold + todo:
        tag = "gold" if r in gold else "todo"
        f = IMG / f"{r['page_id']}.jpg"
        if not f.exists():
            try:
                with urllib.request.urlopen(urllib.request.Request(preview(r["Ссылка на онлайн-архив"]), headers=UA), timeout=60) as resp:
                    f.write_bytes(resp.read())
            except Exception as e:  # noqa: BLE001
                print("  нет скана:", r["page_id"], str(e)[:60])
                continue
            time.sleep(1)
        known = r["Техника исполнения"] or ("Рукописная" if tag == "gold" else "")
        meta.append({"page_id": r["page_id"], "tag": tag, "known": known, "title": r["Название источника"][:200]})
    (WORK / "meta.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in meta), encoding="utf-8")
    print(f"скачано: эталон {sum(m['tag'] == 'gold' for m in meta)}, к разметке {sum(m['tag'] == 'todo' for m in meta)} (из {len(todo)})")


def req(m: dict) -> dict:
    data = base64.b64encode((IMG / f"{m['page_id']}.jpg").read_bytes()).decode()
    return {"model": MODEL, "max_tokens": 800, "system": SYSTEM,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": f"Название в каталоге музея: {m['title']}"}]}]}


def gold() -> None:
    load_env()
    client = anthropic_client()
    meta = [json.loads(x) for x in (WORK / "meta.jsonl").open(encoding="utf-8")]
    ok = n = 0
    for m in [x for x in meta if x["tag"] == "gold"]:
        try:
            a = json.loads(strip_fence(answer_text(client.messages.create(**req(m)))))
        except json.JSONDecodeError:
            print("  битый ответ:", m["title"][:60])
            continue
        got = MAP.get(a.get("tech"), "?")
        hit = (got == "Рукописная") == (m["known"] == "Рукописная")   # главное — рукописная или печатная
        n += 1
        ok += hit
        if not hit:
            print(f"  было {m['known']:10s} модель {got:10s} {'увер.' if a.get('sure') else 'неув.'} | {m['title'][:70]}")
    print(f"рукописная/печатная совпало {ok}/{n}")


def submit() -> None:
    load_env()
    client = anthropic_client()
    meta = [json.loads(x) for x in (WORK / "meta.jsonl").open(encoding="utf-8")]
    todo = [m for m in meta if m["tag"] == "todo"]
    ids = []
    for k in range(0, len(todo), 300):
        reqs = [{"custom_id": f"t{k + j}", "params": req(m)} for j, m in enumerate(todo[k:k + 300])]
        ids.append(client.messages.batches.create(requests=reqs).id)
    (WORK / "batches.json").write_text(json.dumps(ids), encoding="utf-8")
    print(f"записей {len(todo)}, пакетов {len(ids)}")


def collect() -> None:
    load_env()
    client = anthropic_client()
    ids = json.loads((WORK / "batches.json").read_text(encoding="utf-8"))
    for b in ids:
        info = client.messages.batches.retrieve(b)
        if info.processing_status != "ended":
            print("ещё идёт:", b, info.request_counts)
            return
    todo = [m for m in map(json.loads, (WORK / "meta.jsonl").open(encoding="utf-8")) if m["tag"] == "todo"]
    out, stat = [], Counter()
    note = "Правка 24.11.2026 по замечанию сессии анализа (пачка 8): техника «{t}» определена моделью по скану Госкаталога ({w})"
    for b in ids:
        for res in client.messages.batches.results(b):
            m = todo[int(res.custom_id[1:])]
            try:
                a = json.loads(strip_fence(answer_text(res.result.message)))
            except (json.JSONDecodeError, AttributeError):
                stat["битый ответ"] += 1
                continue
            t = MAP.get(a.get("tech"))
            stat[(a.get("tech"), bool(a.get("sure")))] += 1
            if t and a.get("sure"):
                out.append({"page_id": m["page_id"], "set": json.dumps({"Техника исполнения": t}, ensure_ascii=False),
                            "note": note.format(t=t, w=a.get("why", ""))})
    with (ROOT / "output" / "fixes" / "batch8_tech_2026-11-24.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "set", "note"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    print(f"к записи {len(out)}; {stat.most_common()}")


if __name__ == "__main__":
    fix_stdout()
    {"fetch": lambda: fetch(sys.argv[2], sys.argv[3]), "gold": gold, "submit": submit,
     "collect": collect}[sys.argv[1]]()
