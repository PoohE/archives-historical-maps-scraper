"""Сборщик сканов описей ГАСО (portal.gaso-smolensk.ru): карта описей и скачивание PDF.

Измерено живыми зондами 09.10.2026 — не перепроверять:

**Карта описей берётся простым GET, браузер не нужен.** Страница
`/page/portal/opisView.jsf?id=N` отдаёт в сыром HTML и поля описи
(`<div class="caption">МЕТКА:</div> … <div class="value">ЗНАЧЕНИЕ</div>`), и подписи файлов
сканов (`class="file-name-panel"`, значение в `title=`) — клик по вкладке «Скан-образы описи»
для чтения подписей НЕ требуется, содержимое уже в DOM.

**Номер фонда на странице не написан.** Единственный ключ принадлежности — подпись файла
скана. Форматов три (и это ломает допущение «всегда `<фонд>_<опись>`»):
  «259_1»                → один PDF описи                       (id=155, ф. 259 оп. 1)
  «Ф228_оп1_л (1).JPG»   → постраничные образы, серия из 13–24   (id=154 ф. 228, id=156 ф. 277)
  «Фонд 1227, опись 1»   → подпись словами, один PDF             (id=800)
Бывают описи вообще без сканов: HTTP 200, поля есть, список файлов пуст (id=1600 — ф. ?
оп. 2, 1918–1921, «Опись дел постоянного хранения»). Такой id — НЕ конец диапазона.

**Скачивание PDF требует браузера** (сессионный JSF-диалог):
  1) открыть `opisView.jsf?id=N`;
  2) клик вкладки «Скан-образы описи» (PrimeFaces postback);
  3) клик превью файла → в DOM появляется `iframe[title="Document Viewer"]`;
  4) его параметр `file` → URL `dynamiccontent.properties.jsf?...pfdrid=…&uid=…`;
  5) GET этого URL с куками сессии отдаёт файл.
Проверено на ф. 259 оп. 1: 8 339 011 байт, `%PDF-1.6` — совпало с `input_gaso/document.pdf`.
⚠️ Сервер врёт типом (`video/quicktime`) — проверять тело на `%PDF`, не заголовок.
⚠️ `pfdrid` сессионный, между сессиями не переиспользуется.
⚠️ На страницах есть блоки «Требуется оплата» / «приобретите абонемент» — часть услуг
портала платная; скачивание скана описи у ф. 259 прошло без оплаты, но следить за этим.

Выход — ТОЛЬКО локальная папка (`C:\\arch\\output\\...`): состояние переписывается часто,
на Яндекс.Диске это даёт конфликтные копии и `PermissionError [WinError 5]`.

**Список описей берётся с сайта архива, а не обходом id** (решение 13.10.2026). В
«Электронном каталоге» `gaso-smolensk.ru/nauchno-spravochnyj-apparat/jelektronnyj-katalog/`
у каждого фонда стоят прямые ссылки на его описи с их id портала — это точнее обхода
`--map 1-2600`, где номер фонда приходилось угадывать по подписи скана. Отсюда режим
`--map-ids`: та же карта `opis_map.jsonl`, но по готовому списку id.

Режимы:
    python -B scripts_gaso/gaso_scan_collector.py --probe 154,155,156,800,1600
    python -B scripts_gaso/gaso_scan_collector.py --map 1-2600
    python -B scripts_gaso/gaso_scan_collector.py --map-ids 155,377,378 --out C:\\arch\\output\\gaso
    python -B scripts_gaso/gaso_scan_collector.py --download --funds 814,428,13,576,334,259
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://portal.gaso-smolensk.ru"
OPIS_URL = BASE + "/page/portal/opisView.jsf?id={id}"
OUT_DEFAULT = Path(r"C:\arch\output") / f"gaso_scans_{time.strftime('%Y%m%d')}"
DELAY = 1.6              # пауза между запросами, с — портал областного архива не нагружать
TIMEOUT = 60
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
HTTP_FAIL_STOP = 3       # столько подряд 403/429 → штатная остановка

CAPTION_VALUE = re.compile(
    r'<div class="caption">\s*(?P<cap>[^<]{1,80}?)\s*:?\s*</div>.*?'
    r'<div class="value">\s*(?P<val>.*?)\s*</div>',
    re.S)
FILE_LABEL = re.compile(r'class="[^"]*file-name-panel[^"]*"[^>]*>.*?title="([^"]{1,120})"', re.S)
FILE_LABEL_ALT = re.compile(r'<label[^>]+title="([^"]{1,120})"[^>]*>\s*\1\s*</label>')
H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
TAG = re.compile(r"<[^>]+>")

# Подписи файлов сканов: три формата (см. докстринг)
SCAN_PATTERNS = [
    re.compile(r"^\s*(?P<fund>\d+)[_\-](?P<opis>[\w.]+?)\s*$"),
    re.compile(r"^\s*Ф\.?\s*(?P<fund>\d+)[_\s]*оп\.?\s*(?P<opis>[\w.]+?)(?:[_\s(]|$)", re.I),
    re.compile(r"^\s*Фонд\s*(?P<fund>\d+)\s*,?\s*опись\s*(?P<opis>[\w.]+)", re.I),
    # латиницей: «f4_op1», «f21_op2» (встречено на id 10, 24, 25, 26)
    re.compile(r"^\s*f\s*(?P<fund>\d+)[_\-\s]*op\s*(?P<opis>[\w.]+?)(?:[_\s(]|$)", re.I),
]
FIELDS_WANTED = ["№ описи", "Том описи", "Хронология", "Заголовок описи", "Тип описи",
                 "Категория", "Количество экземпляров", "Файлов", "МБ", "Доступ",
                 "Хар-ка секретности", "Движение", "Носитель", "Примечание"]


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
    return "pdf_unnamed"          # «259_1», «Фонд N, опись M» — у обоих оказался PDF


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", s))).strip()


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ru,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:    # noqa: S310
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as exc:                                        # noqa: BLE001
        return -1, f"{type(exc).__name__}"


def read_opis(oid: int) -> dict:
    """Снять описание описи одним GET. Сеть: один запрос."""
    status, body = fetch(OPIS_URL.format(id=oid))
    rec: dict = {"id": oid, "http": status}
    if status != 200 or not body:
        rec["error"] = body or f"http_{status}"
        return rec

    fields = {}
    for m in CAPTION_VALUE.finditer(body):
        cap, val = clean(m.group("cap")), clean(m.group("val"))
        if cap in FIELDS_WANTED and cap not in fields:
            fields[cap] = val
    rec["fields"] = fields
    rec["opis_title"] = next((clean(h) for h in H3.findall(body) if clean(h)), "")

    labels = FILE_LABEL.findall(body) or FILE_LABEL_ALT.findall(body)
    seen, uniq = set(), []
    for lab in labels:
        lab = html.unescape(lab).strip()
        if lab not in seen:
            seen.add(lab)
            uniq.append(lab)
    rec["scan_labels"] = uniq
    rec["files_count"] = len(uniq)
    rec["exists"] = bool(fields or rec["opis_title"])
    for lab in uniq:
        got = parse_scan_label(lab)
        if got:
            rec["fund"], rec["opis"] = got
            rec["scan_kind"] = label_kind(lab)
            break
    if uniq and "fund" not in rec:
        rec["scan_kind"] = label_kind(uniq[0])
        rec["label_unparsed"] = uniq[0]
    return rec


def grab_pdf_url(page) -> str | None:
    """Открыть превью первого файла и вернуть сессионный URL dynamiccontent."""
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
        }""")


