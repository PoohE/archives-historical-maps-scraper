"""Offline post-extraction scope audit for existing JSONL or CSV collections."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

import scope_gate


def records(path: Path):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), 1):
                simplified = {
                    "title": row.get("title") or row.get("Название источника") or "",
                    "description": row.get("description") or row.get("Описание") or "",
                    "url": row.get("url") or row.get("Ссылка на онлайн-архив") or "",
                }
                yield index, row, simplified
    else:
        for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.strip():
                value = json.loads(line)
                yield index, value, value


def reassess(source: Path, rules: Path, output: Path, source_name: str) -> dict:
    if output.exists():
        raise FileExistsError("Output exists; no overwrite")
    policy = scope_gate.load_policy(rules)
    output.mkdir(parents=True)
    counts = collections.Counter()
    paths = {name: output / (name + ".jsonl") for name in ("keep", "drops", "needs_human")}
    with (paths["keep"].open("x", encoding="utf-8") as keep,
          paths["drops"].open("x", encoding="utf-8") as drops,
          paths["needs_human"].open("x", encoding="utf-8") as review):
        for index, raw, record in records(source):
            verdict = scope_gate.check(record, source=source_name, amendments=policy)
            item = {"source": source_name, "input_row": index, "raw_record": raw,
                    "scope_verdict": verdict.asdict(),
                    "scope_drop_reason": verdict.reason if not verdict.keep else None}
            target = drops if not verdict.keep else review if verdict.needs_human else keep
            target.write(json.dumps(item, ensure_ascii=False) + "\n")
            counts["keep" if verdict.keep else verdict.reason] += 1
            if verdict.needs_human:
                counts["needs_human"] += 1
    report = {"source": source_name, "input": str(source),
              "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "rules_sha256": policy.rules_sha256, "counts": dict(counts),
              "input_rows": sum(1 for _ in records(source)), "network": "not_run",
              "ready_for_import": False}
    (output / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--source", required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reassess(args.input, args.rules, args.output, args.source), ensure_ascii=False))


if __name__ == "__main__":
    main()
