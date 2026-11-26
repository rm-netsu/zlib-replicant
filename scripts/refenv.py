#!/usr/bin/env python3
"""Shared environment resolution for the zlib-replicant differential suites.

Every differential script in this directory locates its moving parts
through this module, so the suites work identically in two layouts:

  * the standalone package: `zig build` puts the tools into
    `<package>/zig-out/bin`, and the official reference wrappers are built
    into `<package>/binaries` by `binaries/build-references.sh`;
  * the enclosing zlib-fingerprint repository (this package is a path
    dependency there): the root `zig build` installs the package tools
    into the repository's `zig-out/bin`, and the reference wrappers live
    in the repository's `binaries/` (built by its `build-binaries.sh`,
    which delegates to this package's `build-references.sh`).

Resolution order (both cases): `$ZLIB_REF_BINARIES` if set, then the
enclosing repository's locations, then the package-local ones. Absent
reference wrappers produce an actionable error instead of a crash.
"""
import os
import pathlib
import sys

PKG = pathlib.Path(__file__).resolve().parent.parent
_PARENT = PKG.parent
# The parent directory is the zlib-fingerprint repository only when it
# looks like it (own build.zig.zon + a binaries directory); otherwise the
# package was extracted standalone and there is no repository fallback.
REPO = _PARENT if (_PARENT / "build.zig.zon").is_file() and (
    _PARENT / "binaries").is_dir() else None

RESULTS = PKG / "results"


def find_tool(name):
    """Path of a built tool (zcompress, zlegacy, ...), or None.

    The repository's zig-out wins in-repo (its `zig build` compiles the
    package tools as dependency artifacts); a standalone package falls
    back to its own zig-out.
    """
    for base in ([REPO, PKG] if REPO else [PKG]):
        path = base / "zig-out" / "bin" / name
        if path.is_file():
            return path
    return None


def tool(name):
    path = find_tool(name)
    if path is None:
        where = f"`zig build` in {PKG}"
        if REPO:
            where += f" (or the repository {REPO})"
        raise SystemExit(f"{name} not built: run {where}")
    return path


def _candidate_ref_dirs():
    env = os.environ.get("ZLIB_REF_BINARIES")
    if env:
        return [pathlib.Path(env)]
    dirs = []
    for base in ([REPO, PKG] if REPO else [PKG]):
        d = base / "binaries"
        # zlib-* must match stock-zlib wrappers only, not zlib-ng-<ver>.
        if any(p for p in d.glob("zlib-*")
               if not p.name.startswith("zlib-ng")):
            dirs.append(d)
    return dirs


def ref_dir():
    """Directory holding the official zlib-<ver> reference wrappers."""
    for d in _candidate_ref_dirs():
        return d
    hint = f"{PKG / 'binaries' / 'build-references.sh'}"
    if REPO:
        hint += f" (or {REPO / 'binaries' / 'build-binaries.sh'})"
    raise SystemExit(
        "no official zlib-<version> reference wrappers found; build them "
        f"with: bash {hint}")


def wrapper(version, prefix="zlib"):
    """Path of the official reference wrapper binary for a version."""
    return ref_dir() / f"{prefix}-{version}"


def vendor_dir():
    """Directory of vendored official zlib release sources (build inputs)."""
    for base in ([REPO, PKG] if REPO else [PKG]):
        d = base / "binaries" / "vendor"
        if d.is_dir() and any(p for p in d.glob("zlib-*")
                              if not p.name.startswith("zlib-ng")):
            return d
    return PKG / "binaries" / "vendor"


def results_dir():
    RESULTS.mkdir(exist_ok=True)
    return RESULTS


def output(name):
    """Default report path inside the package's results/ directory."""
    results_dir()
    return RESULTS / name
