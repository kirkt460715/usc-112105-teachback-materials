"""目标归并与评分异议规则测试。"""

import tempfile
import unittest
from pathlib import Path

from review.dataio import load_tables
from review.reconcile import resolve_task_cells
from tests.fixtures import build_fixture


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tables = load_tables(build_fixture(Path(self.temp.name) / "fx"))
        self.reconciled = resolve_task_cells(self.tables)

    def tearDown(self):
        self.temp.cleanup()

    def test_reviewed_disagreement_uses_decision(self):
        cell = self.reconciled.task_cells[("T009", "call-new-a")]
        self.assertEqual(cell.status, "reviewed")
        self.assertTrue(cell.understood)
        self.assertEqual(cell.review_id, "s1")

    def test_unresolved_disagreement_excluded_from_rate_inputs(self):
        # T002 是 C0 的 yue/old，夹具对其 call-old 追加了 P/Q 异判且无复核
        cell = self.reconciled.task_cells[("T002", "call-old")]
        self.assertEqual(cell.status, "unresolved")
        self.assertIsNone(cell.understood)
        result = self.reconciled.goal_results[("T002", "call")]
        self.assertIsNone(result.achieved)
        self.assertIn("call-old", result.unresolved_components)

    def test_call_new_requires_both_parts(self):
        # 合成数据里所有新版 call-new-b 为 False，因此 call 目标应全部未达成
        call_new = [
            result
            for (encounter, goal), result in self.reconciled.goal_results.items()
            if goal == "call" and "call-new-b" in result.components
        ]
        self.assertTrue(call_new)
        for result in call_new:
            self.assertFalse(result.achieved)
            self.assertEqual(result.rule, "all-parts")

    def test_each_goal_counted_once_per_encounter(self):
        counts: dict[tuple[str, str], int] = {}
        for encounter, goal in self.reconciled.goal_results:
            counts[(encounter, goal)] = counts.get((encounter, goal), 0) + 1
        self.assertTrue(counts)
        self.assertTrue(all(count == 1 for count in counts.values()))

    def test_single_task_goal_passthrough(self):
        result = self.reconciled.goal_results[("T000", "place")]
        self.assertTrue(result.achieved)
        self.assertEqual(result.components, ("place-old",))


if __name__ == "__main__":
    unittest.main()
