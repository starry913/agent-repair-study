#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "RQ1"))

from extract_final_patches import lingxi_final_diff  # noqa: E402


class LingxiFinalDiffTest(unittest.TestCase):
    def test_extracts_all_files_from_last_final_block(self):
        text = """
diff --git a/intermediate.py b/intermediate.py
--- a/intermediate.py
+++ b/intermediate.py
@@ -1 +1 @@
-old
+intermediate

The final patch is:
diff --git a/first.py b/first.py
--- a/first.py
+++ b/first.py
@@ -1 +1 @@
-old
+new
diff --git a/second.py b/second.py
--- a/second.py
+++ b/second.py
@@ -1 +1 @@
-old2
+new2
</problem_solver 0>
"""
        patch = lingxi_final_diff(text)
        self.assertIn("diff --git a/first.py b/first.py", patch)
        self.assertIn("diff --git a/second.py b/second.py", patch)
        self.assertNotIn("intermediate.py", patch)
        self.assertNotIn("</problem_solver", patch)

    def test_uses_last_explicit_final_block(self):
        text = """
The final patch is:
diff --git a/old.py b/old.py
--- a/old.py
+++ b/old.py

Final patch:
diff --git a/new.py b/new.py
--- a/new.py
+++ b/new.py
"""
        patch = lingxi_final_diff(text)
        self.assertIn("new.py", patch)
        self.assertNotIn("old.py", patch)

    def test_returns_empty_without_explicit_final_block(self):
        self.assertEqual(
            lingxi_final_diff("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
