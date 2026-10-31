"""Regression: TTL cleanup must never delete queued/running OCR job files.

Execute the actual cleanup_old_jobs function from app/main.py in isolation so
heavy OCR/FastAPI dependencies are not required for this filesystem contract.
"""
from __future__ import annotations

import ast
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


class FakeJobStore:
    def __init__(self, jobs):
        self.jobs = jobs
        self.removed = []

    def get(self, name):
        return self.jobs.get(name)

    def remove(self, name):
        self.removed.append(name)
        self.jobs.pop(name, None)


def isolated_cleanup(data_dir: Path, store: FakeJobStore):
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "cleanup_old_jobs"]
    if len(functions) != 1:
        raise AssertionError("Expected exactly one cleanup_old_jobs function")
    namespace = {
        "DATA_DIR": data_dir,
        "JOB_TTL_HOURS": 1,
        "job_store": store,
        "shutil": shutil,
        "time": time,
    }
    code = compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "app" / "main.py"), "exec")
    exec(code, namespace)
    return namespace["cleanup_old_jobs"]


class ActiveJobCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.jobs = {}
        self.store = FakeJobStore(self.jobs)

    def folder(self, name: str, *, stale=True):
        path = self.root / name
        path.mkdir()
        (path / "input.xlsx").write_bytes(b"unmodified user input")
        if stale:
            then = time.time() - 7200
            os.utime(path, (then, then))
        return path

    def test_running_job_survives_stale_directory_timestamp(self):
        path = self.folder("running")
        self.jobs["running"] = SimpleNamespace(status="running")
        isolated_cleanup(self.root, self.store)()
        self.assertTrue((path / "input.xlsx").is_file())
        self.assertNotIn("running", self.store.removed)

    def test_queued_job_survives_stale_directory_timestamp(self):
        path = self.folder("queued")
        self.jobs["queued"] = SimpleNamespace(status="queued")
        isolated_cleanup(self.root, self.store)()
        self.assertTrue(path.exists())
        self.assertNotIn("queued", self.store.removed)

    def test_completed_job_is_removed_after_ttl(self):
        path = self.folder("completed")
        self.jobs["completed"] = SimpleNamespace(status="completed")
        isolated_cleanup(self.root, self.store)()
        self.assertFalse(path.exists())
        self.assertIn("completed", self.store.removed)

    def test_failed_job_is_removed_after_ttl(self):
        path = self.folder("failed")
        self.jobs["failed"] = SimpleNamespace(status="failed")
        isolated_cleanup(self.root, self.store)()
        self.assertFalse(path.exists())
        self.assertIn("failed", self.store.removed)

    def test_recent_completed_job_is_retained(self):
        path = self.folder("recent", stale=False)
        self.jobs["recent"] = SimpleNamespace(status="completed")
        isolated_cleanup(self.root, self.store)()
        self.assertTrue(path.exists())
        self.assertNotIn("recent", self.store.removed)

    def test_expired_orphan_folder_is_removed(self):
        path = self.folder("orphan")
        isolated_cleanup(self.root, self.store)()
        self.assertFalse(path.exists())
        self.assertIn("orphan", self.store.removed)


    def test_disappearing_directory_between_type_and_timestamp_checks(self):
        """Concurrent cleanup can remove an entry after is_dir but before stat."""
        from unittest.mock import patch

        path = self.folder("vanished")
        self.jobs["vanished"] = SimpleNamespace(status="completed")
        original_stat = Path.stat
        calls = 0

        def racing_stat(candidate, *args, **kwargs):
            nonlocal calls
            if candidate == path:
                calls += 1
                if calls == 2:
                    raise FileNotFoundError("simulated concurrent directory removal")
            return original_stat(candidate, *args, **kwargs)

        with patch.object(Path, "stat", new=racing_stat):
            isolated_cleanup(self.root, self.store)()

        self.assertEqual(calls, 2)
        self.assertTrue((path / "input.xlsx").exists())
        self.assertNotIn("vanished", self.store.removed)



    def test_locked_expired_directory_keeps_job_state(self):
        """Windows locked-file deletion must not discard the job record."""
        from unittest.mock import patch
        path = self.folder("locked")
        self.jobs["locked"] = SimpleNamespace(status="completed")

        def simulated_locked_rmtree(target, *args, **kwargs):
            if kwargs.get("ignore_errors"):
                return None  # shutil.rmtree silently ignores permission errors
            raise PermissionError("simulated Windows file lock")

        with patch("shutil.rmtree", side_effect=simulated_locked_rmtree):
            isolated_cleanup(self.root, self.store)()

        self.assertTrue((path / "input.xlsx").exists())
        self.assertIn("locked", self.jobs)
        self.assertNotIn("locked", self.store.removed)

if __name__ == "__main__":
    unittest.main()
