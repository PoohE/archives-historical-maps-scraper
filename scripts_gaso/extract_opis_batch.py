"""Распознавание описей ГАСО через Batch API (-50 % к цене, асинхронно, до 24 ч).

Тот же промпт и та же подача (страница двумя половинами), что в `extract_opis_vision.py`,
но страницы уходят пачкой и не держат сессию. Для одной описи на 60+ страниц синхронный
прогон занимает час и падает на этой машине по памяти; батч этого лишён.

Режимы:
    --submit   собрать запросы по описям и отправить; id батчей пишутся в batches.json
    --status   показать состояние отправленных батчей
    --fetch    забрать готовые результаты в JSONL того же формата, что у синхронного движка

Запуск:
    python -B scripts_gaso/extract_opis_batch.py --submit --src C:\\arch\\output\\gaso_opisi_20261013 \\
        --out C:\\arch\\output\\gaso_vision_20261013 --files 237_1_часть1,237_1_часть2,428_1,428_2,1071_1
    python -B scripts_gaso/extract_opis_batch.py --status --out C:\\arch\\output\\gaso_vision_20261013
    python -B scripts_gaso/extract_opis_batch.py --fetch  --out C:\\arch\\output\\gaso_vision_20261013
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
try:
    from common import anthropic_client, fix_stdout, load_env
except ImportError:
    def fix_stdout() -> None:
        sys.stdout.reconfigure(encoding="utf-8")

    def load_env() -> None:
        from dotenv import load_dotenv
        load_dotenv(Path.home() / ".secrets" / "claude.env")

    def anthropic_client():
        import os

        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_opis_vision import MAX_TOKENS, MODEL, PRICE_IN, PRICE_OUT, PROMPT, img_block, parse_json  # noqa: E402

STATE = "batches.json"
CUSTOM_ID_RE = re.compile(r"^(?P<stem>.+)__p(?P<page>\d+)$")


def safe_id(stem: str, page: int) -> str:
    """custom_id ограничен латиницей/цифрами/._- — кириллица в именах файлов не пройдёт."""
    key = re.sub(r"[^A-Za-z0-9._-]", "_", stem)
    return f"{key}__p{page}"


def mode_submit(client, src: Path, out: Path, files: list[str], dpi: int) -> int:
    import fitz

    out.mkdir(parents=True, exist_ok=True)
    state_f = out / STATE
    state = json.loads(state_f.read_text(encoding="utf-8")) if state_f.exists() else {}

    for stem in files:
        pdf = src / f"{stem}.pdf"
        if not pdf.exists():
            print(f"НЕТ файла {pdf.name}")
            continue
        done: set[int] = set()
        jsonl = out / f"{stem}.jsonl"
        if jsonl.exists():
            done = {json.loads(ln)["page"] for ln in jsonl.open(encoding="utf-8") if ln.strip()}

        doc = fitz.open(pdf)
        requests = []
        for pno in range(1, doc.page_count + 1):
            if pno in done:
                continue
            pix = doc.load_page(pno - 1).get_pixmap(dpi=dpi)
            w, h = pix.width, pix.height
            blocks = [img_block(pix, (0, 0, w // 2, h)), img_block(pix, (w // 2, 0, w, h))]
            del pix
            requests.append({
                "custom_id": safe_id(stem, pno),
                "params": {"model": MODEL, "max_tokens": MAX_TOKENS,
                           "messages": [{"role": "user",
                                         "content": [*blocks, {"type": "text", "text": PROMPT}]}]},
            })
        doc.close()
        if not requests:
            print(f"{stem}: все страницы уже готовы")
            continue
        batch = client.messages.batches.create(requests=requests)
        state[batch.id] = {"stem": stem, "pages": len(requests),
                           "submitted": time.strftime("%F %T")}
        state_f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{stem}: отправлено {len(requests)} стр. → батч {batch.id}")
    return 0


def mode_status(client, out: Path) -> int:
    state_f = out / STATE
    if not state_f.exists():
        print("нет отправленных батчей")
        return 1
    state = json.loads(state_f.read_text(encoding="utf-8"))
    for bid, meta in state.items():
        b = client.messages.batches.retrieve(bid)
        c = b.request_counts
        print(f"{meta['stem']:<16} {b.processing_status:<10} "
              f"готово {c.succeeded}/{meta['pages']}, ошибок {c.errored}, "
              f"в работе {c.processing} (отправлен {meta['submitted']})")
    return 0


def mode_fetch(client, out: Path) -> int:
    state_f = out / STATE
    state = json.loads(state_f.read_text(encoding="utf-8"))
    tin = tout = 0
    for bid, meta in state.items():
        b = client.messages.batches.retrieve(bid)
        if b.processing_status != "ended":
            print(f"{meta['stem']}: ещё считается ({b.processing_status})")
            continue
        stem = meta["stem"]
        jsonl = out / f"{stem}.jsonl"
        done = set()
        if jsonl.exists():
            done = {json.loads(ln)["page"] for ln in jsonl.open(encoding="utf-8") if ln.strip()}
        added = 0
        with jsonl.open("a", encoding="utf-8") as fh:
            for res in client.messages.batches.results(bid):
                m = CUSTOM_ID_RE.match(res.custom_id)
                pno = int(m.group("page")) if m else -1
                if pno in done or res.result.type != "succeeded":
                    if res.result.type != "succeeded":
                        print(f"  {res.custom_id}: {res.result.type}")
                    continue
                msg = res.result.message
                text = "\n".join(bl.text for bl in msg.content if bl.type == "text")
                rows = parse_json(text)
                tin += msg.usage.input_tokens
                tout += msg.usage.output_tokens
                fund, _, opis = stem.partition("_")
                fh.write(json.dumps({
                    "page": pno, "fund": fund, "opis": opis, "model": MODEL,
                    "usage": {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens},
                    "rows": rows if rows is not None else [],
                    "raw": None if rows is not None else text[:4000],
                }, ensure_ascii=False) + "\n")
                added += 1
        print(f"{stem}: забрано {added} страниц → {jsonl.name}")
    if tin or tout:
        full = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
        print(f"\nтокены: вход {tin:,}, выход {tout:,} → ${full / 2:.2f} (batch, -50 %)")
    return 0


def main() -> int:
    fix_stdout()
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--src", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--files", default="")
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    client = anthropic_client()
    out = Path(args.out)
    if args.submit:
        return mode_submit(client, Path(args.src), out,
                           [x for x in args.files.split(",") if x.strip()], args.dpi)
    if args.status:
        return mode_status(client, out)
    if args.fetch:
        return mode_fetch(client, out)
    print("укажите --submit, --status или --fetch")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

