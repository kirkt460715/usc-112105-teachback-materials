"""证据汇总：分母口径、Wilson 区间、错发与漏访、批次计数测试。"""

import tempfile
import unittest
from pathlib import Path

from review.dataio import load_tables
from review.evidence import build_evidence, wilson_interval
from review.reconcile import resolve_task_cells
from tests.fixtures import build_fixture


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tables = load_tables(build_fixture(Path(self.temp.name) / "fx"))
        self.reconciled = resolve_task_cells(self.tables)
        self.bundle = build_evidence(self.tables, self.reconciled)

    def tearDown(self):
        self.temp.cleanup()

    def test_wilson_interval_bounds(self):
        low, high = wilson_interval(5, 10)
        self.assertLess(low, 0.5 < high)
        low0, high0 = wilson_interval(0, 0)
        self.assertEqual((low0, high0), (0.0, 0.0))

    def test_missing_followups_never_enter_rates(self):
        # pending T012 与 refused T013 只登记为缺口，不进入任何速率口径
        gap_encounters = {gap.encounter for gap in self.bundle.followup_gaps}
        self.assertEqual(gap_encounters, {"T012", "T013"})
        observed_total = sum(1 for row in self.tables.dispatch if row["followup"] == "observed")

        assigned_pooled = [
            r for r in self.bundle.rates if r.view == "assigned" and r.order is None
        ]
        exposure_pooled = [
            r for r in self.bundle.rates if r.view == "exposure" and r.order is None
        ]
        for rate in assigned_pooled + exposure_pooled:
            self.assertLessEqual(rate.observed, observed_total)
        # assigned 按 old/new 两侧互斥；每个语言 x 目标两侧合计等于该语言回访人数
        per_language_total: dict[str, int] = {}
        for row in self.tables.dispatch:
            if row["followup"] == "observed":
                per_language_total[row["language"]] = per_language_total.get(row["language"], 0) + 1
        for language, total in per_language_total.items():
            for goal in ("call", "return", "place"):
                goal_rates = [
                    r for r in assigned_pooled if r.goal == goal and r.language == language
                ]
                self.assertEqual(sum(r.observed for r in goal_rates), total)
        # exposure 按实际纸/口组合互斥；每个语言 x 目标在各渠道合计等于该语言回访人数
        for language, total in per_language_total.items():
            for goal in ("call", "return", "place"):
                goal_rates = [
                    r for r in exposure_pooled if r.goal == goal and r.language == language
                ]
                self.assertEqual(sum(r.observed for r in goal_rates), total)
        self.assertEqual(len(self.bundle.followup_gaps), 2)
        self.assertEqual(
            sorted(gap.kind for gap in self.bundle.followup_gaps),
            ["missing-pending", "missing-refused"],
        )

    def test_wrong_material_flagged_with_administered_edition(self):
        by_encounter = {item.encounter: item for item in self.bundle.wrong_materials}
        self.assertIn("T014", by_encounter)  # 新纸旧口，做新题
        self.assertEqual(by_encounter["T014"].administered_edition, "new")
        self.assertIn("T015", by_encounter)  # 旧纸新口，做旧题
        self.assertEqual(by_encounter["T015"].administered_edition, "old")

    def test_exposure_separates_mixed_channels(self):
        channels = {
            (r.language, r.channel)
            for r in self.bundle.rates
            if r.view == "exposure" and r.order is None
        }
        self.assertIn(("en", "new-old"), channels)
        self.assertIn(("cmn", "old-new"), channels)

    def test_small_and_empty_cells_are_flagged(self):
        # old-new 渠道只有 1 人；任何 0 分母单元必须标注不可估计而非当作 0%
        tiny = [
            r
            for r in self.bundle.rates
            if r.view == "exposure" and r.channel == "old-new" and r.order is None
        ]
        self.assertTrue(tiny)
        for rate in tiny:
            self.assertLessEqual(rate.observed, 1)
            if rate.known == 0:
                self.assertFalse(rate.estimable)

    def test_cluster_counts_exclude_missing_and_wrong_cells(self):
        mapping = {(item.language, item.side): item for item in self.bundle.cluster_counts}
        # C0/C1 完整；C2 有漏访/拒访/错发；C3 有错发
        cmn_old = mapping[("cmn", "old")]
        self.assertEqual(cmn_old.complete_clusters, 2)
        self.assertIn("C2", cmn_old.clusters_with_missing)
        cmn_new = mapping[("cmn", "new")]
        self.assertIn("C3", cmn_new.clusters_with_wrong_material)
        self.assertLess(cmn_new.complete_clusters, cmn_new.total_clusters)

    def test_conservative_rate_never_exceeds_main_rate(self):
        for rate in self.bundle.rates:
            if rate.estimable:
                self.assertLessEqual(rate.conservative_rate, rate.rate + 1e-12)


if __name__ == "__main__":
    unittest.main()
