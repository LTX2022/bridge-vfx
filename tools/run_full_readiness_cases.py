#!/usr/bin/env python3
"""Replay readiness inventory through explicit diagnostic or prepared controllers.

Diagnostic clients never establish formal controller evidence. Production uses
one separately prepared controller per case and the generated server assembly;
missing configuration never falls back to a software host.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_HOUDINI_BUILDS = ("21.0.631", "22.0.459")
for relative in (
    "packages/vfx-pipeline/src",
    "packages/dcc-task-runtime/src",
    "packages/houdini-bridge/src",
    "packages/nuke-bridge/src",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from vfx_pipeline.domain_readiness import DomainReadinessRunner  # noqa: E402
from dcc_task_runtime.artifact_registry import ArtifactRegistry
from native_schema_test_boundary import constrain_hou
from readiness_evidence import build_id
from vfx_pipeline.workbuddy_assembly import (  # noqa: E402
    software_host_client,
    software_nuke_client,
    prepared_graph_facade,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="JSON receipt path")
    parser.add_argument("--output-root", type=Path, default=None,
                        help="task-owned save/output directory")
    parser.add_argument("--task-id", default="full-readiness-software")
    parser.add_argument("--backend", choices=("diagnostic", "production"), default="diagnostic")
    parser.add_argument("--prepared-projects", type=Path,
                        help="JSON mapping exact Houdini version and case ID to an existing prepared project")
    parser.add_argument("--software-processes", action="store_true",
                        help="explicit native API/process test boundary for prepared production controllers")
    args = parser.parse_args()
    if args.backend == "production" and args.prepared_projects is None:
        parser.error("production requires --prepared-projects; no software fallback is available")
    if args.backend != "production" and (args.prepared_projects or args.software_processes):
        parser.error("prepared projects and software processes require --backend production")
    return args


def prepared_case_factory(projects, version, *, allow_software_processes=False):
    """Select a controller prepared by prepare_workbuddy_graph for this case."""
    def create(*, case_id, domain, scenario):
        application = 'nuke' if domain == 'nuke_composite_v1' else 'pipeline'
        configured_version = '17.0v1' if application == 'nuke' else version
        raw = (projects.get(configured_version) or {}).get(case_id)
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError('FORMAL_CASE_CONFIG_REQUIRED: ' + configured_version + '/' + case_id)
        project = Path(raw).resolve()
        manifest = project / 'control/run.json'
        if not manifest.is_file() or not (project / 'control/snapshot-manifest.json').is_file():
            raise ValueError('FORMAL_CASE_CONFIG_REQUIRED: prepared manifest and snapshot are required')
        configured = json.loads(manifest.read_text())
        if application == 'nuke' and (configured.get('production_nuke') or {}).get('version') != '17.0v1':
            raise ValueError('FORMAL_CASE_VERSION_MISMATCH')
        if application != 'nuke' and (configured.get('production_host') or {}).get('version') != version:
            raise ValueError('FORMAL_CASE_VERSION_MISMATCH')
        return prepared_graph_facade(manifest, repo_root=project / 'control/snapshot',
            scheduler_root=project / 'scheduler', backend='production',
            allow_software_processes=allow_software_processes,application=application)
    return create


def main() -> int:
    args = _args()
    projects = json.loads(args.prepared_projects.read_text()) if args.prepared_projects else {}
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output_root = (args.output_root or output.with_name(output.stem + "-artifacts")).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bridge-full-readiness-state-") as state:
        state_root = Path(state).resolve()
        version_receipts = {}
        schema_path = ROOT / "docs/native-basis/hda-interface-capture.json"
        for houdini_version in REQUIRED_HOUDINI_BUILDS:
            version_key = houdini_version.replace(".", "_")
            version_root = state_root / ("houdini-" + version_key)
            version_output_root = output_root / ("houdini-" + version_key)
            version_task_id = args.task_id + "-houdini-" + version_key
            host = nuke = registry = factory = None
            native_schema = None
            if args.backend == "production":
                factory = prepared_case_factory(projects, houdini_version,
                    allow_software_processes=args.software_processes)
            else:
                os.environ["BRIDGE_SKILLS_STATE_ROOT"] = str(version_root / "installation")
                os.environ["BRIDGE_SKILLS_SCHEDULER_ROOT"] = str(version_root / "scheduler")
                os.environ["HOUDINI_BRIDGE_STATE_DIR"] = str(version_root / "houdini")
                host, _host_addon = software_host_client(
                    ROOT / "plugins" / "houdini" / "_impl" / "houdini_bridge_addon.py",
                    version_root / "host",
                )
                native_schema = constrain_hou(schema_path, version=houdini_version)
                nuke = software_nuke_client(
                    ROOT / "plugins" / "nuke" / "nuke_bridge_addon.py",
                    version_root / "nuke",
                    worker_script=ROOT / "tools" / "nuke_owned_render_worker.py",
                )
                registry = ArtifactRegistry(version_root / "artifact-ledger")
                nuke.bind_artifact_registry(registry)
                # The clients exercise shipped dispatch code but do not start a
                # DCC. Make that boundary explicit in every receipt.
                host.boundary_kind = "strict_fake_houdini_" + houdini_version
                nuke.boundary_kind = "strict_fake_nuke"
                prepare = getattr(host, "prepare_task", None)
                if callable(prepare):
                    prepare(version_task_id)
            version_receipt = DomainReadinessRunner(
                host_client=host,
                nuke_client=nuke,
                task_id=version_task_id,
                output_root=version_output_root,
                repo_root=ROOT,
                houdini_versions=(houdini_version,),
                artifact_registry=registry,
                case_facade_factory=factory,
            ).run_all()
            version_receipt.update({
                "houdini_version": houdini_version,
                "native_schema": native_schema,
                "software_boundary_only": args.backend == "diagnostic" or args.software_processes,
                "real_workbuddy_verified": False,
                "real_houdini_verified": False,
                "real_nuke_verified": False,
                "visual_acceptance_verified": False,
            })
            version_receipts[houdini_version] = version_receipt
        receipt = dict(version_receipts["21.0.631"])
        receipt["task_id"] = args.task_id
        receipt["houdini_versions"] = list(REQUIRED_HOUDINI_BUILDS)
        receipt["version_runs"] = version_receipts
        receipt["dual_version_gate"] = {
            "required_versions": list(REQUIRED_HOUDINI_BUILDS),
            "software_boundary_only": args.backend == "diagnostic" or args.software_processes,
            "all_cases_and_composites_passed": all(
                item.get("software_preparation_status") == "PASS"
                for item in version_receipts.values()
            ),
        }
    receipt.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "build_id": build_id(ROOT),
        "native_schema": native_schema,
        "software_boundary_only": args.backend == "diagnostic" or args.software_processes,
        "real_workbuddy_verified": False,
        "real_houdini_verified": False,
        "real_nuke_verified": False,
        "visual_acceptance_verified": False,
    })
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    statuses = [item.get("status") for item in receipt.get("cases", [])]
    composite_statuses = [item.get("status") for item in receipt.get("composites", [])]
    expected = receipt.get("case_count") == 48 and receipt.get("required_case_count") == 48
    expected = expected and receipt.get("required_composite_count") == 2
    expected = expected and all(value == "PASS" for value in statuses + composite_statuses)
    expected = expected and receipt.get("dual_version_gate", {}).get("all_cases_and_composites_passed") is True
    return 0 if expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
