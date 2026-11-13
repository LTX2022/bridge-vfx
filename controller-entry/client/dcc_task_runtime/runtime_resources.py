"""Locate Bridge runtime packages and their filesystem resources.

The repository has two supported source layouts:

* development checkouts keep a package at ``packages/<name>/src``;
* standalone Skill releases keep it at ``runtime/<name>/src``.

An installed Python package is used only as a final fallback.  The helpers
return real filesystem paths, so a package imported from a zip or another
non-filesystem importer is rejected instead of returning a path that cannot
be opened by a DCC-side caller.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Iterable


class ResourceLookupError(LookupError):
    """Raised when a runtime package or resource cannot be located safely."""


class ResourceOrigin(str, Enum):
    DEVELOPER = "developer"
    RELEASE = "release"
    INSTALLED = "installed"


_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class PackageLocation:
    """A resolved import package and the source root that contains it."""

    distribution_name: str
    module_name: str
    package_root: Path
    source_root: Path
    origin: ResourceOrigin

    def resource(self, relative_path: str | Path) -> Path:
        """Resolve one package resource without permitting path traversal."""

        return _resource_path(self.package_root, relative_path)

    def source_resource(self, relative_path: str | Path) -> Path:
        """Resolve one resource relative to the package's ``src`` root."""

        return _resource_path(self.source_root, relative_path)


def _module_name(distribution_name: str) -> str:
    if not isinstance(distribution_name, str) or not distribution_name or not _PACKAGE_NAME.fullmatch(distribution_name):
        raise ValueError("runtime package name contains unsupported characters")
    parts = distribution_name.replace("-", "_").split(".")
    if any(not part.isidentifier() for part in parts):
        raise ValueError("runtime package name must map to Python identifiers")
    return ".".join(parts)


def _candidate_module_root(source_root: Path, module_name: str) -> Path | None:
    candidate = source_root.joinpath(*module_name.split("."))
    if candidate.is_dir() and (candidate / "__init__.py").is_file():
        return candidate
    return None


def _search_roots(start: Path | str | None) -> tuple[Path, ...]:
    """Return deterministic ancestor roots for developer/release discovery."""

    values: list[Path] = []
    raw = Path(start).expanduser() if start is not None else Path.cwd()
    try:
        raw = raw.resolve()
    except OSError:
        raw = raw.absolute()
    if raw.is_file():
        raw = raw.parent
    for root in (raw, *raw.parents):
        if root not in values:
            values.append(root)
    return tuple(values)


def _source_candidates(roots: Iterable[Path], distribution_name: str, module_name: str) -> Iterable[tuple[Path, ResourceOrigin]]:
    for root in roots:
        developer_source = root / "packages" / distribution_name / "src"
        developer_package = _candidate_module_root(developer_source, module_name)
        if developer_package is not None:
            yield developer_package, ResourceOrigin.DEVELOPER

        release_source = root / "runtime" / distribution_name / "src"
        release_package = _candidate_module_root(release_source, module_name)
        if release_package is not None:
            yield release_package, ResourceOrigin.RELEASE


def _installed_package(distribution_name: str, module_name: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or spec.submodule_search_locations is None:
        return None
    locations = sorted((Path(location) for location in spec.submodule_search_locations), key=lambda path: str(path))
    for package_root in locations:
        if package_root.is_dir() and (package_root / "__init__.py").is_file():
            return package_root.resolve()
    return None


def locate_package(
    distribution_name: str,
    *,
    start: Path | str | None = None,
    allow_installed: bool = True,
) -> PackageLocation:
    """Locate one runtime package in developer, release, then installed form.

    ``start`` should be the caller's file or a directory in the checkout or
    release tree.  The search is ancestor-based and never treats an arbitrary
    child directory as a package root.  When ``start`` is omitted, the current
    working directory is used.
    """

    module_name = _module_name(distribution_name)
    for package_root, origin in _source_candidates(_search_roots(start), distribution_name, module_name):
        package_root = package_root.resolve()
        return PackageLocation(
            distribution_name=distribution_name,
            module_name=module_name,
            package_root=package_root,
            source_root=package_root.parent,
            origin=origin,
        )

    if allow_installed:
        package_root = _installed_package(distribution_name, module_name)
        if package_root is not None:
            return PackageLocation(
                distribution_name=distribution_name,
                module_name=module_name,
                package_root=package_root,
                source_root=package_root.parent,
                origin=ResourceOrigin.INSTALLED,
            )
    raise ResourceLookupError(f"runtime package is not available: {distribution_name}")


def _resource_path(root: Path, relative_path: str | Path) -> Path:
    if not isinstance(relative_path, (str, Path)):
        raise ValueError("resource path must be text or pathlib.Path")
    text = str(relative_path)
    if not text or "\\" in text or ":" in text:
        raise ValueError("resource path must be a non-empty POSIX relative path")
    raw_parts = text.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("resource path must not be absolute or traverse its root")
    requested = PurePosixPath(text)
    if requested.is_absolute() or any(part in {"", ".", ".."} for part in requested.parts):
        raise ValueError("resource path must not be absolute or traverse its root")
    root = root.resolve()
    target = (root / Path(*requested.parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("resource path escapes its root") from error
    if not target.is_file():
        raise ResourceLookupError(f"runtime resource is not a file: {relative_path}")
    return target


def locate_resource(
    distribution_name: str,
    relative_path: str | Path,
    *,
    start: Path | str | None = None,
    allow_installed: bool = True,
) -> Path:
    """Locate a resource inside the resolved import package."""

    return locate_package(distribution_name, start=start, allow_installed=allow_installed).resource(relative_path)


def locate_package_source(
    distribution_name: str,
    *,
    start: Path | str | None = None,
    allow_installed: bool = True,
) -> Path:
    """Return the source root (``.../src`` or installed site-packages root)."""

    return locate_package(distribution_name, start=start, allow_installed=allow_installed).source_root


# Small aliases keep call sites readable when they need a path rather than
# provenance details.  The richer ``locate_package`` result remains the
# canonical API.
def locate_runtime_package(
    distribution_name: str,
    *,
    start: Path | str | None = None,
    allow_installed: bool = True,
) -> Path:
    return locate_package(distribution_name, start=start, allow_installed=allow_installed).package_root


def locate_runtime_resource(
    distribution_name: str,
    relative_path: str | Path,
    *,
    start: Path | str | None = None,
    allow_installed: bool = True,
) -> Path:
    return locate_resource(distribution_name, relative_path, start=start, allow_installed=allow_installed)


__all__ = [
    "PackageLocation",
    "ResourceLookupError",
    "ResourceOrigin",
    "locate_package",
    "locate_package_source",
    "locate_resource",
    "locate_runtime_package",
    "locate_runtime_resource",
]
