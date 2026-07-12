import sys
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("cv2", ModuleType("cv2"))

from scripts.pipeline import reports_to_output


EXPECTED_FIELDS = {
    "has_disease",
    "final_label",
    "confidence",
    "leaf_count",
    "scan_status",
    "summary",
    "leaves",
    "position_cm",
}


def make_report(label, stage1_conf=0.8, stage2_conf=None, bbox=None):
    if bbox is None:
        bbox = SimpleNamespace(x1=1, y1=2, x2=30, y2=40)
    stage1 = SimpleNamespace(avg_conf=stage1_conf, vote_ratio=1.0)
    stage2 = None
    if stage2_conf is not None:
        stage2 = SimpleNamespace(avg_conf=stage2_conf)
    return SimpleNamespace(
        final_label=label,
        stage1=stage1,
        stage2=stage2,
        bbox=bbox,
        n_detections=3,
    )


class PipelineOutputTest(unittest.TestCase):
    def assert_output_fields(self, output):
        self.assertEqual(EXPECTED_FIELDS, set(output))

    def test_no_leaf_detected(self):
        leaves, output = reports_to_output([], 12.5)

        self.assertEqual([], leaves)
        self.assert_output_fields(output)
        self.assertFalse(output["has_disease"])
        self.assertEqual("Uncertain", output["final_label"])
        self.assertEqual("uncertain", output["scan_status"])
        self.assertEqual(0, output["leaf_count"])
        self.assertEqual(12.5, output["position_cm"])

    def test_all_leaves_healthy(self):
        leaves, output = reports_to_output(
            [make_report("Healthy", 0.92), make_report("Healthy", 0.88)],
            10.0,
        )

        self.assertEqual(2, len(leaves))
        self.assert_output_fields(output)
        self.assertFalse(output["has_disease"])
        self.assertEqual("Healthy", output["final_label"])
        self.assertEqual("healthy", output["scan_status"])
        self.assertEqual({"Healthy": 2}, output["summary"])

    def test_only_uncertain_stays_uncertain(self):
        leaves, output = reports_to_output([make_report("Uncertain", 0.51)], 8.0)

        self.assertEqual(1, len(leaves))
        self.assert_output_fields(output)
        self.assertFalse(output["has_disease"])
        self.assertEqual("Uncertain", output["final_label"])
        self.assertEqual("uncertain", output["scan_status"])
        self.assertEqual({"Uncertain": 1}, output["summary"])

    def test_single_leafminer_leaf_is_diseased(self):
        leaves, output = reports_to_output(
            [make_report("LeafMiner", stage1_conf=0.72, stage2_conf=0.86)],
            24.0,
        )

        self.assertEqual(1, len(leaves))
        self.assert_output_fields(output)
        self.assertTrue(output["has_disease"])
        self.assertEqual("LeafMiner", output["final_label"])
        self.assertEqual("diseased", output["scan_status"])
        self.assertEqual(0.86, output["confidence"])

    def test_healthy_and_earlyblight_is_diseased(self):
        leaves, output = reports_to_output(
            [
                make_report("Healthy", stage1_conf=0.9),
                make_report("EarlyBlight", stage1_conf=0.7, stage2_conf=0.81),
            ],
            36.0,
        )

        self.assertEqual(2, len(leaves))
        self.assert_output_fields(output)
        self.assertTrue(output["has_disease"])
        self.assertEqual("EarlyBlight", output["final_label"])
        self.assertEqual("diseased", output["scan_status"])
        self.assertEqual({"Healthy": 1, "EarlyBlight": 1}, output["summary"])

    def test_multiple_disease_types_are_reported(self):
        leaves, output = reports_to_output(
            [
                make_report("LeafMiner", stage1_conf=0.7, stage2_conf=0.77),
                make_report("EarlyBlight", stage1_conf=0.8, stage2_conf=0.91),
            ],
            48.0,
        )

        self.assertEqual(2, len(leaves))
        self.assert_output_fields(output)
        self.assertTrue(output["has_disease"])
        self.assertEqual("LeafMiner (1), EarlyBlight (1)", output["final_label"])
        self.assertEqual("diseased", output["scan_status"])
        self.assertEqual(0.91, output["confidence"])
        self.assertEqual({"LeafMiner": 1, "EarlyBlight": 1}, output["summary"])


if __name__ == "__main__":
    unittest.main()
