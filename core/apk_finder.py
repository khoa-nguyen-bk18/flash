#!/usr/bin/env python3
"""
Smart recursive APK discovery matching variants, flavors, and modification times.
"""

import os
import re
from pathlib import Path
from typing import Optional, List
from .config import ConfigManager
from . import ui


def _split_flavor_tokens(flavor: str) -> List[str]:
    """Split camelCase/kebab/snake flavor name into lowercase tokens (e.g. globalGplay -> ['global', 'gplay'])."""
    parts = re.findall(r'[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z]|$)', flavor)
    return [p.lower() for p in parts if p]


def _has_token(path_str: str, token: str) -> bool:
    return re.search(rf'(?:^|[/\\_\-.]){re.escape(token)}(?:$|[/\\_\-.])', path_str) is not None


def find_best_apk(variant: str = "debug", module: Optional[str] = None, flavor: Optional[str] = None) -> Optional[Path]:
    """
    Recursively searches for generated APK files matching variant and flavor.
    Supports multi-dimension flavor names (e.g. globalGplay matching .../globalGplay/debug/app-global-gplay-debug.apk).
    Filters out androidTest/unitTest and sorts by newest mtime.
    """
    cfg = ConfigManager.get_instance()
    root = cfg.project_root

    # Determine module subdirectory
    module_dir = "app"
    if module and module != "(Project Root)":
        clean_mod = module.lstrip(":")
        module_dir = clean_mod.replace(":", os.sep)

    base_apk_dir = root / module_dir / "build" / "outputs" / "apk"
    if not base_apk_dir.exists():
        # Fallback check root/build/outputs/apk
        base_apk_dir = root / "build" / "outputs" / "apk"
        if not base_apk_dir.exists():
            return None

    non_test_apks: List[Path] = [
        p for p in base_apk_dir.rglob("*.apk")
        if "androidtest" not in str(p).lower() and "unittest" not in str(p).lower()
    ]

    if not non_test_apks:
        return None

    v_lower = variant.lower()
    fl_lower = flavor.lower() if flavor else None
    fl_tokens = _split_flavor_tokens(flavor) if flavor else []

    def matches_flavor_strict(path_str: str) -> bool:
        if not fl_lower:
            return True
        if _has_token(path_str, fl_lower):
            return True
        return bool(fl_tokens) and all(_has_token(path_str, t) for t in fl_tokens)

    def matches_flavor_loose(path_str: str) -> bool:
        if not fl_lower:
            return True
        if fl_lower in path_str:
            return True
        return bool(fl_tokens) and all(t in path_str for t in fl_tokens)

    # Priority 1: strict token match on both variant and flavor
    matching = [
        a for a in non_test_apks
        if _has_token(str(a).lower(), v_lower) and matches_flavor_strict(str(a).lower())
    ]

    # Priority 2: substring match on both variant and flavor (or all flavor tokens)
    if not matching:
        matching = [
            a for a in non_test_apks
            if v_lower in str(a).lower() and matches_flavor_loose(str(a).lower())
        ]

    # Priority 3: flavor match only
    if not matching and fl_lower:
        matching = [a for a in non_test_apks if matches_flavor_loose(str(a).lower())]

    # Priority 4: variant match only
    if not matching:
        matching = [a for a in non_test_apks if v_lower in str(a).lower()]

    # Priority 5: any non-test APK
    if not matching:
        matching = non_test_apks

    # Sort by mtime descending (most recently built first)
    matching.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return matching[0]
