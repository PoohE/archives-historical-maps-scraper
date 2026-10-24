"""Offline v6 regressions for shared PRLIB state and robots infrastructure."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prlib_run_state as state


class AtomicJsonRetryTests(unittest.TestCase):
    def test_permission_error_retries_then_writes_final_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            original = state.os.replace
            calls = []
            def flaky(source, destination):
                calls.append((source, destination))
                if len(calls) < 3:
                    raise PermissionError(5, "locked")
                return original(source, destination)
            with patch.object(state.os, "replace", side_effect=flaky), patch.object(state.time, "sleep") as pause:
                state.atomic_json(target, {"ok": True, "attempt": 3})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"ok": True, "attempt": 3})
            self.assertEqual(len(calls), 3)
            self.assertEqual([call.args[0] for call in pause.call_args_list], [0.05, 0.10])
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_permission_error_beyond_limit_is_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            error = PermissionError(5, "locked")
            with patch.object(state.os, "replace", side_effect=error) as replace, patch.object(state.time, "sleep") as pause:
                with self.assertRaises(PermissionError) as caught:
                    state.atomic_json(target, {"ok": False})
            self.assertIs(caught.exception, error)
            self.assertEqual(replace.call_count, len(state.ATOMIC_RETRY_DELAYS) + 1)
            self.assertEqual(pause.call_count, len(state.ATOMIC_RETRY_DELAYS))
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_non_retryable_os_error_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            error = OSError(22, "invalid argument")
            with patch.object(state.os, "replace", side_effect=error) as replace, patch.object(state.time, "sleep") as pause:
                with self.assertRaises(OSError) as caught:
                    state.atomic_json(target, {"ok": False})
            self.assertIs(caught.exception, error)
            self.assertEqual(replace.call_count, 1)
            pause.assert_not_called()
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])