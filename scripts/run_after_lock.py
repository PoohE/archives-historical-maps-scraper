"""Дождаться снятия чужого замка прогона и запустить свою команду.

Нужен потому, что перекрывающиеся прогоны записи в Notion уже давали лавину 429
(инцидент 09.11.2026: три фоновых процесса одновременно). Вместо ручного ожидания —
ждём освобождения конкретного замка и запускаем следующий шаг.

  python run_after_lock.py .series24.lock -- python year_provenance_fix.py --apply
"""

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLL = 30
MAX_WAIT = 6 * 3600


def main() -> int:
    if "--" not in sys.argv:
        sys.exit("нужно: run_after_lock.py <замок> -- <команда…>")
    i = sys.argv.index("--")
    locks = [HERE / x for x in sys.argv[1:i]]
    cmd = sys.argv[i + 1 :]
    if not cmd:
        sys.exit("команда не задана")

    waited = 0
    while True:
        busy = [p.name for p in locks if p.exists()]
        if not busy:
            break
        if waited >= MAX_WAIT:
            print(f"ждал {waited // 60} мин, замки всё ещё на месте: {busy} — выхожу", flush=True)
            return 2
        if waited % 600 == 0:
            print(f"ждём снятия: {', '.join(busy)} ({waited // 60} мин)", flush=True)
        time.sleep(POLL)
        waited += POLL

    print(f"замки сняты через {waited // 60} мин, запускаю: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(HERE))


if __name__ == "__main__":
    raise SystemExit(main())
