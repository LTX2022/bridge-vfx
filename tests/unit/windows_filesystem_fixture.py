"""Explicit filesystem metadata boundaries for Windows software fixtures."""

from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from dcc_task_runtime import platform_support
from vfx_pipeline import paths as approval_paths


@contextmanager
def fixture_denied_permissions(path: Path):
    if os.name != "nt":
        yield
        return
    validator = getattr(platform_support, "private_permissions_valid", None)
    if not callable(validator):
        raise RuntimeError("dependent_on_carson_helper: platform_support.private_permissions_valid unavailable")

    def denied_permissions(candidate, *args, **kwargs):
        if Path(candidate) == path:
            return False
        return validator(candidate, *args, **kwargs)

    with ExitStack() as boundary:
        boundary.enter_context(patch.object(platform_support, "private_permissions_valid", denied_permissions))
        if getattr(approval_paths, "private_permissions_valid", None) is validator:
            boundary.enter_context(patch.object(approval_paths, "private_permissions_valid", denied_permissions))
        yield


def fixture_private_permissions(path: Path):
    if os.name == "nt":
        platform_support.set_private_permissions(path)
    else:
        path.chmod(0o600)


def fixture_approval_environment(path: Path) -> dict[str, str]:
    return {"BRIDGE_SKILLS_APPROVAL_SECRET_FILE": str(path), "HOUDINI_BRIDGE_APPROVAL_SECRET": ""}


def fixture_symlink(case, link: Path, target: Path, *, target_is_directory=False) -> bool:
    with case.subTest(symlink=str(link)):
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                raise unittest.SkipTest("WinError 1314: symlink creation privilege unavailable") from error
            raise
        return True
    return False
