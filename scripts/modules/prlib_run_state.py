"""Durable per-query PRLIB state; offline-safe, no network implementation."""
import csv
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import registry
import searcher_libraries as lib

HASH_FIELDS=("parser_sha256","access_sha256","detail_sha256")
MIGRATION_CONTEXT=None

def configure_migration(accepted_prior_module_hashes, manifest_sha256):
    """Настроить единственный явно заверенный переход хешей для frozen runner."""
    global MIGRATION_CONTEXT
    if accepted_prior_module_hashes is None:
        MIGRATION_CONTEXT=None
        return
    if not isinstance(manifest_sha256,str) or len(manifest_sha256)!=64:
        raise ValueError("Invalid migration manifest hash")
    accepted=[]
    for hashes in accepted_prior_module_hashes:
        if not isinstance(hashes,dict) or set(hashes)!=set(HASH_FIELDS):
            raise ValueError("Invalid accepted prior module hashes")
        if any(not isinstance(hashes[name],str) or len(hashes[name])!=64 for name in HASH_FIELDS):
            raise ValueError("Invalid accepted prior module hash value")
        accepted.append({name:hashes[name] for name in HASH_FIELDS})
    MIGRATION_CONTEXT={"accepted":accepted,"manifest_sha256":manifest_sha256}

ATOMIC_RETRY_DELAYS=(0.05,0.10,0.20,0.40,0.40,0.40,0.40)

def _retryable_atomic_error(exc):
    return isinstance(exc,PermissionError) or (isinstance(exc,OSError) and getattr(exc,"winerror",None) in (5,32))

