import json
import unittest
from pathlib import Path


class BenchmarkTests(unittest.TestCase):
    def test_has_twenty_distinct_classic_cases(self):
        path = Path(__file__).parents[1] / "benchmarks" / "adversarial_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), 20)
        self.assertTrue(all(case.get("prompt") and case.get("checks") for case in cases))


if __name__ == "__main__":
    unittest.main()
