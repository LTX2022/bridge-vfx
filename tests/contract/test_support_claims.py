# -*- coding: utf-8 -*-
"""Support-claims gate: documented maturity must never exceed live evidence.

The verifier reports a single explicitly-labelled ``git_state_unavailable``
item in delivery trees without ``.git`` (HEAD re-verification is deferred
there, every other protection still runs).  That item is handled separately
here: a git tree must have ZERO violations, and a no-git tree must have
exactly the one labelled item and nothing else.  Faking a git repository or
deleting the protective comparisons is forbidden.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools" / "verify_support_claims.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("_bridge_support_claims", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load support-claims verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SupportClaimTests(unittest.TestCase):
    def test_documented_maturity_never_exceeds_live_evidence(self) -> None:
        verifier = _load_verifier()
        violations = verifier.violations()
        others = [v for v in violations if not v.startswith("git_state_unavailable")]
        self.assertEqual(others, [], "documented maturity must never exceed live evidence")

    def test_git_item_is_zero_or_single_labelled_deferral(self) -> None:
        verifier = _load_verifier()
        violations = verifier.violations()
        if (ROOT / ".git").exists():
            self.assertEqual(violations, [], "a git tree must fully verify against HEAD")
            return
        git_only = [v for v in violations if v.startswith("git_state_unavailable")]
        self.assertEqual(violations, git_only, "only the labelled git item may remain")
        self.assertEqual(len(git_only), 1, "git deferral must be exactly one labelled item")
        self.assertIn("deferred HEAD re-verification", git_only[0])


if __name__ == "__main__":
    unittest.main()
