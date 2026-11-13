#!/usr/bin/env python3
"""Explicit software HOM boundary for the supervised, shipped graph worker."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    expected = ROOT / 'packages/vfx-pipeline/src/vfx_pipeline/graph_job_worker.py'
    if (not arguments or not Path(arguments[0]).is_absolute()
            or Path(arguments[0]).is_symlink() or Path(arguments[0]).resolve() != expected.resolve()):
        raise ValueError('SOFTWARE_GRAPH_WORKER_PATH_INVALID')
    for package in ('dcc-task-runtime', 'houdini-bridge', 'nuke-bridge', 'vfx-pipeline'):
        sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))
    from vfx_pipeline import graph_job_worker as worker
    from vfx_pipeline.workbuddy_assembly import software_host_client
    if Path(worker.__file__).resolve() != expected.resolve():
        raise ValueError('SOFTWARE_GRAPH_WORKER_IMPORT_MISMATCH')
    original = worker.run_job

    def run_software_job(job):
        if (job.get('schema_version') != worker.PROTOCOL
                or job.get('validation_scope') != 'software_test'
                or Path(str(job.get('repo_root') or '')).resolve() != ROOT):
            raise ValueError('SOFTWARE_GRAPH_JOB_REQUIRED')
        _, addon = software_host_client(ROOT / 'plugins/houdini/_impl/houdini_bridge_addon.py',
            Path(job['result_path']).parent / 'software-native-api')
        return original(job, addon=addon)

    # Keep the worker's parser, evidence, journal, execution and sealing intact;
    # the existing addon dependency parameter carries only the fake HOM API.
    worker.run_job = run_software_job
    try:
        return worker.main(arguments[1:])
    finally:
        worker.run_job = original


if __name__ == '__main__':
    raise SystemExit(main())