def grab_image_urls(page, count: int) -> list[str]:
    """Серия образов: кликнуть каждое превью и снять URL картинки из background-image.

    Измерено на id=154 (ф. 228, 13 листов): в HTML страницы URL образов НЕТ, они приходят
    только JSF-postback'ом по клику. Доступна ТОЛЬКО watermark-версия
    `/thumbnails/upload/<a>/<b>/<hash>.JPG_watermark.jpg` (~170 КБ, 1471×2000) — оригинал
    `/upload/...` отдаёт 404. Качество проверено глазами: машинопись читается, водяной
    знак «ОГКУ ГАСО» полупрозрачный и Vision не мешает.
    """
    return page.evaluate(
        """async (n) => {
            const urls = [];
            for (let k = 0; k < n; k++) {
                const links = [...document.querySelectorAll('[id$="dataPreview_content"] a')];
                if (!links[k]) break;
                links[k].click();
                let got = null;
                for (let i = 0; i < 20; i++) {
                    await new Promise(r => setTimeout(r, 400));
                    const el = document.querySelector('[id$="previewPanel"] .scanImage');
                    if (el) {
                        const bg = getComputedStyle(el).backgroundImage || '';
                        const m = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                        if (m && !urls.includes(m[1])) { got = m[1]; break; }
                    }
                }
                urls.push(got);
                const close = document.querySelector('[id$="previewPanel"] .ui-sidebar-close');
                if (close) close.click();
                await new Promise(r => setTimeout(r, 600));
            }
            return urls;
        }""", count)


