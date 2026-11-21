import unittest
from datetime import date

from content_impact import Decision, DecisionLog


def _decision(ref, asset, state, day, reviewer="R-1", reason="reviewed_claim"):
    return Decision(ref, asset, state, date.fromisoformat(day), reviewer, reason)


class DecisionLogTests(unittest.TestCase):
    def test_effective_decision_is_latest(self):
        log = DecisionLog([
            _decision("D-1", "A-1", "restrict", "2026-01-03"),
            _decision("D-25", "A-1", "cleared", "2026-03-01", reviewer="R-9", reason="appeal_upheld"),
        ])
        self.assertEqual(log.effective("A-1").decision_ref, "D-25")

    def test_effective_decision_at_past_date(self):
        log = DecisionLog([
            _decision("D-1", "A-1", "restrict", "2026-01-03"),
            _decision("D-25", "A-1", "cleared", "2026-03-01"),
        ])
        self.assertEqual(log.effective("A-1", at=date(2026, 2, 1)).decision_ref, "D-1")
        self.assertEqual(log.effective("A-1", at=date(2026, 3, 1)).decision_ref, "D-25")

    def test_history_preserves_superseded_decisions(self):
        log = DecisionLog([
            _decision("D-25", "A-1", "cleared", "2026-03-01"),
            _decision("D-1", "A-1", "restrict", "2026-01-03"),
        ])
        self.assertEqual([d.decision_ref for d in log.history("A-1")], ["D-1", "D-25"])
        self.assertTrue(log.is_superseded(log.get("D-1")))
        self.assertFalse(log.is_superseded(log.get("D-25")))

    def test_missing_reviewed_at_sorts_earliest(self):
        log = DecisionLog([
            Decision("D-2", "A-1", "cleared", date(2026, 3, 1), "R-1", "appeal_upheld"),
            Decision("D-1", "A-1", "restrict", None, "R-1", "reviewed_claim"),
        ])
        self.assertEqual(log.effective("A-1").decision_ref, "D-2")

    def test_unknown_asset_has_no_effective_decision(self):
        log = DecisionLog([_decision("D-1", "A-1", "restrict", "2026-01-03")])
        self.assertIsNone(log.effective("A-2"))
        self.assertEqual(log.history("A-2"), ())


if __name__ == "__main__":
    unittest.main()
