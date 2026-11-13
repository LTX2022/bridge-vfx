#!/usr/bin/env python3
"""Run the shipped media/cache/feedback integration contracts.

This is a software-boundary receipt generator.  Each readiness check is tied
to an executable repository test; no check is inferred from a filename or a
prewritten status value, and the suite never claims visual acceptance.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "packages/dcc-task-runtime/src",
    "packages/vfx-pipeline/src",
    "packages/houdini-bridge/src",
    "packages/nuke-bridge/src",
    "tests/unit",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from readiness_evidence import build_id  # noqa: E402


CHECKS = {
    "formal_media_tool": "test_media_formal_entry.FormalMediaEntryTests.test_actual_generated_media_video_and_frozen_metric_tools",
    "formal_sequence_metrics": "test_media_formal_entry.FormalMediaEntryTests.test_actual_generated_media_video_and_frozen_metric_tools",
    "runtime_budget_owned_stop": "test_controller_media.ControllerMediaTests.test_owned_budget_multiple_roots_cancel_once_and_unknown_never_release",
    "unknown_stop_retains_slot": "test_owned_cache_runner.OwnedCacheRunnerTests.test_native_write_failure_keeps_unknown_slot_and_does_not_retry_frame",
    "confirmed_stop_releases_slot": "test_owned_cache_runner.OwnedCacheRunnerTests.test_contiguous_history_segmented_under_one_owned_slot_and_hash_checked_output",
    "feedback_version_dependency_invalidation": "test_feedback_versions.FeedbackVersionTests.test_native_readback_versions_restart_and_scoped_invalidation",
    "cache_resource_confirmation": "test_cache_resource_contract.CacheResourceContractTests",
}


def _run(name: str) -> dict[str, object]:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    return {
        "test": name,
        "passed": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "output": stream.getvalue()[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = {key: _run(test_name) for key, test_name in CHECKS.items()}
    payload = {
        "schema": "bridge.full_readiness.media_integration/1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": build_id(ROOT),
        "checks": {
            key: bool(value["passed"] and value["tests_run"] > 0
                      and value["skipped"] == 0
                      and value["expected_failures"] == 0
                      and value["unexpected_successes"] == 0)
            for key, value in checks.items()
        },
        "evidence": checks,
        "model_called": False,
        "visual_acceptance_verified": False,
        "software_boundary_only": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(payload["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
