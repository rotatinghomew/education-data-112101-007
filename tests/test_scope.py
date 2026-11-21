import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from content_impact import (
    Coverage,
    Dataset,
    Decision,
    DecisionLog,
    Requirement,
    analyze,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset.load(DATA)
        cls.result = analyze(cls.dataset)

    def assessment(self, result, placement_ref):
        return next(a for a in result.assessments if a.placement.placement_ref == placement_ref)

    def family(self, result, origin_ref):
        return next(f for f in result.families if f.origin_ref == origin_ref)

    def test_fixture_loads_without_issues(self):
        self.assertEqual(self.dataset.issues, ())

    def test_restrict_family_covers_same_claim_lineage(self):
        # A-1 被人工限制后，同谱系的 A-1/A-2 投放都进入处置范围
        family = self.family(self.result, "ROOT-1")
        by_ref = {p.placement.placement_ref: p for p in family.placements}
        self.assertEqual(set(by_ref), {"PL-1", "PL-2", "PL-3"})
        self.assertIs(by_ref["PL-1"].requirement, Requirement.REQUIRED)
        self.assertIs(by_ref["PL-1"].coverage, Coverage.COVERED)
        self.assertIs(by_ref["PL-2"].requirement, Requirement.RECOMMENDED)
        self.assertIs(by_ref["PL-2"].coverage, Coverage.OUTSTANDING)
        self.assertIs(by_ref["PL-3"].requirement, Requirement.RECOMMENDED)
        self.assertIs(by_ref["PL-3"].coverage, Coverage.GAP)
        self.assertTrue(by_ref["PL-3"].still_active)

    def test_recommendation_basis_is_human_decision(self):
        # 建议处置的依据是可追溯的人工结论，不是相似度本身
        pl3 = self.assessment(self.result, "PL-3")
        self.assertIs(pl3.requirement, Requirement.RECOMMENDED)
        self.assertEqual(pl3.basis.decision_ref, "D-1")
        self.assertEqual(pl3.basis.review_state, "restrict")

    def test_substantive_rewrite_not_auto_included(self):
        # 实质改写的 A-4 不自动并入 A-1 的处置范围，需单独复核
        family = self.family(self.result, "ROOT-1")
        self.assertEqual([a.asset_ref for a, _ in family.rewrites], ["A-4"])
        pl4 = self.assessment(self.result, "PL-4")
        self.assertIs(pl4.requirement, Requirement.NONE)

    def test_topic_similar_not_in_scope(self):
        # 仅主题相近的 A-5 不计入同一内容，其投放不在处置范围内
        family = self.family(self.result, "ROOT-1")
        self.assertEqual([a.asset_ref for a, _ in family.topic_adjacent], ["A-5"])
        self.assertNotIn("PL-5", {p.placement.placement_ref for p in family.placements})
        pl5 = self.assessment(self.result, "PL-5")
        self.assertIs(pl5.requirement, Requirement.NONE)

    def test_coverage_gap_visible_after_source_removed(self):
        # 源素材投放 PL-1 已撤下，但关联账号的 PL-2/PL-3 仍在传播：缺口必须可见
        gaps = {a.placement.placement_ref for a in self.result.gaps}
        self.assertIn("PL-2", gaps)
        self.assertIn("PL-3", gaps)
        self.assertNotIn("PL-1", gaps)
        active_gaps = {a.placement.placement_ref for a in self.result.gaps if a.still_active}
        self.assertEqual(active_gaps, {"PL-2", "PL-3"})

    def test_impact_links_sessions_exposures_and_orders(self):
        pl1 = self.assessment(self.result, "PL-1")
        self.assertEqual(pl1.placement.session_ref, "L-1")
        self.assertEqual(pl1.exposure_total, 800)
        self.assertEqual(len(pl1.orders), 2)
        self.assertEqual(pl1.order_total, Decimal("428.50"))

    def test_summary_counts(self):
        s = self.result.summary
        self.assertEqual(s["restrict_decisions"], 8)
        self.assertEqual(s["families"], 8)
        self.assertEqual(s["placements_in_scope"], 10)
        self.assertEqual((s["covered"], s["outstanding"], s["gap"]), (8, 1, 1))
        self.assertEqual(s["active_gaps"], 2)
        self.assertEqual(s["exposure_total_in_scope"], 3045)
        self.assertEqual(s["orders_in_scope"], 12)
        self.assertEqual(s["order_amount_in_scope"], Decimal("2305.50"))
        self.assertEqual(s["sessions_in_scope"], 6)
        self.assertEqual(s["sessions_fully_covered"], 4)
        self.assertEqual(s["unattributed_orders"], 2)

    def test_review_queue_prioritizes_lineage_of_restricted(self):
        queue = self.result.review_queue
        self.assertEqual(len(queue), 8)
        first = queue[0]
        self.assertEqual(first.asset.asset_ref, "A-2")
        self.assertEqual(first.exposure_total, 460)
        self.assertIn("A-1", first.note)
        # 队列按曝光量降序
        totals = [i.exposure_total or 0 for i in queue]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_pending_request_without_restrict_basis_is_listed(self):
        # A-4 仍为待复核：其未执行请求不构成处置要求，单独列出交人工确认
        unsupported = {m.action.action_ref for m in self.result.unsupported_pending}
        self.assertIn("AC-4", unsupported)
        self.assertEqual(self.result.withdrawals, ())

    def test_unattributed_orders_kept_separate(self):
        self.assertEqual(
            {o.order_ref for o in self.result.unattributed_orders}, {"O-27", "O-28"}
        )


class DecisionChangeTests(unittest.TestCase):
    """审核结论改变后：待处理范围与影响统计重算，历史措施及其依据保留。"""

    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset.load(DATA)
        cls.changed = analyze(
            cls.dataset,
            DecisionLog(
                list(cls.dataset.decisions)
                + [
                    Decision(
                        "D-25", "A-1", "cleared",
                        date(2026, 3, 1), "R-9", "appeal_upheld",
                    )
                ]
            ),
        )

    def assessment(self, result, placement_ref):
        return next(a for a in result.assessments if a.placement.placement_ref == placement_ref)

    def test_scope_recomputed_after_cleared(self):
        # ROOT-1 家族不再存在，相关投放不再要求处置
        self.assertNotIn("ROOT-1", {f.origin_ref for f in self.changed.families})
        for ref in ("PL-1", "PL-2", "PL-3"):
            self.assertIs(self.assessment(self.changed, ref).requirement, Requirement.NONE)
        s = self.changed.summary
        self.assertEqual(s["restrict_decisions"], 7)
        self.assertEqual(s["exposure_total_in_scope"], 3045 - 800 - 120 - 340)

    def test_unexecuted_recommendation_withdrawn(self):
        withdrawn = {m.action.action_ref for m in self.changed.withdrawals}
        self.assertIn("AC-2", withdrawn)  # PL-2 的未执行建议应撤回
        report = next(c for c in self.changed.cleared_reports if c.asset.asset_ref == "A-1")
        self.assertEqual([m.action.action_ref for m in report.withdrawals], ["AC-2"])

    def test_completed_measure_explained_with_basis(self):
        # 已执行的 AC-1 不撤销，可说明触达了哪些传播记录，依据是当时的 D-1
        report = next(c for c in self.changed.cleared_reports if c.asset.asset_ref == "A-1")
        self.assertEqual([m.action.action_ref for m in report.completed], ["AC-1"])
        measure = report.completed[0]
        self.assertEqual(measure.basis.decision_ref, "D-1")
        self.assertEqual(measure.basis.review_state, "restrict")
        self.assertTrue(measure.basis_superseded)
        self.assertEqual(measure.exposure_total, 800)
        self.assertEqual([e.exposure_ref for e in measure.exposures], ["X-1"])
        self.assertEqual(measure.order_total, Decimal("428.50"))

    def test_audit_retains_history(self):
        ac1 = next(m for m in self.changed.audit if m.action.action_ref == "AC-1")
        self.assertTrue(ac1.basis_superseded)
        self.assertEqual(ac1.asset_state, "cleared")
        # 其他已执行措施的依据未被取代
        ac6 = next(m for m in self.changed.audit if m.action.action_ref == "AC-6")
        self.assertFalse(ac6.basis_superseded)

    def test_original_result_unchanged(self):
        # 重算不影响基于原结论的分析结果
        original = analyze(self.dataset)
        self.assertEqual(original.summary["restrict_decisions"], 8)
        self.assertEqual(original.withdrawals, ())


if __name__ == "__main__":
    unittest.main()