def download_in_page(page, url: str, dest: Path, expect: bytes = b"%PDF") -> dict:
    """Скачать файл в контексте страницы — куки сессии обязательны.

    `expect` — ожидаемая сигнатура начала файла: `%PDF` для описи-документа,
    `\\xff\\xd8` (JPEG SOI) для постраничного образа. Проверять надо именно тело:
    сервер отдаёт PDF с заголовком `content-type: video/quicktime`.
    """
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
    blob = base64.b64decode(res["b64"])
    dest.write_bytes(blob)
    return {"ok": blob.startswith(expect), "http": 200, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "head": res["head"][:8]}


def mode_probe(ids: list[int]) -> int:
    print(f"{'id':>6} {'http':>5} {'фонд':>6} {'оп.':>5} {'вид':>13} {'файлов':>7}  поля / подпись")
    for oid in ids:
        r = read_opis(oid)
        f = r.get("fields", {})
        print(f"{oid:>6} {str(r.get('http')):>5} {r.get('fund', '—'):>6} "
              f"{r.get('opis', '—'):>5} {r.get('scan_kind', '—'):>13} "
              f"{r.get('files_count', 0):>7}  "
              f"оп.{f.get('№ описи', '?')} · {f.get('Хронология', '?')} · "
              f"{(r.get('opis_title') or '')[:40]}")
        if r.get("scan_labels"):
            print(f"{'':>14}подписи: {r['scan_labels'][:3]}")
        time.sleep(DELAY)
    return 0


def mode_map(lo: int, hi: int, out: Path) -> int:
    state_f, map_f = out / "map_state.json", out / "opis_map.jsonl"
    start = lo
    if state_f.exists():
        start = json.loads(state_f.read_text(encoding="utf-8"))["next_id"]
        print(f"возобновление с id={start}")
    found, no_scan, absent, http_fail = 0, 0, 0, 0
    t0 = time.time()
    with map_f.open("a", encoding="utf-8") as fh:
        for oid in range(start, hi + 1):
            r = read_opis(oid)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            state_f.write_text(json.dumps({"next_id": oid + 1,
                                           "found": found, "stamp": time.strftime("%H:%M")}),
                               encoding="utf-8")
            if r.get("http") in (403, 429):
                http_fail += 1
                if http_fail >= HTTP_FAIL_STOP:
                    print(f"\nостановка: {http_fail} подряд HTTP {r['http']} на id={oid}")
                    return 2
            else:
                http_fail = 0
            if r.get("fund"):
                found += 1
                print(f"  id={oid}: ф.{r['fund']} оп.{r['opis']} "
                      f"{r.get('scan_kind')} ×{r['files_count']}")
            elif r.get("files_count"):
                found += 1
                print(f"  id={oid}: подпись не разобрана — {r.get('label_unparsed')!r}")
            elif r.get("exists"):
                no_scan += 1
            else:
                absent += 1
            if (oid - start + 1) % 100 == 0:
                el = time.time() - t0
                print(f"— {oid - start + 1} id за {el/60:.0f} мин; со сканом {found}, "
                      f"без скана {no_scan}, пусто {absent}")
            time.sleep(DELAY)
    print(f"\nитог: со сканом {found}, опись без скана {no_scan}, пустых {absent}")
    return 0


def mode_map_ids(ids: list[int], out: Path) -> int:
    """Карта по готовому списку id описей (маршрут через Электронный каталог).

    Пишет тот же `opis_map.jsonl`, что и `--map`, поэтому `--download` работает без правок.
    Повторный запуск дописывает только отсутствующие id — состояние берётся из самой карты.
    """
    map_f = out / "opis_map.jsonl"
    done = set()
    if map_f.exists():
        done = {json.loads(ln)["id"] for ln in map_f.open(encoding="utf-8") if ln.strip()}
        print(f"в карте уже {len(done)} описей, доберу остальные")
    with_scan, no_scan, absent = 0, 0, 0
    with map_f.open("a", encoding="utf-8") as fh:
        for oid in ids:
            if oid in done:
                continue
            r = read_opis(oid)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            if r.get("files_count"):
                with_scan += 1
                print(f"  id={oid}: ф.{r.get('fund', '?')} оп.{r.get('opis', '?')} "
                      f"{r.get('scan_kind')} ×{r['files_count']}")
            elif r.get("exists"):
                no_scan += 1
                print(f"  id={oid}: опись есть, скана НЕТ")
            else:
                absent += 1
                print(f"  id={oid}: пусто ({r.get('error', '?')})")
            time.sleep(DELAY)
    print(f"\nитог: со сканом {with_scan}, без скана {no_scan}, пустых {absent}")
    return 0


