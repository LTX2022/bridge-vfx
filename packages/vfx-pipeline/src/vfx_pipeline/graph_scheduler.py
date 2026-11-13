"""Compatibility re-export: the scheduler lives in the shared low-level package.

Standalone Houdini/Nuke installs ship ``dcc-task-runtime``; hosting the
installation-wide heavy-slot scheduler there keeps every adapter on the same
primitive without importing the orchestrator package.
"""
from dcc_task_runtime.graph_scheduler import GraphScheduler, SchedulerBusy  # noqa: F401

__all__ = ["GraphScheduler", "SchedulerBusy"]
