#!/bin/bash
# Ночной цикл: перезапускает apply_auto_review.py --apply при каждом обрыве (OOM),
# пока ledger не покроет все 69650 решений. Резюмируется сам по ledger-файлу.
cd "D:/Yandex.Disk/History&Geography/БД/Поиск онлайн архив"
TARGET=69650
LEDGER="output/auto_review_candidates_full_apply_ledger.jsonl"
LOG="output/apply_loop_$(date +%Y%m%d_%H%M%S).log"

while true; do
  done_count=0
  if [ -f "$LEDGER" ]; then
    done_count=$(python3 -c "
import json
seen=set()
with open('$LEDGER', encoding='utf-8') as f:
    for line in f:
        line=line.strip()
        if not line: continue
        try:
            rec=json.loads(line)
        except Exception:
            continue
        if rec.get('status') in ('ok', 'already_archived'):
            seen.add(rec['page_id'])
print(len(seen))
")
  fi
  echo "$(date '+%H:%M:%S') уникальных ok: $done_count / $TARGET" >> "$LOG"
  if [ "$done_count" -ge "$TARGET" ]; then
    echo "$(date '+%H:%M:%S') ГОТОВО: $done_count / $TARGET" >> "$LOG"
    break
  fi
  python scripts/maintenance/apply_auto_review.py output/auto_review_candidates_full.tsv --apply >> "$LOG" 2>&1
  echo "$(date '+%H:%M:%S') процесс завершился/прерван, пауза 15с перед перезапуском" >> "$LOG"
  sleep 15
done
