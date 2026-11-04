#!/usr/bin/env python3
"""
Package Name and Launcher Activity Detector.
Extracts package from APK, Gradle build scripts, AndroidManifest, or running device.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional
from .config import ConfigManager
from .gradle import get_product_flavors

def get_package_from_apk(apk_path: Path) -> Optional[str]:
    cfg = ConfigManager.get_instance()
    aapt = cfg.get_aapt_path()
    if not aapt or not apk_path.exists():
        return None

    try:
        res = subprocess.run([aapt, "dump", "badging", str(apk_path)], capture_output=True, text=True, timeout=5)
        m = re.search(r"package:\s*name='([^']+)'", res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def get_package_from_gradle(flavor: Optional[str] = None, module: Optional[str] = None) -> Optional[str]:
    cfg = ConfigManager.get_instance()
    root = cfg.project_root

    gradle_paths = []
    if module and module != "(Project Root)":
        clean_mod = module.lstrip(":")
        mod_dir = clean_mod.replace(":", os.sep)
        gradle_paths.extend([
            root / mod_dir / "build.gradle.kts",
            root / mod_dir / "build.gradle",
        ])
    else:
        gradle_paths.extend([
            root / "app" / "build.gradle.kts",
            root / "app" / "build.gradle",
            root / "build.gradle.kts",
            root / "build.gradle",
        ])

    base_pkg = None
    for gp in gradle_paths:
        if gp.exists():
            try:
                content = gp.read_text(encoding="utf-8")
                # Look for applicationId or namespace
                m_app = re.search(r'applicationId\s*=\s*["\']([^"\']+)["\']', content)
                if m_app:
                    base_pkg = m_app.group(1)
                    break
                m_app_legacy = re.search(r'applicationId\s+["\']([^"\']+)["\']', content)
                if m_app_legacy:
                    base_pkg = m_app_legacy.group(1)
                    break
                m_ns = re.search(r'namespace\s*=\s*["\']([^"\']+)["\']', content)
                if m_ns:
                    base_pkg = m_ns.group(1)
                    break
            except Exception:
                pass

    if not base_pkg:
        return None

    if flavor:
        flavors = get_product_flavors(module=module)
        for f in flavors:
            if f.name.lower() == flavor.lower() and f.application_id_suffix:
                return f"{base_pkg}{f.application_id_suffix}"

    return base_pkg


def get_package_from_manifest() -> Optional[str]:
    cfg = ConfigManager.get_instance()
    manifest_paths = [
        cfg.project_root / "app" / "src" / "main" / "AndroidManifest.xml",
        cfg.project_root / "src" / "main" / "AndroidManifest.xml",
    ]
    for mp in manifest_paths:
        if mp.exists():
            try:
                content = mp.read_text(encoding="utf-8")
                m = re.search(r'package\s*=\s*["\']([^"\']+)["\']', content)
                if m:
                    return m.group(1)
            except Exception:
                pass
    return None


def get_foreground_package(serial: str) -> Optional[str]:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    try:
        res = subprocess.run([adb, "-s", serial, "shell", "dumpsys window"], capture_output=True, text=True, timeout=3)
        m = re.search(r'mCurrentFocus=Window\{[^}]*\s+u\d+\s+([^\s/]+)', res.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def detect_package_name(apk_path: Optional[Path] = None, serial: Optional[str] = None,
                        flavor: Optional[str] = None, module: Optional[str] = None) -> Optional[str]:
    """Smart detection combining all sources."""
    if apk_path:
        pkg = get_package_from_apk(apk_path)
        if pkg:
            return pkg

    if flavor:
        pkg = get_package_from_gradle(flavor=flavor, module=module)
        if pkg:
            return pkg

    if serial:
        pkg = get_foreground_package(serial)
        if pkg:
            return pkg

    pkg = get_package_from_gradle(module=module)
    if pkg:
        return pkg

    pkg = get_package_from_manifest()
    if pkg:
        return pkg

    return None


def resolve_launcher_activity(package_name: str, serial: str) -> str:
    """
    Resolve installed launcher activity using cmd package resolve-activity.
    Fallback: <package_name>/.MainActivity
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    try:
        cmd = [
            adb, "-s", serial, "shell",
            "cmd", "package", "resolve-activity", "--brief",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER",
            package_name
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
        if res.returncode == 0:
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
            for line in reversed(lines):
                if "/" in line and "ResolverActivity" not in line and "ChooserActivity" not in line:
                    return line
    except Exception:
        pass

    return f"{package_name}/.MainActivity"
