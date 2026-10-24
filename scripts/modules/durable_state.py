"""Shared durable JSON checkpoint writer; v6 Windows-lock policy."""

import json
import os
import time
import uuid
from pathlib import Path

ATOMIC_RETRY_DELAYS = (0.05, 0.10, 0.20, 0.40, 0.40, 0.40, 0.40)


def decode_robots_text(body):
    """Decode a public robots.txt without rejecting unrelated legacy bytes."""
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("robots body must be bytes")
    return bytes(body).decode("utf-8-sig", errors="replace")


def _retryable_atomic_error(exc):
    return isinstance(exc, PermissionError) or (
        isinstance(exc, OSError) and getattr(exc, "winerror", None) in (5, 32)
    )


def _remove_own_temp(path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def atomic_json(path, value):
    path = Path(path)
    for attempt in range(len(ATOMIC_RETRY_DELAYS) + 1):
        tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with tmp.open("x", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            return
        except OSError as exc:
            _remove_own_temp(tmp)
            if not _retryable_atomic_error(exc) or attempt == len(ATOMIC_RETRY_DELAYS):
                raise
            time.sleep(ATOMIC_RETRY_DELAYS[attempt])
        except Exception:
            _remove_own_temp(tmp)
            raise
