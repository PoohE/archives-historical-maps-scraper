import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output")
RES = Path(r"C:\Users\admin\AppData\Local\Temp\gpib_audit.txt")
lines = ["АУДИТ ДАННЫХ ГПИБ ПО ВСЕМ ПАПКАМ\n"]

files = []
for p in ROOT.rglob("*"):
    if not p.is_file() or p.suffix not in (".csv", ".jsonl"):
        continue
    if p.stat().st_size < 2000:
        continue
    try:
        head = p.open(encoding="utf-8-sig", errors="ignore").read(50_000)
    except Exception:
        continue
    if "gpib" in head or "shpl.ru" in head:
        files.append(p)

lines.append(f"файлов с данными ГПИБ: {len(files)}\n")
all_urls = set()
per_file = []
for p in files:
    urls = set()
    terr = Counter()
    try:
        if p.suffix == ".csv":
            for r in csv.DictReader(p.open(encoding="utf-8-sig", errors="ignore")):
                u = r.get("URL") or r.get("url") or ""
                if "shpl.ru" in u:
                    urls.add(u)
                    terr[r.get("Территория") or r.get("territory") or "?"] += 1
        else:
            for ln in p.open(encoding="utf-8", errors="ignore"):
                try:
                    j = json.loads(ln)
                except Exception:
                    continue
                rec = j.get("record") or j
                u = rec.get("url") or ""
                if "shpl.ru" in u:
                    urls.add(u)
                    terr[j.get("territory") or "?"] += 1
    except Exception:
        pass
    if urls:
        per_file.append((p, len(urls), dict(terr.most_common(4))))
        all_urls |= urls

per_file.sort(key=lambda x: -x[1])
lines.append(f"{'файл':<72} {'уник. URL':>9}")
for p, n, t in per_file[:25]:
    lines.append(f"{str(p.relative_to(ROOT))[:72]:<72} {n:>9}")
lines.append(f"\nВСЕГО УНИКАЛЬНЫХ URL ГПИБ ПО ВСЕМ ФАЙЛАМ: {len(all_urls)}")
lines.append(f"файлов с непустым ГПИБ: {len(per_file)}")
RES.write_text("\n".join(lines), encoding="utf-8")
print("готово, уникальных URL:", len(all_urls))
