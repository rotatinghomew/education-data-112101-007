import unittest
from pathlib import Path

from content_impact import ContentGraph, Dataset, RelationKind

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class ClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = Dataset.load(DATA)
        cls.graph = ContentGraph(cls.dataset.assets)

    def test_caption_change_is_same_claim_variant(self):
        # 同一来源、仅文案级改动：关键承诺未变，属于同一承诺谱系
        self.assertIs(self.graph.classify("A-1", "A-2"), RelationKind.SAME_CLAIM_VARIANT)
        self.assertIs(self.graph.classify("A-2", "A-1"), RelationKind.SAME_CLAIM_VARIANT)

    def test_claim_change_is_substantive_rewrite(self):
        # 改掉关键承诺的剪辑版本：实质改写，不自动并入原谱系
        self.assertIs(self.graph.classify("A-1", "A-4"), RelationKind.SUBSTANTIVE_REWRITE)
        self.assertIs(self.graph.classify("A-4", "A-1"), RelationKind.SUBSTANTIVE_REWRITE)

    def test_topic_similar_both_spellings_excluded(self):
        # similar_topic / topic_similar 两种写法都表示仅主题相近
        self.assertIs(self.graph.classify("A-1", "A-5"), RelationKind.TOPIC_SIMILAR_ONLY)
        self.assertIs(self.graph.classify("A-5", "A-1"), RelationKind.TOPIC_SIMILAR_ONLY)
        self.assertIs(self.graph.classify("A-6", "A-3"), RelationKind.TOPIC_SIMILAR_ONLY)

    def test_unrelated_origins(self):
        self.assertIs(self.graph.classify("A-1", "A-9"), RelationKind.UNRELATED)

    def test_segmentation_splits_on_claim_change(self):
        segment = self.graph.segment_of("A-1")
        self.assertIsNotNone(segment)
        self.assertEqual({m.asset_ref for m in segment.members}, {"A-1", "A-2"})
        self.assertFalse(segment.created_by_rewrite)

        rewrite_segment = self.graph.segment_of("A-4")
        self.assertIsNotNone(rewrite_segment)
        self.assertIsNot(rewrite_segment, segment)
        self.assertTrue(rewrite_segment.created_by_rewrite)
        self.assertEqual({m.asset_ref for m in rewrite_segment.members}, {"A-4"})

    def test_topic_adjacent_has_no_segment(self):
        self.assertIsNone(self.graph.segment_of("A-5"))
        self.assertTrue(self.graph.is_topic_adjacent("A-5"))
        self.assertFalse(self.graph.is_topic_adjacent("A-2"))

    def test_unknown_asset_raises(self):
        with self.assertRaises(ValueError):
            self.graph.classify("A-1", "A-999")


if __name__ == "__main__":
    unittest.main()
