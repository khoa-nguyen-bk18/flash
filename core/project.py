#!/usr/bin/env python3
"""
Multi-platform project detection (Android, Native Xcode, and Kotlin Multiplatform - KMP)
and active platform resolution.
Zero external dependencies.
"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional

from . import ui


class ProjectType(str, Enum):
    ANDROID = "android"
    XCODE = "xcode"
    KMP = "kmp"
    UNKNOWN = "unknown"


_IGNORED_DIRS = frozenset({
    ".git", ".gradle", ".flash", ".idea", "build", "DerivedData",
    "Pods", "Carthage", "node_modules", ".build", "__pycache__",
})

_IOS_SUBDIR_CANDIDATES = ("iosApp", "ios", "iOS", "apple", "Apple", "Darwin", "darwin")
_ANDROID_SUBDIR_CANDIDATES = ("androidApp", "android", "app")


@dataclass
class ProjectContext:
    root: Path
    start_dir: Path
    project_type: ProjectType
    has_android: bool = False
    has_ios: bool = False
    xcode_workspace: Optional[Path] = None
    xcode_project: Optional[Path] = None
    all_xcode_entries: List[Path] = field(default_factory=list)
    ios_dir: Optional[Path] = None
    podfile: Optional[Path] = None
    is_kmp: bool = False
    kmp_shared_modules: List[str] = field(default_factory=list)

    @property
    def active_xcode_path(self) -> Optional[Path]:
        """Prefer .xcworkspace over .xcodeproj when both exist."""
        return self.xcode_workspace or self.xcode_project

    @property
    def is_workspace(self) -> bool:
        return self.xcode_workspace is not None


def _has_gradle_root(directory: Path) -> bool:
    return (
        (directory / "settings.gradle.kts").is_file()
        or (directory / "settings.gradle").is_file()
        or (directory / "gradlew").is_file()
    )


def _list_xcode_in_dir(directory: Path) -> List[Path]:
    """List valid .xcworkspace and .xcodeproj entries directly inside `directory`."""
    if not directory.is_dir():
        return []

    workspaces: List[Path] = []
    projects: List[Path] = []
    try:
        for entry in sorted(directory.iterdir()):
            name = entry.name
            if name in _IGNORED_DIRS or name.startswith("."):
                continue
            if name.endswith(".xcworkspace") and entry.is_dir():
                if name == "project.xcworkspace":
                    continue
                workspaces.append(entry)
            elif name.endswith(".xcodeproj") and entry.is_dir():
                if name == "Pods.xcodeproj":
                    continue
                projects.append(entry)
    except OSError:
        pass
    return workspaces + projects


def find_xcode_entries(search_root: Path) -> List[Path]:
    """
    Discover valid .xcworkspace / .xcodeproj bundles in `search_root`
    and standard KMP/iOS subdirectories (iosApp/, ios/, apple/, etc.).
    Workspaces are ordered before projects within each directory.
    """
    entries: List[Path] = []
    seen = set()

    def _add(paths: List[Path]):
        for p in paths:
            rp = p.resolve()
            if rp not in seen:
                seen.add(rp)
                entries.append(rp)

    # 1. Direct children of root
    _add(_list_xcode_in_dir(search_root))

    # 2. Well-known iOS/KMP subdirectories
    for sub in _IOS_SUBDIR_CANDIDATES:
        sub_dir = search_root / sub
        if sub_dir.is_dir():
            _add(_list_xcode_in_dir(sub_dir))

    # 3. Fallback: scan 1 level deep for any other subdirectory containing Xcode project
    if not entries:
        try:
            for child in sorted(search_root.iterdir()):
                if not child.is_dir() or child.name in _IGNORED_DIRS or child.name.startswith("."):
                    continue
                if child.name.endswith((".xcodeproj", ".xcworkspace")):
                    continue
                _add(_list_xcode_in_dir(child))
        except OSError:
            pass

    return entries


def _detect_kmp_shared_modules(root: Path) -> List[str]:
    """Inspect settings.gradle(.kts) and module build files to identify KMP modules."""
    kmp_modules: List[str] = []
    settings_candidates = [root / "settings.gradle.kts", root / "settings.gradle"]
    module_names: List[str] = []

    for sf in settings_candidates:
        if sf.is_file():
            try:
                content = sf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'["\'](:[a-zA-Z0-9_\-:]+)["\']', content):
                    mod = m.group(1)
                    if mod not in module_names:
                        module_names.append(mod)
            except OSError:
                pass
            break

    for mod in module_names:
        mod_dir = root / mod.lstrip(":").replace(":", os.sep)
        for bf_name in ("build.gradle.kts", "build.gradle"):
            bf = mod_dir / bf_name
            if bf.is_file():
                try:
                    txt = bf.read_text(encoding="utf-8", errors="ignore")
                    if (
                        "multiplatform" in txt
                        or "iosArm64" in txt
                        or "iosSimulatorArm64" in txt
                        or "iosX64" in txt
                    ):
                        kmp_modules.append(mod)
                        break
                except OSError:
                    pass
    return kmp_modules


def _find_podfile(root: Path, ios_dir: Optional[Path]) -> Optional[Path]:
    candidates = []
    if ios_dir:
        candidates.append(ios_dir / "Podfile")
    candidates.append(root / "Podfile")
    for sub in _IOS_SUBDIR_CANDIDATES:
        candidates.append(root / sub / "Podfile")
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def detect_project(start_dir: Optional[Path] = None, preferred_xcode: Optional[str] = None) -> ProjectContext:
    """
    Detect project root and type (ANDROID, XCODE, KMP, or UNKNOWN) starting from `start_dir`.
    Handles running from root as well as nested subdirectories (e.g., MyKMP/iosApp).
    """
    curr_start = Path(start_dir or os.getcwd()).resolve()

    gradle_root: Optional[Path] = None
    xcode_root: Optional[Path] = None
    swift_pkg_root: Optional[Path] = None

    curr = curr_start
    for _ in range(10):
        if gradle_root is None and _has_gradle_root(curr):
            gradle_root = curr
        if xcode_root is None and _list_xcode_in_dir(curr):
            xcode_root = curr
        if swift_pkg_root is None and (curr / "Package.swift").is_file():
            swift_pkg_root = curr

        # If we already found a Gradle root, check if it also contains iOS subdirs and stop walking up
        if gradle_root is not None:
            break
        if curr.parent == curr:
            break
        curr = curr.parent

    # Determine canonical project root:
    # If a Gradle root exists (even above an iosApp/ Xcode dir), that is the KMP/Android root.
    if gradle_root is not None:
        root = gradle_root
    elif xcode_root is not None:
        root = xcode_root
    elif swift_pkg_root is not None:
        root = swift_pkg_root
    else:
        root = curr_start

    has_android = gradle_root is not None
    xcode_entries = find_xcode_entries(root)
    if xcode_root is not None and not xcode_entries:
        xcode_entries = _list_xcode_in_dir(xcode_root)

    has_ios = bool(xcode_entries) or (swift_pkg_root is not None and not has_android)

    # Pick preferred Xcode workspace / project
    selected_ws: Optional[Path] = None
    selected_proj: Optional[Path] = None

    if preferred_xcode:
        pref_path = Path(preferred_xcode)
        if not pref_path.is_absolute():
            pref_path = (root / pref_path).resolve()
        for entry in xcode_entries:
            if entry.resolve() == pref_path or entry.name == preferred_xcode:
                if entry.suffix == ".xcworkspace":
                    selected_ws = entry
                elif entry.suffix == ".xcodeproj":
                    selected_proj = entry
                break

    if selected_ws is None and selected_proj is None and xcode_entries:
        # Prefer .xcworkspace over .xcodeproj
        workspaces = [e for e in xcode_entries if e.suffix == ".xcworkspace"]
        projects = [e for e in xcode_entries if e.suffix == ".xcodeproj"]
        if workspaces:
            selected_ws = workspaces[0]
        if projects:
            selected_proj = projects[0]
    elif selected_ws is not None and selected_proj is None:
        projects = [e for e in xcode_entries if e.suffix == ".xcodeproj" and e.parent == selected_ws.parent]
        if projects:
            selected_proj = projects[0]

    active_xcode = selected_ws or selected_proj
    ios_dir = active_xcode.parent if active_xcode else (swift_pkg_root if has_ios else None)
    podfile = _find_podfile(root, ios_dir) if has_ios else None

    kmp_modules = _detect_kmp_shared_modules(root) if has_android else []
    is_kmp = bool(has_android and (has_ios or kmp_modules))

    if is_kmp:
        ptype = ProjectType.KMP
    elif has_android:
        ptype = ProjectType.ANDROID
    elif has_ios:
        ptype = ProjectType.XCODE
    else:
        ptype = ProjectType.UNKNOWN

    return ProjectContext(
        root=root,
        start_dir=curr_start,
        project_type=ptype,
        has_android=has_android,
        has_ios=has_ios,
        xcode_workspace=selected_ws,
        xcode_project=selected_proj,
        all_xcode_entries=xcode_entries,
        ios_dir=ios_dir,
        podfile=podfile,
        is_kmp=is_kmp,
        kmp_shared_modules=kmp_modules,
    )


def resolve_active_platform(
    cli_platform: Optional[str] = None,
    interactive: bool = True,
) -> str:
    """
    Determine whether the current command should run in 'android' or 'ios' mode.
    Priority:
      1. Explicit CLI flag (--ios / --android / -P ios|android)
      2. Single-platform project (ANDROID -> 'android', XCODE -> 'ios')
      3. KMP subdirectory auto-detection (iosApp/ -> 'ios', androidApp/ -> 'android')
      4. Saved default in .flash/config.json (target_platform)
      5. Interactive prompt for KMP projects
    """
    if cli_platform in ("android", "ios"):
        return cli_platform

    from .config import ConfigManager

    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context

    if ctx.project_type == ProjectType.XCODE:
        return "ios"
    if ctx.project_type == ProjectType.ANDROID:
        return "android"

    if ctx.project_type == ProjectType.KMP:
        # Subdirectory auto-detection
        if ctx.ios_dir and ctx.ios_dir != ctx.root and _is_subpath(ctx.start_dir, ctx.ios_dir):
            return "ios"
        for sub in _ANDROID_SUBDIR_CANDIDATES:
            android_sub = ctx.root / sub
            if android_sub.is_dir() and _is_subpath(ctx.start_dir, android_sub):
                return "android"

        saved = cfg.get_target_platform()
        if saved in ("android", "ios"):
            return saved

        if not interactive:
            return "android"

        chosen = ui.ask_choice(
            "Phát hiện dự án KMP (Android + iOS). Vui lòng chọn nền tảng:",
            [
                ("android", "🤖 Android (Gradle / ADB)"),
                ("ios", "🍎 iOS (Xcode / Simulator & Physical Device)"),
            ],
            default_idx=0,
        )
        return chosen

    return "android"
