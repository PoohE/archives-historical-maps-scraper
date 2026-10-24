"""Прогон focr по машинописным описям ГАСО: PDF -> markdown + JSON.

`focr ocr` принимает PDF напрямую (растрирует страницы сам), поэтому рендерить
страницы заранее не нужно.

Возобновляемый: опись с готовым `.md` пропускается, поэтому после обрыва скрипт
запускается той же командой. Каждая опись идёт ОТДЕЛЬНЫМ процессом — падение одной
(например по памяти) не роняет остальные.

Запуск (Винки):
    python -B scripts_gaso/focr_opisi_run.py C:\\arch\\gaso_in C:\\arch\\gaso_focr_out

Проверка перед запуском:  focr doctor   и   focr models --json
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

FOCR_DEFAULT = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "focr" / "focr.exe"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="папка с PDF описей")
    ap.add_argument("out", help="папка для результатов")
    ap.add_argument("--focr", default=str(FOCR_DEFAULT))
    ap.add_argument("--timeout", type=int, default=3600, help="секунд на одну опись")
    args = ap.parse_args()

    focr, src, out = Path(args.focr), Path(args.src), Path(args.out)
    if not focr.exists():
        print(f"НЕ НАЙДЕН focr: {focr}\nукажите путь флагом --focr")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    log = out / "run.log"

    pdfs = sorted(src.glob("*.pdf"))
    if not pdfs:
        print(f"PDF в {src} не найдено")
        return 1
    print(f"описей к прогону: {len(pdfs)}")

    ok, failed, skipped = 0, [], 0
    for pdf in pdfs:
        md = out / f"{pdf.stem}.md"
        if md.exists() and md.stat().st_size > 0:
            skipped += 1
            print(f"= {pdf.name}: уже готово, пропуск")
            continue
        t0 = time.time()
        cmd = [str(focr), "ocr", str(pdf), "-o", str(md)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=args.timeout)
        except subprocess.TimeoutExpired:
            failed.append((pdf.name, f"таймаут {args.timeout} с"))
            print(f"✗ {pdf.name}: таймаут")
            continue
        el = time.time() - t0
        if r.returncode == 0 and md.exists() and md.stat().st_size > 0:
            ok += 1
            print(f"✓ {pdf.name}: {md.stat().st_size // 1024} КБ за {el / 60:.1f} мин")
        else:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            reason = tail[-1][:200] if tail else f"код {r.returncode}"
            failed.append((pdf.name, reason))
            print(f"✗ {pdf.name}: {reason}")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%F %T')}\t{pdf.name}\tcode={r.returncode}\t"
                     f"{el:.0f}s\t{(r.stderr or '').strip()[:300]}\n")

    print(f"\nитог: готово {ok}, пропущено {skipped}, провалено {len(failed)}")
    for name, why in failed:
        print(f"  ✗ {name}: {why}")
    print(f"журнал: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
