import os
import tempfile
import unittest

from backend.policy import WorkspacePolicy
from code_intelligence.indexer import CodeIndexer


class IndexerTests(unittest.TestCase):
    def test_indexes_python_symbols(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "main.py"), "w", encoding="utf-8") as handle:
                handle.write("class Service:\n    def run(self):\n        return 1\n")
            symbols = CodeIndexer(root, WorkspacePolicy(root)).build()
            names = {item["name"] for item in symbols}
            self.assertEqual(names, {"Service", "run"})

