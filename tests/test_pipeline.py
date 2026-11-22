"""资料校验与端到端 CLI 测试。"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from review.dataio import DataError, load_tables
from run_review import main as cli_main
from tests.fixtures import build_fixture


class DataValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = build_fixture(self.root / "fx")

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_valid_fixture(self):
        tables = load_tables(self.data_dir)
        self.assertGreater(len(tables.dispatch), 0)
        self.assertGreater(len(tables.bridge_cases), 0)

    def test_rejects_duplicate_encounter(self):
        path = self.data_dir / "dispatch.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows.append(dict(rows[0]))
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "重复"):
            load_tables(self.data_dir)

    def test_rejects_score_with_unknown_task(self):
        path = self.data_dir / "scores.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows.append(
            {
                "score": "sc-bad",
                "encounter": rows[0]["encounter"],
                "task": "not-a-task",
                "assessor": "P",
                "understood": True,
                "received_on": "2026-10-17",
            }
        )
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        with self.assertRaises(DataError):
            load_tables(self.data_dir)


class CliEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_dir = build_fixture(self.root / "fx")
        self.out_dir = self.root / "out"

    def tearDown(self):
        self.temp.cleanup()

    def test_run_writes_all_outputs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(
                ["run", "--data", str(self.data_dir), "--output", str(self.out_dir),
                 "--review-date", "2026-11-22"]
            )
        self.assertEqual(code, 0)
        for name in ("review_packet.json", "review_report.md", "service_desk.jsonl"):
            self.assertTrue((self.out_dir / name).exists())
        packet = json.loads((self.out_dir / "review_packet.json").read_text(encoding="utf-8"))
        self.assertEqual(packet["review_date"], "2026-11-22")
        self.assertIn("channel_decisions", packet)
        desk_lines = (self.out_dir / "service_desk.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertTrue(desk_lines)
        for line in desk_lines:
            record = json.loads(line)
            self.assertIn("available_now", record)
            self.assertIn("evidence_refs", record)

    def test_lookup_returns_encounter(self):
        with redirect_stdout(io.StringIO()):
            cli_main(["run", "--data", str(self.data_dir), "--output", str(self.out_dir)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["lookup", "T014", "--output", str(self.out_dir)])
        self.assertEqual(code, 0)
        record = json.loads(buf.getvalue())
        self.assertEqual(record["actual_channel"], "new-old")

    def test_lookup_unknown_encounter_fails(self):
        with redirect_stdout(io.StringIO()):
            cli_main(["run", "--data", str(self.data_dir), "--output", str(self.out_dir)])
        with redirect_stderr(io.StringIO()):
            code = cli_main(["lookup", "NOPE", "--output", str(self.out_dir)])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
