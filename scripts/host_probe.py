"""Проверка достижимости архивных хостов перед доборм.

Зачем: 09.11.2026 выяснилось, что ГАЯО отдаёт WAF-блок, а ГАПК недостижим — и это
меняет план добора. Прежде чем запускать длинные прогоны, нужно знать, куда вообще
есть доступ, и не выдавать недостижимое за «сделано».

Проверяет один дешёвый GET на каждый хост, печатает код/ошибку и признаки блокировки.

  python host_probe.py
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "defects" / "host_probe.json"

TARGETS = [
    ("РГИА", "https://fgurgia.ru/object/2471019079"),
    ("РГАДА", "http://rgada.info/"),
    ("НЭБ", "https://rusneb.ru/"),
    ("РГО", "https://elib.rgo.ru/handle/123456789/236729"),
    ("ГАСО-Урал описи", "https://opisi.gaso-ural.ru/"),
    ("ГАСО-Урал сайт", "https://gaso-ural.ru/"),
    ("ГАПК", "https://archives.permkrai.ru/"),
    ("ГАЯО", "https://af.yar-archives.ru/"),
    ("ГАСО-Смоленск", "https://portal.gaso-smolensk.ru/"),
    ("ГАКО", "https://archive.admoblkaluga.ru/"),
    ("Президентская б-ка", "https://www.prlib.ru/"),
    ("ГПИБ", "https://elib.shpl.ru/ru/nodes/9347"),
]
# ⚠️ Только ЯВНЫЕ фразы блокировки. Подстрока «captcha» в разметке — ложный признак:
# виджет reCAPTCHA стоит на формах входа у работающих сайтов (РГИА, РГО, ГАКО).
BLOCK_MARKS = (
    "Ваш запрос заблокирован",
    "Доступ запрещен",
    "Access denied",
    "Подтвердите, что вы не робот",
    "Request blocked",
)


def probe(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read(40000).decode("utf-8", "replace")
            marks = [m for m in BLOCK_MARKS if m.lower() in body.lower()]
            return {
                "ok": not marks,
                "code": r.status,
                "ms": int((time.time() - t0) * 1000),
                "bytes": len(body),
                "blocked_marks": marks,
            }
    except urllib.error.HTTPError as e:
        return {"ok": False, "code": e.code, "ms": int((time.time() - t0) * 1000),
                "err": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 — нужен любой сетевой сбой
        return {"ok": False, "code": None, "ms": int((time.time() - t0) * 1000),
                "err": f"{type(e).__name__}: {str(e)[:90]}"}


def main() -> None:
    fix_stdout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    res = {}
    for name, url in TARGETS:
        r = probe(url)
        res[name] = {"url": url, **r}
        mark = "✅" if r["ok"] else "⛔"
        tail = (
            f"код {r.get('code')}, {r['ms']} мс, {r.get('bytes', 0)} б"
            if r["ok"]
            else r.get("err") or f"код {r.get('code')}, метки {r.get('blocked_marks')}"
        )
        print(f"  {mark} {name:22s} {tail}")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = [k for k, v in res.items() if v["ok"]]
    print(f"\nдостижимо: {len(ok)} из {len(TARGETS)} → {', '.join(ok)}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
