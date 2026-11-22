"""锚点撤回与共同案例可比性测试。"""

import tempfile
import unittest
from pathlib import Path

from review.comparability import (
    ANCHOR_COMPARABLE,
    BRIDGE_ONLY,
    INCOMPARABLE,
    evaluate_comparability,
    remaining_comparison_scope,
)
from review.dataio import load_tables
from tests.fixtures import build_fixture


class ComparabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tables = load_tables(build_fixture(Path(self.temp.name) / "fx"))
        self.comparability = evaluate_comparability(self.tables)

    def tearDown(self):
        self.temp.cleanup()

    def test_withdrawal_with_divergent_bridge_is_incomparable(self):
        item = self.comparability[("yue", "call")]
        self.assertEqual(item.level, INCOMPARABLE)
        self.assertGreaterEqual(item.bridge_divergent, 1)
        self.assertEqual([w.notice for w in item.withdrawals], ["v1"])

    def test_untouched_anchor_remains_quantitative(self):
        for language in ("cmn", "yue", "en"):
            for goal in ("return", "place"):
                self.assertEqual(
                    self.comparability[(language, goal)].level,
                    ANCHOR_COMPARABLE,
                )
        self.assertEqual(self.comparability[("cmn", "call")].level, ANCHOR_COMPARABLE)

    def test_withdrawal_without_divergence_is_bridge_only(self):
        # 在夹具上撤回 cmn place，且其 bridge 无分歧
        tables = self.tables
        rows = list(tables.anchor_changes)
        rows = rows + (
            type(rows)([
                {
                    "notice": "v9",
                    "language": "cmn",
                    "task": "place-new",
                    "applied_on": "2026-10-25",
                    "kind": "withdraw",
                }
            ])
        )
        tables = type(tables)(
            tables.dispatch,
            tables.scores,
            tables.targets,
            tuple(rows),
            tables.review_floors,
            tables.release_options,
            tables.active_wards,
            tables.bridge_cases,
            tables.scorer_reviews,
        )
        item = evaluate_comparability(tables)[("cmn", "place")]
        self.assertEqual(item.level, BRIDGE_ONLY)
        self.assertEqual(item.bridge_divergent, 0)

    def test_remaining_scope_lists_levels(self):
        scope = remaining_comparison_scope(self.tables)
        self.assertIn(INCOMPARABLE, scope)
        self.assertIn(ANCHOR_COMPARABLE, scope)
        self.assertEqual(
            {(row["language"], row["goal"]) for row in scope[INCOMPARABLE]},
            {("yue", "call")},
        )


if __name__ == "__main__":
    unittest.main()
