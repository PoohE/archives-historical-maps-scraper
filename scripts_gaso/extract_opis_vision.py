"""Извлечение записей из рукописной описи ГАСО через Claude Vision (API-ключ, не подписка).

Калибровка 13.10.2026 (`calibrate_screening.py`, ф. 576 стр. 34) показала:
  - Haiku 4.5 на скорописи ВЫДУМЫВАЕТ объекты («Симоновский монастырь» там, где его нет) —
    применять нельзя ни для отбора, ни для извлечения;
  - Sonnet 5 читает верно; подача страницы ДВУМЯ ПОЛОВИНАМИ полнее, чем целиком
    (ловит больше строк и фамилии), расход ~4250 вход / ~690 выход на страницу.

Возобновляемый: готовые страницы берутся из уже записанного JSONL, повтор — та же команда.

Запуск:
    python -B scripts_gaso/extract_opis_vision.py --pdf C:\\arch\\output\\gaso_opisi_20261013\\576_1.pdf \\
        --out C:\\arch\\output\\gaso_vision_20261013\\576_1.jsonl --fund 576 --opis 1
"""
from __future__ import annotations

import argparse
import base64
import io
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

MODEL = "claude-sonnet-5"
PRICE_IN, PRICE_OUT = 2.0, 10.0          # $ за 1 млн токенов, Sonnet 5 (прайс на 13.10.2026)
MAX_EDGE = 1540
# ⚠️ 8000 не хватало: плотные развороты ф. 428 упирались в потолок ровно на 8000 токенов,
# JSON обрывался на полуслове и страница уходила в «не разобрано» (19 страниц из 131).
MAX_TOKENS = 16000

PROMPT = """Перед тобой разворот рукописной архивной описи (Россия, XIX — начало XX в.),
поданный двумя изображениями: левая половина, затем правая.

Выпиши КАЖДУЮ запись описи построчно. Ничего не додумывай и не дополняй по смыслу:
нечитаемое место — `<нрзб>`, отсутствующее поле — null.

Верни ТОЛЬКО JSON-массив без пояснений, каждый элемент:
{
  "n_poryadok": "номер по порядку, как в графе (строкой)",
  "n_delo": "номер дела / входящего, если есть",
  "zagolovok": "заголовок дела дословно, с сокращениями оригинала",
  "data_nachato": "дата начала как в документе",
  "data_okoncheno": "дата окончания как в документе",
  "listov": "число листов, если указано",
  "obyekt": "географический объект: дача, пустошь, село, сельцо, деревня, волость, уезд, город",
  "kartograficheskiy_priznak": "план | выкопировка | чертёж | карта | межевание | размежевание | съёмка | геодезическое описание | межевая книга | экономические примечания | ведомость дачам | владенная запись | нет",
  "primechanie": "пометы, штампы, «выбыло» и прочее — или null"
}

Правила:
- порядок записей — как на развороте, сверху вниз, сначала левая половина;
- если одна запись продолжается на второй половине, объединяй её в одну;
- `kartograficheskiy_priznak` ставь только если соответствующее слово ЕСТЬ в заголовке,
  иначе "нет"; не выводи признак из догадок о содержании дела;
- пустой массив [] — ТОЛЬКО для действительно чистого листа: обложка, линованный лист
  без записей, оборот без текста. Если на развороте есть хоть одна строка рукописи —
  выписывай её, даже когда почерк трудный, номера не читаются или часть граф пуста;
  нечитаемые места закрывай `<нрзб>`, но запись не пропускай.
  ⚠️ Проверено на ф. 428: треть страниц с плотным текстом вернулась пустым массивом —
  это потеря данных, а не «служебный лист»."""


def img_block(pix, crop=None) -> dict:
    from PIL import Image

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if crop:
        img = img.crop(crop)
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70, optimize=True)
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def parse_json(text: str) -> list[dict] | None:
    """Разобрать ответ модели. При обрыве по лимету токенов спасаем целые объекты."""
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    # обрезанный массив: собрать объекты, которые успели закрыться
    salvaged = []
    for chunk in re.findall(r"\{[^{}]*\}", text, re.S):
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("zagolovok"):
            obj["flags"] = "ответ_обрезан"
            salvaged.append(obj)
    return salvaged or None


def main() -> int:
    fix_stdout()
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True, help="путь к JSONL (одна строка = одна страница)")
    ap.add_argument("--fund", required=True)
    ap.add_argument("--opis", required=True)
    ap.add_argument("--model", default=MODEL)
    # 150 dpi: половина разворота ≈ 1500 px по длинной стороне — ровно под MAX_EDGE.
    # При 200 dpi система убивала прогон по памяти (разворот ф. 576 — 18 Мпикс, ~54 МБ),
    # а выигрыша нет: изображение всё равно ужимается до MAX_EDGE перед отправкой.
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--from-page", type=int, default=1)
    ap.add_argument("--to-page", type=int, default=0, help="0 — до конца")
    args = ap.parse_args()

    import fitz

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done: set[int] = set()
    if out.exists():
        done = {json.loads(ln)["page"] for ln in out.open(encoding="utf-8") if ln.strip()}
        print(f"уже готово страниц: {len(done)}")

    doc = fitz.open(args.pdf)
    last = args.to_page or doc.page_count
    client = anthropic_client()
    tin = tout = 0
    records = 0
    pages_done = 0
    t0 = time.time()

    with out.open("a", encoding="utf-8") as fh:
        for pno in range(args.from_page, last + 1):
            if pno in done:
                continue
            page = doc.load_page(pno - 1)
            pix = page.get_pixmap(dpi=args.dpi)
            w, h = pix.width, pix.height
            blocks = [img_block(pix, (0, 0, w // 2, h)), img_block(pix, (w // 2, 0, w, h))]
            del pix, page                # не держать растр разворота, пока идёт запрос
            try:
                r = client.messages.create(
                    model=args.model, max_tokens=MAX_TOKENS,
                    messages=[{"role": "user",
                               "content": [*blocks, {"type": "text", "text": PROMPT}]}],
                )
            except Exception as exc:                              # noqa: BLE001
                print(f"  стр.{pno}: ОШИБКА {type(exc).__name__}: {exc}")
                continue
            text = "\n".join(b.text for b in r.content if b.type == "text")
            rows = parse_json(text)
            tin += r.usage.input_tokens
            tout += r.usage.output_tokens
            rec = {"page": pno, "fund": args.fund, "opis": args.opis,
                   "model": args.model,
                   "usage": {"in": r.usage.input_tokens, "out": r.usage.output_tokens},
                   "rows": rows if rows is not None else [],
                   "raw": None if rows is not None else text[:4000]}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n = len(rec["rows"])
            records += n
            pages_done += 1
            flag = "" if rows is not None else "  ⚠ JSON не разобран, сырой текст сохранён"
            print(f"  стр.{pno}/{last}: записей {n}{flag}")

    cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    print(f"\nстраниц обработано: {pages_done}, записей {records}, "
          f"время {(time.time() - t0) / 60:.1f} мин")
    print(f"токены: вход {tin:,}, выход {tout:,} → ${cost:.2f} "
          f"(через Batch было бы ${cost / 2:.2f})")
    print(f"выход: {out}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

