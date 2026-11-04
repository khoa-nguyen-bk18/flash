#!/usr/bin/env python3
"""
Smart recursive APK discovery matching variants, flavors, and modification times.
"""

import os
from pathlib import Path
from typing import Optional, List
from .config import ConfigManager
from . import ui

def find_best_apk(variant: str = "debug", module: Optional[str] = None, flavor: Optional[str] = None) -> Optional[Path]:
    """
    Recursively searches for generated APK files matching variant and flavor.
    Filters out androidTest and sorts by newest mtime.
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

    all_apks: List[Path] = []
    for p in base_apk_dir.rglob("*.apk"):
        all_apks.append(p)

    if not all_apks:
        return None

    # Filter by variant, flavor, and exclude androidTest
    matching = []
    v_lower = variant.lower()
    fl_lower = flavor.lower() if flavor else None

    for apk in all_apks:
        path_str = str(apk).lower()
        if "androidtest" in path_str:
            continue
        if v_lower not in path_str:
            continue
        if fl_lower and fl_lower not in path_str:
            continue
        matching.append(apk)

    if not matching and fl_lower:
        # If strict flavor + variant failed, try any non-test APK with flavor
        matching = [a for a in all_apks if "androidtest" not in str(a).lower() and fl_lower in str(a).lower()]

    if not matching:
        # Fallback to any non-test APK with variant
        matching = [a for a in all_apks if "androidtest" not in str(a).lower() and v_lower in str(a).lower()]

    if not matching:
        # Fallback to any non-test APK
        matching = [a for a in all_apks if "androidtest" not in str(a).lower()]

    if not matching:
        return None

    # Sort by mtime descending (most recently built first)
    matching.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return matching[0]
