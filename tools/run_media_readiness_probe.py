#!/usr/bin/env python3
"""Execute media contracts; require formal integration evidence for P4 PASS."""
from __future__ import annotations
import argparse
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for relative in ('packages/dcc-task-runtime/src', 'packages/vfx-pipeline/src',
                 'packages/houdini-bridge/src', 'packages/nuke-bridge/src', 'tests/unit'):
    sys.path.insert(0, str(ROOT / relative))
from readiness_evidence import build_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--integration-evidence', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_controller_media', 'test_media_readiness'])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    integration = {}
    if args.integration_evidence:
        integration = json.loads(args.integration_evidence.read_text())
    required = {'formal_media_tool', 'formal_sequence_metrics', 'runtime_budget_owned_stop',
                'unknown_stop_retains_slot', 'confirmed_stop_releases_slot',
                'feedback_version_dependency_invalidation', 'cache_resource_confirmation'}
    actual = integration.get('checks', {})
    integrated = (integration.get('build_id') == build_id(ROOT) and
                  all(actual.get(name) is True for name in required))
    receipt = {'schema': 'bridge.full_readiness.media_probe/2.0', 'build_id': build_id(ROOT),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'local_media_tests': {'run': result.testsRun, 'failures': len(result.failures),
                              'errors': len(result.errors), 'passed': result.wasSuccessful()},
        'formal_integration': integration,
        'missing_integration_checks': sorted(name for name in required if actual.get(name) is not True),
        'passed': result.wasSuccessful() and integrated,
        'model_called': False, 'visual_acceptance': False, 'software_boundary_only': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
