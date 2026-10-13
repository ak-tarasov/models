import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import watch


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "inbox"
        self.dir.mkdir()
        self.sent = []
        env = {"WATCH_DIR": str(self.dir), "WATCH_WAIT": "0", "WATCH_MONTH_LIMIT": "2"}
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(watch, "STATE", Path(self.tmp.name) / "state.json"),
                  mock.patch.object(watch, "notify", lambda text, link=None: self.sent.append((text, link))),
                  mock.patch.object(watch.cf, "add", lambda urn, name, view=None: f"https://x/m/{urn}")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def put(self, name, age=1000):
        p = self.dir / name
        p.write_bytes(b"x" * 10)
        os.utime(p, (time.time() - age, time.time() - age))
        return p

    def run_pass(self, status="success", upload=None):
        up = upload or mock.Mock(side_effect=lambda path: {"urn": "u-" + Path(path).stem})
        with mock.patch.object(watch.aps, "upload", up), \
             mock.patch.object(watch.aps, "manifest", lambda urn: {"status": status}):
            try:
                watch.run()
                code = 0
            except SystemExit as e:
                code = e.code
        return up, code

    def test_new_model_is_published_once(self):
        self.put("Дом.rvt")
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 1)
        self.assertEqual(self.sent[0][1], "https://x/m/u-Дом")
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 0)
        self.assertEqual(len(self.sent), 1)

    def test_pending_finishes_on_a_later_pass(self):
        self.put("a.rvt")
        self.run_pass(status="inprogress")
        self.assertEqual(self.sent, [])
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 0)
        self.assertIn("выложена", self.sent[0][0])

    def test_fresh_and_foreign_files(self):
        self.put("new.rvt", age=5)
        self.put("plan.pdf")
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 0)
        self.assertIn("пропущен", self.sent[0][0])
        self.run_pass()
        self.assertEqual(len(self.sent), 1)

    def test_month_limit(self):
        for n in "abc":
            self.put(n + ".rvt")
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 2)
        self.assertEqual(sum("не выложена" in t for t, _ in self.sent), 1)
        up, _ = self.run_pass()
        self.assertEqual(up.call_count, 0)
        with mock.patch.object(watch.time, "strftime", lambda fmt: "2099-01"):
            up, _ = self.run_pass()
        self.assertEqual(up.call_count, 1)

    def test_upload_error_retries_then_gives_up(self):
        self.put("a.rvt")
        boom = mock.Mock(side_effect=SystemExit("PUT -> 500"))
        for _ in range(4):
            _, code = self.run_pass(upload=boom)
        self.assertEqual(boom.call_count, watch.MAX_TRIES)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(watch.load_state()["used"], {})

    def test_failed_translation(self):
        self.put("a.rvt")
        self.run_pass(status="failed")
        self.assertIn("не удалось", self.sent[0][0])


if __name__ == "__main__":
    unittest.main()
