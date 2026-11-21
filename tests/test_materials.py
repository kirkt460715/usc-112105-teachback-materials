import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from inspect_inputs import read_tables


class MaterialTests(unittest.TestCase):
    def test_published_feed_can_be_read(self):
        data = Path(__file__).resolve().parents[1] / "data"
        tables = read_tables(data)
        for name, records in tables.items():
            with self.subTest(name=name):
                self.assertGreater(len(records), 0)

    def test_rejects_record_with_missing_column(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "manifest.json").write_text(json.dumps({"records": ["id"]}))
            (directory / "records.jsonl").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "第 1 行"):
                read_tables(directory)
