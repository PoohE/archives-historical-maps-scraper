"""Калибровка дешёвого скрининга рукописных описей ГАСО.

Задача первого (дешёвого) прохода — не прочитать опись, а ответить, есть ли на странице
дела с картографическим признаком. Ошибка «нет, когда на самом деле да» списывает целую
опись, поэтому модель и формат картинки выбираются ИЗМЕРЕНИЕМ на страницах с заранее
известным ответом, а не на глаз.

Матрица: {haiku, sonnet} × {страница целиком, страница половинами}.
Эталон: ф. 576 стр. 34 — там точно есть «план на дачу Гжатского уезда пустоши Мошиной»,
«о размежевании земли села Верховья», «именные ведомости дачам».

Запуск:
    python -B scripts_gaso/calibrate_screening.py --pdf C:\\arch\\output\\gaso_opisi_20261013\\576_1.pdf \\
        --pages 34,12,50
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
try:
    from common import anthropic_client, fix_stdout, load_env
except ImportError:                                     # запуск вне общего дерева
    def fix_stdout() -> None:
        sys.stdout.reconfigure(encoding="utf-8")

    def load_env() -> None:
        from dotenv import load_dotenv
        load_dotenv(Path.home() / ".secrets" / "claude.env")

    def anthropic_client():
        import os

        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODELS = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5"}
MAX_EDGE = 1540          # рекомендованный предел длинной стороны для vision

PROMPT = """Перед тобой страница рукописной архивной описи (Россия, XIX — начало XX в.).

Твоя задача — только отбор, не расшифровка. Выпиши заголовки дел, в которых есть
КАРТОГРАФИЧЕСКИЙ признак или привязанные к местности данные:
план, выкопировка, чертёж, карта, межевание и размежевание, съёмка, геодезическое
описание, межевая книга, экономические примечания, ведомость дачам, владенная запись.

Формат ответа — строго:
ЕСТЬ: <краткий заголовок> | <объект: дача, село, пустошь, уезд, волость>
...либо одна строка:
НЕТ

Ничего не додумывай: если слово не читается, пиши <нрзб>. Не пересказывай страницу целиком."""


def img_block(pix, crop=None) -> dict:
    from PIL import Image

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if crop:
        img = img.crop(crop)
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70, optimize=True)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg",
                   "data": base64.standard_b64encode(buf.getvalue()).decode()},
    }


def ask(client, model: str, blocks: list[dict]) -> tuple[str, int, int]:
    r = client.messages.create(
        model=model, max_tokens=700,
        messages=[{"role": "user", "content": [*blocks, {"type": "text", "text": PROMPT}]}],
    )
    text = "\n".join(b.text for b in r.content if b.type == "text").strip()
    return text, r.usage.input_tokens, r.usage.output_tokens


def main() -> int:
    fix_stdout()
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--pages", default="34", help="номера страниц через запятую (с 1)")
    args = ap.parse_args()

    import fitz

    doc = fitz.open(args.pdf)
    client = anthropic_client()
    totals: dict[str, list[int]] = {}

    for pno in [int(x) for x in args.pages.split(",") if x.strip()]:
        page = doc.load_page(pno - 1)
        pix = page.get_pixmap(dpi=200)
        whole = [img_block(pix)]
        w, h = pix.width, pix.height
        halves = [img_block(pix, (0, 0, w // 2, h)), img_block(pix, (w // 2, 0, w, h))]

        for mname, mid in MODELS.items():
            for vname, blocks in (("целиком", whole), ("половинами", halves)):
                try:
                    text, tin, tout = ask(client, mid, blocks)
                except Exception as exc:                        # noqa: BLE001
                    print(f"\n### стр.{pno} | {mname} | {vname}: ОШИБКА {type(exc).__name__}: {exc}")
                    continue
                key = f"{mname}/{vname}"
                acc = totals.setdefault(key, [0, 0, 0])
                acc[0] += tin
                acc[1] += tout
                acc[2] += 1
                print(f"\n### стр.{pno} | {mname} | {vname} | вход {tin}, выход {tout}")
                print(text[:900])

    print("\n\n=== расход по вариантам (на все проверенные страницы) ===")
    for key, (tin, tout, n) in totals.items():
        print(f"{key:<22} страниц {n}, вход {tin:>7}, выход {tout:>5}, "
              f"на страницу: вход {tin // n}, выход {tout // n}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
