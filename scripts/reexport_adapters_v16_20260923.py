"""Offline v1.6 re-layout of preserved archive candidate JSONL; no network."""
from __future__ import annotations
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/modules"))
import notion_export

OUT = ROOT / "output/adapters_v16_relayout_20260923_v2"
INPUTS = {
    "prlib": ROOT / "output/prlib_catalog_full_20260917_v1/records_full.jsonl",
    "rgada": ROOT / "output/rgada_catalog_full_20260922_v3/records_full.jsonl",
    "rgia": ROOT / "output/rgia_catalog_full_20260923_v1/records_full.jsonl",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_stats(path: Path) -> dict:
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    return {"input_rows": len(entries), "unique_urls": len({x["record"].get("url", "") for x in entries})}


def csv_coverage(path: Path) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {"rows": len(rows), "columns": len(rows[0]) if rows else len(notion_export.FIELDS),
            "nonempty_by_field": {field: sum(bool((row.get(field) or "").strip()) for row in rows)
                                  for field in notion_export.FIELDS}}


def main() -> None:
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite " + str(OUT))
    OUT.mkdir()
    report = {"task": "offline adapter v1.6 re-layout", "network": "not_run",
              "ready_for_import": False, "schema_version": notion_export.SCHEMA["version"],
              "schema_sha256": sha(ROOT / "scripts/modules/notion_schema.json"),
              "sources": {}}
    for name, source in INPUTS.items():
        before = source.read_bytes()
        target = OUT / name
        exported = notion_export.export(source, target)
        if source.read_bytes() != before:
            raise ValueError("source JSONL changed: " + str(source))
        report["sources"][name] = {"input_path": str(source), "input_sha256": sha(source),
                                    **input_stats(source), "export": {k: exported[k] for k in ("rows", "columns", "roundtrip")},
                                    "coverage": csv_coverage(target / "notion_import.csv")}
    (OUT / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"rows": data["export"]["rows"], "columns": data["export"]["columns"]}
                      for name, data in report["sources"].items()}, ensure_ascii=False))

if __name__ == "__main__":
    main()