def _remove_own_temp(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

def atomic_json(path, value):
    """Записать JSON атомарно, переживая краткий Windows sharing lock."""
    path=Path(path)
    for attempt in range(len(ATOMIC_RETRY_DELAYS)+1):
        tmp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        try:
            with tmp.open("x",encoding="utf-8") as handle:
                json.dump(value,handle,ensure_ascii=False,indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp,path)
            return
        except OSError as exc:
            _remove_own_temp(tmp)
            if not _retryable_atomic_error(exc) or attempt==len(ATOMIC_RETRY_DELAYS):
                raise
            time.sleep(ATOMIC_RETRY_DELAYS[attempt])
        except Exception:
            _remove_own_temp(tmp)
            raise

def identity(source,territory,keyword,url):
    # Preserve query-specific provenance; collapse only PRLIB host variants.
    if source=="prlib":
        u=urlsplit(url)
        if u.scheme=="https" and u.netloc in ("prlib.ru","www.prlib.ru"):
            url="https://prlib.ru"+u.path.rstrip("/")
    return (source,territory,keyword,url)

def existing_outputs(run_dir):
    run_dir=Path(run_dir)
    files=[run_dir/n for n in ("records_full.jsonl","search_audit.csv","review.csv")]
    if not any(p.exists() for p in files):
        state_dir=run_dir/"prlib_query_state"
        if state_dir.exists() and any(state_dir.glob("*.json")):
            raise ValueError("Query state exists without result files; review before resume")
        return False,set()
    if not all(p.exists() for p in files):
        raise ValueError("Partial output file set; preserve files and review before resume")
    raw_keys=[]
    with files[0].open(encoding="utf-8") as handle:
        for line in handle:
            rec=json.loads(line) # malformed tail is not silently discarded
            raw_keys.append(identity(rec["source"],rec["territory"],rec["keyword"],rec["record"]["url"]))
    csv_keys=[]
    for path in files[1:]:
        with path.open(encoding="utf-8-sig",newline="") as handle:
            for row in csv.DictReader(handle):
                csv_keys.append(identity(row["Источник"],row["Территория"],row["Ключевое слово"],row["URL"]))
    from collections import Counter
    if Counter(raw_keys)!=Counter(csv_keys):
        raise ValueError("JSONL/CSV mismatch; preserve files and reconcile before resume")
    return True,set(raw_keys)

def query_path(run_dir,key):
    return Path(run_dir)/"prlib_query_state"/(hashlib.sha256(key.encode("utf-8")).hexdigest()+".json")

def expected_scope(key,query,year_from,year_to):
    return {"key":key,"query":query,"year_from":year_from,"year_to":year_to,
           "detail_mode":lib.PRLIB_FETCH_DETAILS_IN_BULK,
           "parser_sha256":hashlib.sha256(Path(lib.__file__).read_bytes()).hexdigest(),
           "detail_sha256":hashlib.sha256(Path(lib.__file__).with_name("prlib_card.py").read_bytes()).hexdigest(),
           "access_sha256":hashlib.sha256(Path(lib.__file__).with_name("prlib_access.py").read_bytes()).hexdigest(),
           "state_schema":2}

def _scope_migration(previous_scope,current_scope):
    """Вернуть запись миграции только для тройки, заверенной манифестом."""
    if not isinstance(previous_scope,dict) or set(previous_scope)!=set(current_scope):
        raise ValueError("Resume scope changed outside module hashes; use a new run directory")
    for field,value in current_scope.items():
        if field not in HASH_FIELDS and previous_scope[field]!=value:
            raise ValueError("Resume scope changed outside module hashes; use a new run directory")
    old_hashes={name:previous_scope[name] for name in HASH_FIELDS}
    new_hashes={name:current_scope[name] for name in HASH_FIELDS}
    if old_hashes==new_hashes:
        return None
    context=MIGRATION_CONTEXT or {}
    if old_hashes not in context.get("accepted",[]):
        raise ValueError("Resume module hash triple is not accepted by the manifest; use a new run directory")
    return {"from_hashes":old_hashes,"to_hashes":new_hashes,
            "utc":datetime.now(timezone.utc).isoformat(),
            "manifest_sha256":context["manifest_sha256"]}

def _read_and_migrate(path,scope):
    record=json.loads(path.read_text(encoding="utf-8"))
    migration=_scope_migration(record.get("scope"),scope)
    if migration:
        record["scope"]=scope
        record["migrations"]=list(record.get("migrations",[]))+[migration]
        atomic_json(path,record)
    return record

def completed_query(run_dir,key,year_from,year_to):
    path=query_path(run_dir,key)
    if not path.exists():return False
    territory,keyword,source=key.rsplit("|",2)
    record=_read_and_migrate(path,expected_scope(key,keyword+" "+territory,year_from,year_to))
    return record["coverage"].get("status")=="reported_end"

def iter_query(run_dir,key,query,year_from,year_to,max_pages,coverage):
    path=query_path(run_dir,key)
    path.parent.mkdir(exist_ok=True)
    scope=expected_scope(key,query,year_from,year_to)
    previous=_read_and_migrate(path,scope) if path.exists() else None
    if previous and previous["coverage"].get("status")=="reported_end":
        coverage.update(previous["coverage"])
        return
    resume=previous["coverage"].get("resume") if previous else None
    attempts = list(previous.get("previous_attempts", [])) if previous else []
    migrations = list(previous.get("migrations", [])) if previous else []
    if previous:
        attempts.append(previous["coverage"])
    def save(state):
        record={"scope":scope,"coverage":state,"previous_attempts":attempts}
        if migrations:
            record["migrations"]=migrations
        atomic_json(path,record)
    # Persist initial attempt, including failures before any result.
    coverage.update(status="starting",stop_reason="",full_search_complete=False,
                    resume=resume or {"page":0,"seen":[],"fingerprints":[]})
    save(coverage)
    iterator=registry.search("prlib",query,year_from=year_from,year_to=year_to,
                             max_pages=max_pages,coverage=coverage,resume=resume,on_progress=save)
    try:
        yield from iterator
    finally:
        iterator.close()
        save(coverage)
