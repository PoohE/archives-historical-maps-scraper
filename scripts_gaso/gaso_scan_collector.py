"""Сборщик сканов описей ГАСО (portal.gaso-smolensk.ru) — карта id и скачивание PDF.

Блокер снят 09.10.2026 живым зондом: PDF описи доступен так —
  1) GET `/page/portal/opisView.jsf?id=N` в сессии с куками;
  2) клик вкладки «Скан-образы описи» (PrimeFaces postback);
  3) клик превью файла → в DOM появляется `iframe[title="Document Viewer"]`;
  4) его параметр `file` указывает на `dynamiccontent.properties.jsf?...pfdrid=...&uid=...`;
  5) GET этого URL с теми же куками отдаёт PDF (сервер врёт типом `video/quicktime`,
     тело начинается с `%PDF`). `pfdrid` сессионный — кэшировать между сессиями нельзя.

Принадлежность описи фонду на странице НЕ написана: единственный ключ — подпись файла
скана вида `<фонд>_<опись>` (например `259_1`).

Режимы:
  --probe 1,155,500,...   точки для проверки (печатает фонд/опись/заголовок, ничего не пишет)
  --map A-B               обойти диапазон id, собрать карту в `opis_map.jsonl`
  --download              скачать PDF для фондов из `--funds` по собранной карте

Выход — ТОЛЬКО локальная папка (по умолчанию `C:\\arch\\output\\gaso_scans_<дата>`):
состояние переписывается часто, на Яндекс.Диске это даёт конфликтные копии и `WinError 5`.

Запуск:
    python -B scripts_gaso/gaso_scan_collector.py --probe 154,155,156,800,1600,2400
    python -B scripts_gaso/gaso_scan_collector.py --map 1-2600
    python -B scripts_gaso/gaso_scan_collector.py --download --funds 814,428,13,576,334,259
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

BASE = "https://portal.gaso-smolensk.ru"
OPIS_URL = BASE + "/page/portal/opisView.jsf?id={id}"
OUT_DEFAULT = Path(r"C:\arch\output") / f"gaso_scans_{time.strftime('%Y%m%d')}"
DELAY = 1.6          # пауза между страницами, с (портал областного архива не нагружать)
NAV_TIMEOUT = 60_000
FAIL_STREAK_STOP = 25   # устойчивая серия пустых/неответивших id → конец диапазона

# Подписи файлов сканов на портале НЕ единообразны (измерено 09.10 на id 154/155/156/800):
#   «259_1»                  — один PDF описи, формат <фонд>_<опись>
#   «Ф228_оп1_л (1).JPG»     — постраничные образы описи, серия JPG
#   «Фонд 1227, опись 1»     — подпись словами
# Плюс бывают описи вообще без сканов (HTTP 200, список файлов пуст).
SCAN_PATTERNS = [
    re.compile(r"^\s*(?P<fund>\d+)[_\-](?P<opis>[\w.]+?)\s*$"),
    re.compile(r"^\s*Ф\.?\s*(?P<fund>\d+)[_\s]*оп\.?\s*(?P<opis>[\w.]+?)(?:[_\s]|$)", re.I),
    re.compile(r"^\s*Фонд\s*(?P<fund>\d+)\s*,\s*опись\s*(?P<opis>[\w.]+)", re.I),
]


def parse_scan_label(label: str) -> tuple[str, str] | None:
    for rx in SCAN_PATTERNS:
        m = rx.match(label)
        if m:
            return m.group("fund"), m.group("opis")
    return None


def label_kind(label: str) -> str:
    low = label.lower()
    if low.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
        return "image_series"
    if low.endswith(".pdf"):
        return "pdf"
    return "pdf_unnamed"      # «259_1», «Фонд N, опись M» — у нас оба оказались PDF


def read_page(page, oid: int) -> dict:
    """Открыть описание описи и снять поля + подпись скана. Сеть: один переход."""
    rec: dict = {"id": oid, "ok": False}
    try:
        resp = page.goto(OPIS_URL.format(id=oid), timeout=NAV_TIMEOUT,
                         wait_until="domcontentloaded")
    except Exception as exc:                                   # noqa: BLE001
        rec["error"] = f"nav:{type(exc).__name__}"
        return rec
    rec["http"] = resp.status if resp else None
    if not resp or resp.status != 200:
        return rec

    data = page.evaluate(
        """async () => {
            const out = {};
            const text = (sel) => {
                const e = document.querySelector(sel);
                return e ? e.textContent.trim() : '';
            };
            // поля «Общие сведения» идут парами метка→значение в таблице панели
            const rows = [...document.querySelectorAll('.data-content label, .data-content td')]
                .map(e => e.textContent.trim()).filter(Boolean);
            out.fields = rows.slice(0, 60);
            out.title_page = document.title;
            // вкладка со сканами
            const tab = [...document.querySelectorAll('a')]
                .find(a => a.textContent.trim() === 'Скан-образы описи');
            out.has_scan_tab = !!tab;
            if (tab) {
                tab.click();
                await new Promise(r => setTimeout(r, 2500));
            }
            out.scan_labels = [...document.querySelectorAll('.file-name-panel')]
                .map(e => e.textContent.trim());
            out.units = text('[id$="unitsCount"]');
            return out;
        }"""
    )
    rec["ok"] = True
    rec["has_scan_tab"] = data.get("has_scan_tab")
    rec["scan_labels"] = data.get("scan_labels") or []
    rec["fields"] = data.get("fields") or []
    rec["files_count"] = len(rec["scan_labels"])
    for lab in rec["scan_labels"]:
        got = parse_scan_label(lab)
        if got:
            rec["fund"], rec["opis"] = got
            rec["scan_kind"] = label_kind(lab)
            break
    return rec


def grab_pdf_url(page) -> str | None:
    """Открыть превью первого файла и вернуть URL dynamiccontent (сессионный)."""
    return page.evaluate(
        """async () => {
            const a = document.querySelector('[id$="dataPreview_content"] a');
            if (!a) return null;
            a.click();
            for (let i = 0; i < 24; i++) {
                await new Promise(r => setTimeout(r, 500));
                const ifr = document.querySelector('iframe[title="Document Viewer"]');
                if (ifr && ifr.src) {
                    const f = new URL(ifr.src).searchParams.get('file');
                    if (f) return new URL(f, location.origin).href;
                }
            }
            return null;
        }"""
    )


def download_pdf(page, url: str, dest: Path) -> dict:
    """Скачать файл в контексте страницы (куки сессии обязательны)."""
    res = page.evaluate(
        """async (u) => {
            const r = await fetch(u, {credentials: 'include'});
            const buf = await r.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let bin = '';
            const chunk = 0x8000;
            for (let i = 0; i < bytes.length; i += chunk) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
            }
            return {status: r.status, b64: btoa(bin),
                    head: new TextDecoder().decode(buf.slice(0, 8))};
        }""", url)
    if res["status"] != 200:
        return {"ok": False, "http": res["status"]}
    import base64
    blob = base64.b64decode(res["b64"])
    dest.write_bytes(blob)
    return {"ok": res["head"].startswith("%PDF"), "http": 200, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "head": res["head"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", help="список id через запятую — разведка без записи")
    ap.add_argument("--map", help="диапазон id вида 1-2600")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--funds", default="", help="номера фондов через запятую")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    ap.add_argument("--headed", action="store_true", default=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        page = browser.new_page()
        page.set_default_timeout(NAV_TIMEOUT)

        if args.probe:
            ids = [int(x) for x in args.probe.split(",") if x.strip()]
            print(f"{'id':>6} {'http':>5} {'фонд':>6} {'оп.':>5}  подписи / ошибка")
            for oid in ids:
                rec = read_page(page, oid)
                print(f"{oid:>6} {str(rec.get('http')):>5} "
                      f"{rec.get('fund', '—'):>6} {rec.get('opis', '—'):>5}  "
                      f"{rec.get('scan_kind', '—')} ×{rec.get('files_count', 0)}  "
                      f"{(rec.get('scan_labels') or [rec.get('error', '')])[0]}")
                print(f"         поля: {' | '.join(rec.get('fields', [])[:12])}")
                time.sleep(DELAY)
            browser.close()
            return 0

        if args.map:
            lo, hi = (int(x) for x in args.map.split("-"))
            state_f = out / "map_state.json"
            map_f = out / "opis_map.jsonl"
            start = lo
            if state_f.exists():
                start = json.loads(state_f.read_text(encoding="utf-8"))["next_id"]
                print(f"возобновление с id={start}")
            streak = 0
            with map_f.open("a", encoding="utf-8") as fh:
                for oid in range(start, hi + 1):
                    rec = read_page(page, oid)
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    state_f.write_text(json.dumps({"next_id": oid + 1}), encoding="utf-8")
                    streak = streak + 1 if not rec.get("fund") else 0
                    if rec.get("fund"):
                        print(f"  id={oid}: ф.{rec['fund']} оп.{rec['opis']}")
                    if streak >= FAIL_STREAK_STOP:
                        print(f"\n{streak} id подряд без скана — считаю диапазон законченным "
                              f"на id={oid}")
                        break
                    time.sleep(DELAY)
            browser.close()
            return 0

        if args.download:
            want = {x.strip() for x in args.funds.split(",") if x.strip()}
            rows = [json.loads(ln) for ln in (out / "opis_map.jsonl").open(encoding="utf-8")
                    if ln.strip()]
            targets = [r for r in rows if r.get("fund") in want]
            print(f"по карте найдено описей целевых фондов: {len(targets)}")
            man_f = out / "manifest.json"
            manifest = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else []
            done = {(m["id"]) for m in manifest}
            for r in targets:
                if r["id"] in done:
                    continue
                page.goto(OPIS_URL.format(id=r["id"]), wait_until="domcontentloaded")
                page.evaluate(
                    """async () => {
                        const t = [...document.querySelectorAll('a')]
                            .find(a => a.textContent.trim() === 'Скан-образы описи');
                        if (t) { t.click(); await new Promise(r => setTimeout(r, 2500)); }
                    }""")
                url = grab_pdf_url(page)
                if not url:
                    manifest.append({**r, "downloaded": False, "reason": "no_viewer_url"})
                    print(f"  id={r['id']} ф.{r['fund']} оп.{r['opis']}: просмотрщик не открылся")
                else:
                    dest = out / f"{r['fund']}_{r['opis']}.pdf"
                    res = download_pdf(page, url, dest)
                    manifest.append({**r, "downloaded": res["ok"], "file": dest.name,
                                     "page_url": OPIS_URL.format(id=r["id"]), **res})
                    print(f"  id={r['id']} ф.{r['fund']} оп.{r['opis']}: "
                          f"{res.get('bytes', 0):,} б, {res.get('head')}")
                man_f.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
                time.sleep(DELAY)
            browser.close()
            return 0

    print("укажите --probe, --map или --download")
    return 1


if __name__ == "__main__":
    sys.exit(main())
