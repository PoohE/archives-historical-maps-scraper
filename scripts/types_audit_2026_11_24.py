"""Выборочная проверка «Типа источника», уже стоящего в каталоге (поручение владельца 24.11.2026).

Повод: на проверке классификатора пачки 2 расхождения с каталогом оказались в основном ошибками
каталога («Геометрический специальный план … владения» с типом A2, планы городов с типом A1).

Схема: выборка, расслоённая по типу (до 20 на тип, у A3 и B8 по 40), только принятые записи,
не размеченные 24.11. Sonnet размечает вслепую (тип каталога не видит). Где ответ разошёлся
с каталогом, Opus судит: видит заголовок, оба варианта и типологию и выбирает «каталог»,
«модель» или «оба допустимы». Ошибка каталога — вердикт «модель».

  python scripts/types_audit_2026_11_24.py <слепок.csv>
Выход: output/types_audit_2026-11-24/{sample.jsonl, verdicts.csv, svodka.txt}
"""
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_for_upload import SYSTEM2, TYPOLOGY, answer_text, strip_fence  # noqa: E402
from types_batch2_2026_11_24 import CODES, body, item, snapshot  # noqa: E402
from common import anthropic_client, fix_stdout, load_env  # noqa: E402

SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
OUT = Path(__file__).resolve().parents[1] / "output" / "types_audit_2026-11-24"
JUDGE = """Ты эксперт по историческим географическим источникам XVIII — начала XX в.
Для каждой записи даны заголовок, держатель и два варианта типа: A — тип в каталоге,
B — тип, предложенный другой моделью. Типология каталога:
""" + TYPOLOGY + """

Реши для каждой записи, какой тип верен: "A" (каталог прав), "B" (прав вариант B),
"оба" (заголовок допускает оба), "ни один" (оба неверны — тогда укажи свой код в "code").
Отвечай ТОЛЬКО массивом JSON: [{"i": <номер>, "v": "A"|"B"|"оба"|"ни один", "code": "<код или пусто>",
"why": "<до десяти слов>"}]"""


def main() -> None:
    fix_stdout()
    snap = snapshot(sys.argv[1])
    today = set()
    for p in (Path(__file__).resolve().parents[1] / "output" / "fixes").glob("*types*.csv"):
        today |= {r["page_id"] for r in csv.DictReader(open(p, encoding="utf-8"))}
    by = defaultdict(list)
    for r in snap.values():
        if r["Статус приёмки"] == "принято" and r["Тип источника"] in CODES and r["page_id"] not in today:
            by[r["Тип источника"]].append(r)
    random.seed(20261124)
    sample = []
    for code, rs in sorted(by.items()):
        n = 40 if code in ("A3", "B8") else 20
        sample += random.sample(rs, min(n, len(rs)))
    pop = {c: len(v) for c, v in by.items()}
    items = [item(r) | {"cat": r["Тип источника"], "holder": r["Архив [авто]"]} for r in sample]
    load_env()
    client = anthropic_client()

    def ask(model: str, system: str, text: str) -> list:
        # битый JSON у модели бывает (24.11: 7 пачек из 130) — до трёх попыток, потом пусто
        for _ in range(3):
            msg = client.messages.create(model=model, max_tokens=6000, system=system,
                                         messages=[{"role": "user", "content": text}])
            try:
                return json.loads(strip_fence(answer_text(msg)))
            except json.JSONDecodeError:
                continue
        print("  ⚠️ три битых ответа подряд — порция пропущена")
        return []

    for k in range(0, len(items), 20):              # 1) Sonnet вслепую
        for a in ask(SONNET, SYSTEM2, body(items[k:k + 20], k)):
            items[int(a["i"])].update(model=a.get("code"), sure=bool(a.get("sure")))
    diff = [x for x in items if x.get("model") != x["cat"]]
    for k in range(0, len(diff), 15):               # 2) Opus судит расхождения
        chunk = diff[k:k + 15]
        text = "\n".join(f'{j}. ЗАГОЛОВОК: {x["title"]}\n   ДЕРЖАТЕЛЬ/ФОНД: {x["ctx"][:160]}\n'
                         f'   A: {x["cat"]}   B: {x.get("model")}' for j, x in enumerate(chunk))
        for a in ask(OPUS, JUDGE, text):
            chunk[int(a["i"])].update(verdict=a.get("v"), judge_code=a.get("code", ""), judge_why=a.get("why", ""))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sample.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
    with (OUT / "verdicts.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["page_id", "holder", "cat", "model", "sure", "verdict", "judge_code",
                                          "judge_why", "title"], extrasaction="ignore")
        w.writeheader()
        w.writerows(diff)
    lines = [f"выборка {len(items)} записей по {len(by)} типам; Sonnet совпал с каталогом в "
             f"{len(items) - len(diff)}; расхождений {len(diff)}: {dict(Counter(x.get('verdict') for x in diff))}",
             "тип | в каталоге | в выборке | ошибка каталога (B или «ни один») | доля"]
    est = 0.0
    for code in sorted(by, key=lambda c: -pop[c]):
        s = [x for x in items if x["cat"] == code]
        err = sum(1 for x in s if x.get("verdict") in ("B", "ни один"))
        share = err / len(s) if s else 0
        est += share * pop[code]
        lines.append(f"{code} | {pop[code]} | {len(s)} | {err} | {share:.0%}")
    lines.append(f"оценка ошибочно типизированных в каталоге: ~{est:.0f} из {sum(pop.values())}")
    (OUT / "svodka.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
