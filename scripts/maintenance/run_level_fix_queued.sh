#!/bin/bash
# Ждёт завершения текущего ночного цикла apply_auto_review (уникальных ok >= цели),
# затем применяет правку Административный уровень -> "Дача" для pid из dacha_level_fix_pids.txt
# (классификация 27-28.10.2026: наличие конкретного объекта уровня "дача" в названии).
cd "D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив"
LEDGER="output/auto_review_candidates_full_apply_ledger.jsonl"
TARGET=69650
PIDS="output/dacha_level_fix_pids.txt"
FIX_LEDGER="output/dacha_level_fix_pids_admin_level_ledger.jsonl"
LOG="output/level_fix_queue_$(date +%Y%m%d_%H%M%S).log"
FIX_TARGET=$(wc -l < "$PIDS")

count_unique_ok() {
  python3 -c "
import json
seen=set()
try:
    with open('$1', encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                rec=json.loads(line)
            except Exception:
                continue
            if rec.get('status') in ('ok', 'already_archived'):
                seen.add(rec['page_id'])
except FileNotFoundError:
    pass
print(len(seen))
"
}

echo "$(date '+%H:%M:%S') жду завершения apply_auto_review (цель=$TARGET уникальных)" >> "$LOG"
while true; do
  done_count=$(count_unique_ok "$LEDGER")
  if [ "$done_count" -ge "$TARGET" ]; then
    echo "$(date '+%H:%M:%S') apply_auto_review завершён ($done_count), запускаю правку уровня" >> "$LOG"
    break
  fi
  sleep 60
done

sleep 30
echo "$(date '+%H:%M:%S') цель правки уровня: $FIX_TARGET pid" >> "$LOG"
while true; do
  python scripts/maintenance/fix_admin_level_by_pid_list.py "$PIDS" "Дача" --apply >> "$LOG" 2>&1
  n=$(count_unique_ok "$FIX_LEDGER")
  echo "$(date '+%H:%M:%S') уникальных ok: $n / $FIX_TARGET" >> "$LOG"
  if [ "$n" -ge "$FIX_TARGET" ]; then
    echo "$(date '+%H:%M:%S') правка уровня ГОТОВО (уникальных=$n)" >> "$LOG"
    break
  fi
  echo "$(date '+%H:%M:%S') обрыв/неполно, пауза 15с, перезапуск" >> "$LOG"
  sleep 15
done
