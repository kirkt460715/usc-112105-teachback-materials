"""换版裁决、发行组合与服务台视图测试。"""

import tempfile
import unittest
from pathlib import Path

from review.comparability import evaluate_comparability
from review.dataio import load_tables
from review.decision import (
    ALLOW_NEW,
    CONTINUE_OLD,
    HOLD_EVIDENCE,
    MANUAL_HARMONIZE,
    decide_channels,
)
from review.evidence import build_evidence
from review.handoff import build_handoffs, build_service_desk, scope_summary
from review.reconcile import resolve_task_cells
from tests.fixtures import build_fixture

REVIEW_DATE = "2026-11-22"


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tables = load_tables(build_fixture(Path(self.temp.name) / "fx"))
        self.reconciled = resolve_task_cells(self.tables)
        self.comparability = evaluate_comparability(self.tables)
        self.bundle = build_evidence(self.tables, self.reconciled)
        self.decisions = decide_channels(
            self.tables, self.bundle, self.comparability, REVIEW_DATE
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_statuses(self):
        index = {(d.language, d.channel): d.status for d in self.decisions}
        self.assertEqual(index[("yue", "old-old")], MANUAL_HARMONIZE)
        self.assertEqual(index[("cmn", "old-old")], CONTINUE_OLD)
        self.assertEqual(index[("en", "old-old")], CONTINUE_OLD)
        # 夹具中新版 call 普遍失败且 yue 不可比，新组合全部暂缓
        for (language, channel), status in index.items():
            if channel != "old-old":
                self.assertEqual(status, HOLD_EVIDENCE)

    def test_no_offsetting_between_goals(self):
        cmn_new = next(d for d in self.decisions if d.language == "cmn" and d.channel == "new-new")
        failed = [check for check in cmn_new.goal_checks if not check.passed]
        passed = [check for check in cmn_new.goal_checks if check.passed]
        self.assertTrue(failed)
        self.assertTrue(passed)
        self.assertEqual(cmn_new.status, HOLD_EVIDENCE)

    def test_yue_call_blocker_is_comparability(self):
        yue_new = next(d for d in self.decisions if d.language == "yue" and d.channel == "new-new")
        call_check = next(check for check in yue_new.goal_checks if check.goal == "call")
        self.assertFalse(call_check.passed)
        self.assertTrue(any("不可比" in blocker for blocker in call_check.blockers))

    def test_followup_actions_name_people_and_checks(self):
        yue_new = next(d for d in self.decisions if d.language == "yue" and d.channel == "new-new")
        action_types = {action["type"] for action in yue_new.followup_actions}
        self.assertIn("re-contact", action_types)
        self.assertIn("adjudicate", action_types)
        self.assertIn("comparability", action_types)
        re_contacts = [a for a in yue_new.followup_actions if a["type"] == "re-contact"]
        self.assertTrue(any(a["encounter"] == "T013" for a in re_contacts))

    def test_banned_old_combo_kept_for_inflight_but_not_new_batches(self):
        yue_old = next(d for d in self.decisions if d.language == "yue" and d.channel == "old-old")
        self.assertTrue(yue_old.banned_for_new)
        handoffs = build_handoffs(self.tables, self.decisions, REVIEW_DATE)
        yue_handoff = next(h for h in handoffs if h.language == "yue")
        self.assertEqual(yue_handoff.continue_combo, "old-old")
        self.assertIn("不得向新批次", yue_handoff.note)

    def test_scope_summary_partitions_options(self):
        summary = scope_summary(self.decisions)
        total = sum(len(rows) for rows in summary.values())
        self.assertEqual(total, len(self.decisions))
        self.assertIn(ALLOW_NEW, summary)

    def test_service_desk_shows_actual_and_available(self):
        desk = build_service_desk(
            self.tables, self.reconciled, self.bundle, self.decisions, REVIEW_DATE
        )
        records = {record.encounter: record for record in desk}
        wrong = records["T014"]
        self.assertEqual(wrong.actual_channel, "new-old")
        self.assertTrue(any("wrong-material" in flag for flag in wrong.material_flags))
        self.assertTrue(wrong.available_now)
        self.assertIsNotNone(wrong.evidence_refs["channel_decision"])
        # 正常批次带目标级证据与评分编号
        normal = records["T000"]
        self.assertEqual(normal.actual_channel, "old-old")
        self.assertTrue(normal.evidence_refs["score_ids"])
        self.assertEqual(normal.evidence_refs["goal_results"]["place"]["achieved"], True)


if __name__ == "__main__":
    unittest.main()