def mode_download(out: Path, funds: set[str]) -> int:
    rows = [json.loads(ln) for ln in (out / "opis_map.jsonl").open(encoding="utf-8")
            if ln.strip()]
    targets = [r for r in rows if r.get("fund") in funds]
    print(f"целевых описей по карте: {len(targets)} (фонды {sorted(funds)})")
    if not targets:
        return 1
    man_f = out / "manifest.json"
    manifest = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else []
    done = {m["id"] for m in manifest}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(60_000)
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
            tag = f"id={r['id']} ф.{r['fund']} оп.{r['opis']}"
            if r.get("scan_kind") == "image_series":
                # серия постраничных образов: по клику на каждое превью
                sub = out / f"{r['fund']}_{r['opis']}"
                sub.mkdir(parents=True, exist_ok=True)
                urls = grab_image_urls(page, r.get("files_count", 0))
                files = []
                for i, u in enumerate(urls, 1):
                    if not u:
                        files.append({"n": i, "ok": False, "reason": "no_url"})
                        continue
                    dest = sub / f"{i:04d}.jpg"
                    res = download_in_page(page, u, dest, expect=b"\xff\xd8")
                    files.append({"n": i, **res})
                ok = sum(1 for f in files if f.get("ok"))
                manifest.append({**r, "kind": "image_series", "dir": sub.name,
                                 "files": files, "downloaded_ok": ok,
                                 "page_url": OPIS_URL.format(id=r["id"])})
                print(f"  {tag}: образов {ok}/{len(urls)} → {sub.name}/")
            else:
                url = grab_pdf_url(page)
                if not url:
                    manifest.append({**r, "downloaded": False, "reason": "no_viewer_url"})
                    print(f"  {tag}: просмотрщик не открылся")
                else:
                    dest = out / f"{r['fund']}_{r['opis']}.pdf"
                    res = download_in_page(page, url, dest)
                    manifest.append({**r, "kind": "pdf", "file": dest.name,
                                     "page_url": OPIS_URL.format(id=r["id"]), **res})
                    print(f"  {tag}: {res.get('bytes', 0):,} б {res.get('head', '')}")
            man_f.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")
            time.sleep(DELAY)
        browser.close()
    return 0


def mode_reparse(out: Path) -> int:
    """Переразобрать подписи в уже собранной карте, не трогая сеть.

    Сырые подписи сохраняются в `opis_map.jsonl`, поэтому при встрече нового формата
    подписи достаточно дописать шаблон в SCAN_PATTERNS и прогнать этот режим.
    """
    src = out / "opis_map.jsonl"
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    changed = 0
    for r in rows:
        if r.get("fund") or not r.get("scan_labels"):
            continue
        for lab in r["scan_labels"]:
            got = parse_scan_label(lab)
            if got:
                r["fund"], r["opis"] = got
                r["scan_kind"] = label_kind(lab)
                r.pop("label_unparsed", None)
                changed += 1
                break
    with src.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    rest = [r for r in rows if r.get("files_count") and not r.get("fund")]
    print(f"переразобрано {changed}; осталось неразобранных {len(rest)}")
    for r in rest[:10]:
        print(f"  id={r['id']} {r.get('scan_labels')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", help="id через запятую — разведка без записи")
    ap.add_argument("--map", help="диапазон id вида 1-2600")
    ap.add_argument("--map-ids", dest="map_ids",
                    help="id описей через запятую — карта по списку из Электронного каталога")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--reparse", action="store_true",
                    help="переразобрать подписи в собранной карте, без сети")
    ap.add_argument("--funds", default="", help="номера фондов через запятую")
    ap.add_argument("--out", default=str(OUT_DEFAULT))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.probe:
        return mode_probe([int(x) for x in args.probe.split(",") if x.strip()])
    if args.reparse:
        return mode_reparse(out)
    if args.map_ids:
        return mode_map_ids([int(x) for x in args.map_ids.split(",") if x.strip()], out)
    if args.map:
        lo, hi = (int(x) for x in args.map.split("-"))
        return mode_map(lo, hi, out)
    if args.download:
        funds = {x.strip() for x in args.funds.split(",") if x.strip()}
        if not funds:
            print("нужен --funds")
            return 1
        return mode_download(out, funds)
    print("укажите --probe, --map, --map-ids или --download")
    return 1


if __name__ == "__main__":
    sys.exit(main())
