"""Compatibility re-export: the artifact ledger lives in the shared package."""
from dcc_task_runtime.artifact_registry import (  # noqa: F401
    ARTIFACT_CLASSES, ArtifactError, ArtifactRegistry, frame_path,
)

__all__ = ["ARTIFACT_CLASSES", "ArtifactError", "ArtifactRegistry", "frame_path"]
