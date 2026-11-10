"""The workers' progress messages (backends/shared/messages.py), the same for every model. No Blender."""
import os
import sys
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from backends.shared import messages  # noqa: E402


class TestMessages(unittest.TestCase):
    def test_wording(self):
        self.assertEqual(messages.loading("ARDY"), "Loading ARDY")
        self.assertEqual((messages.encoding(), messages.encoding(3)), ("Encoding the prompt", "Encoding the prompts"))
        self.assertEqual(messages.in_segment(messages.GENERATING, 0, 1), "Generating")
        self.assertEqual(messages.in_segment(messages.GENERATING, 1, 3), "Segment 2/3: generating")
        self.assertEqual(messages.in_segment(messages.POST_PROCESSING, 2, 3), "Segment 3/3: post-processing")

    def test_workers_use_them(self):
        """Neither worker words a progress message of its own"""
        for backend in ("kimodo", "ardy"):
            with open(os.path.join(REPO, "backends", backend, "worker.py"), encoding="utf-8") as f:
                source = f.read()
            for line in source.splitlines():
                if "context.progress(" in line:
                    self.assertNotIn('"', line.split("context.progress(", 1)[1], (backend, line))


if __name__ == "__main__":
    unittest.main()
