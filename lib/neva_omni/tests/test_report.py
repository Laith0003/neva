import re
import unittest
from pathlib import Path


def validate_prose(text):
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    prose = re.sub(r"`[^`]*`", "", prose)
    prose = re.sub(r"^\|[ :|\-]+\|$", "", prose, flags=re.M)
    if "\u2014" in prose or "--" in prose or re.search(r"[\U0001f300-\U0001faff]", prose):
        raise ValueError("report prose: remove em dashes, double hyphens and emojis")


class ReportWritingTest(unittest.TestCase):
    def test_report_writing_and_negative_controls(self):
        for bad in ("prose \u2014 aside", "prose -- aside", "prose \U0001f600"):
            with self.assertRaisesRegex(ValueError, "report prose"):
                validate_prose(bad)
        # The build report was a session note and no longer ships; the worker README is the
        # omni prose that does.
        root = Path(__file__).resolve().parents[3]
        validate_prose((root / "omni/worker/README.md").read_text())
