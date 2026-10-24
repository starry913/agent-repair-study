#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "swe_verified_claude4_traj"))

from scripts.profile_taxonomy_coverage import execute_outcome  # noqa: E402


class ExecuteOutcomeTest(unittest.TestCase):
    def test_zero_negative_counts_are_pass(self):
        self.assertEqual(
            execute_outcome(
                "Total: 78 passed, 0 failed, 0 errors", structured=True
            ),
            "pass",
        )

    def test_nonzero_failure_count_is_fail(self):
        self.assertEqual(
            execute_outcome("2 passed, 1 failed", structured=True), "fail"
        )

    def test_unstructured_prose_counts_are_unknown(self):
        self.assertEqual(
            execute_outcome("Test Results: 4/4 passed", "python custom_check.py"),
            "unknown",
        )

    def test_test_runner_exit_zero_is_pass(self):
        self.assertEqual(
            execute_outcome("completed with exit code 0", "python -m pytest tests/test_x.py"),
            "pass",
        )

    def test_diagnostic_exit_zero_is_unknown(self):
        self.assertEqual(
            execute_outcome("bug still reproduced; exit code 0", "python reproduce.py"),
            "unknown",
        )

    def test_diagnostic_explicit_failure_is_fail(self):
        self.assertEqual(
            execute_outcome("✗ FAILURE: expected 1, got 2", "python reproduce.py"),
            "fail",
        )

    def test_conflicting_custom_markers_are_unknown(self):
        self.assertEqual(
            execute_outcome(
                "✓ first check passed\n✗ second check failed",
                "python custom_check.py",
            ),
            "unknown",
        )

    def test_generic_success_word_is_not_pass(self):
        self.assertEqual(
            execute_outcome("setup completed successfully", "python inspect.py"),
            "unknown",
        )

    def test_nonzero_exit_is_fail(self):
        self.assertEqual(
            execute_outcome("completed with exit code 2", "python reproduce.py"),
            "fail",
        )


if __name__ == "__main__":
    unittest.main()
