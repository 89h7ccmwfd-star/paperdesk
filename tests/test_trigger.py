"""Der Cloudflare-Ausloeser (trigger/worker.js) muss denselben Boersenkalender haben wie der Bot."""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from paperdesk import config  # noqa: E402


def js_set(name):
    with open(os.path.join(ROOT, "trigger", "worker.js"), encoding="utf-8") as f:
        src = f.read()
    body = re.search(rf"{name} = new Set\(\[(.*?)\]\)", src, re.S).group(1)
    return set(re.findall(r'"(\d{4}-\d{2}-\d{2})"', body))


class TriggerCalendarTests(unittest.TestCase):
    def test_holidays_match(self):
        self.assertEqual(js_set("HOLIDAYS"), config.HOLIDAYS)

    def test_early_close_match(self):
        self.assertEqual(js_set("EARLY_CLOSE"), config.EARLY_CLOSE)


if __name__ == "__main__":
    unittest.main()
