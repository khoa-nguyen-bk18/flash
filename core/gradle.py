#!/usr/bin/env python3
"""
Gradle build execution and multi-module discovery.
"""

import os
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Optional
from .config import ConfigManager
from . import ui

def get_gradlew_path() -> Path:
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    if not root:
        raise FileNotFoundError("Không tìm thấy thư mục gốc của project Android.")

    wrapper_name = "gradlew.bat" if sys.platform == "win32" else "gradlew"
    wrapper_path = root / wrapper_name
    if wrapper_path.exists():
        # Ensure executable bit on Unix
        if sys.platform != "win32" and not os.access(wrapper_path, os.X_OK):
            try:
                os.chmod(wrapper_path, 0o755)
            except Exception:
                pass
        return wrapper_path

    raise FileNotFoundError(f"Không tìm thấy '{wrapper_name}' tại {root}.")


class FlavorInfo:
    def __init__(self, name: str, dimension: Optional[str] = None,
                 application_id_suffix: str = "", version_name_suffix: str = ""):
        self.name = name
        self.dimension = dimension
        self.application_id_suffix = application_id_suffix
        self.version_name_suffix = version_name_suffix

    def __repr__(self) -> str:
        return f"FlavorInfo(name={self.name!r}, dimension={self.dimension!r}, suffix={self.application_id_suffix!r})"


def get_product_flavors(module: Optional[str] = None) -> List[FlavorInfo]:
    """
    Parse build.gradle.kts or build.gradle of the given module to discover productFlavors.
    """
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    if not root:
        return []

    mod_paths = []
    if module and module != "(Project Root)":
        clean_mod = module.lstrip(":")
        mod_dir = clean_mod.replace(":", os.sep)
        mod_paths.extend([
            root / mod_dir / "build.gradle.kts",
            root / mod_dir / "build.gradle",
        ])
    else:
        mod_paths.extend([
            root / "app" / "build.gradle.kts",
            root / "app" / "build.gradle",
            root / "build.gradle.kts",
            root / "build.gradle",
        ])

    for bp in mod_paths:
        if not bp.exists():
            continue
        try:
            content = bp.read_text(encoding="utf-8")
            idx = content.find("productFlavors")
            if idx == -1:
                continue

            open_brace = content.find("{", idx)
            if open_brace == -1:
                continue

            # Extract full balanced body of productFlavors { ... }
            depth = 1
            pos = open_brace + 1
            while pos < len(content) and depth > 0:
                if content[pos] == "{":
                    depth += 1
                elif content[pos] == "}":
                    depth -= 1
                pos += 1

            block = content[open_brace + 1:pos - 1]

            # Find flavors inside block
            # Kotlin DSL: create("name"), register("name"), "name" {
            # Groovy DSL: name {
            flavor_pattern = re.compile(
                r'(?:(?:create|register)\s*\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\)|["\']([a-zA-Z0-9_]+)["\']\s*\{|([a-zA-Z0-9_]+)\s*\{)'
            )

            flavors: List[FlavorInfo] = []
            seen = set()

            for match in flavor_pattern.finditer(block):
                fl_name = match.group(1) or match.group(2) or match.group(3)
                if not fl_name or fl_name in seen:
                    continue
                # Exclude gradle keywords that might look like a block
                if fl_name in ("dimension", "dimensionList", "signingConfig", "manifestPlaceholders"):
                    continue

                seen.add(fl_name)

                # Locate inner block for this flavor to extract properties
                f_start = block.find("{", match.start())
                f_body = ""
                if f_start != -1:
                    f_depth = 1
                    f_pos = f_start + 1
                    while f_pos < len(block) and f_depth > 0:
                        if block[f_pos] == "{":
                            f_depth += 1
                        elif block[f_pos] == "}":
                            f_depth -= 1
                        f_pos += 1
                    f_body = block[f_start + 1:f_pos - 1]

                suffix_m = re.search(r'applicationIdSuffix\s*(?:=|\s)\s*["\']([^"\']+)["\']', f_body)
                suffix = suffix_m.group(1) if suffix_m else ""

                version_suffix_m = re.search(r'versionNameSuffix\s*(?:=|\s)\s*["\']([^"\']+)["\']', f_body)
                version_suffix = version_suffix_m.group(1) if version_suffix_m else ""

                dim_m = re.search(r'dimension\s*(?:=|\s)\s*["\']([^"\']+)["\']', f_body)
                dimension = dim_m.group(1) if dim_m else None

                flavors.append(FlavorInfo(
                    name=fl_name,
                    dimension=dimension,
                    application_id_suffix=suffix,
                    version_name_suffix=version_suffix
                ))

            if flavors:
                return flavors

        except Exception:
            pass

    return []


def resolve_target_flavor(module: Optional[str] = None, flavor_arg: Optional[str] = None,
                          interactive: bool = True, allow_all: bool = False) -> Optional[FlavorInfo]:
    """
    Resolve flavor:
    - If module has 0 flavors, returns None.
    - If flavor_arg is provided, validates and returns it.
    - If saved in config, returns it (or prompts if interactive).
    - If interactive and >1 flavors, presents choice menu to user.
    """
    flavors = get_product_flavors(module=module)
    if not flavors:
        return None

    flavor_map = {f.name.lower(): f for f in flavors}

    if flavor_arg:
        fl_lower = flavor_arg.lower()
        if fl_lower in flavor_map:
            return flavor_map[fl_lower]
        ui.error(f"Flavor '{flavor_arg}' không tồn tại trong module. Các flavor hiện có: {', '.join(flavor_map.keys())}")
        sys.exit(1)

    if len(flavors) == 1:
        return flavors[0]

    cfg = ConfigManager.get_instance()
    saved = cfg.get_selected_flavor()
    if saved and saved.lower() in flavor_map and not interactive:
        return flavor_map[saved.lower()]

    if not interactive:
        return flavor_map[saved.lower()] if (saved and saved.lower() in flavor_map) else flavors[0]

    # Multiple flavors: interactive selection
    options = []
    default_idx = 0
    for idx, f in enumerate(flavors):
        desc_parts = []
        if f.dimension:
            desc_parts.append(f"dimension: {f.dimension}")
        if f.application_id_suffix:
            desc_parts.append(f"suffix: {f.application_id_suffix}")
        desc = f"{ui.Colors.BOLD}{f.name}{ui.Colors.RESET}"
        if desc_parts:
            desc += f" ({', '.join(desc_parts)})"
        options.append((f.name, desc))
        if saved and f.name.lower() == saved.lower():
            default_idx = idx

    if allow_all:
        options.append(("all", f"{ui.Colors.CYAN}Build tất cả flavors{ui.Colors.RESET}"))

    chosen = ui.ask_choice("Phát hiện nhiều Product Flavors. Vui lòng chọn Flavor:", options, default_idx=default_idx)
    if chosen == "all":
        return None

    selected = flavor_map[chosen.lower()]
    return selected


def resolve_target_flavors(module: Optional[str] = None, flavor_arg: Optional[str] = None,
                           interactive: bool = True) -> List[Optional[FlavorInfo]]:
    """
    Resolve target product flavors:
    - If 0 flavors exist in module, returns [None] (standard single APK build).
    - If flavor_arg is provided via CLI (-f/--flavor), validates and returns [matched_flavor].
    - If 1 flavor exists, returns [flavors[0]].
    - If >1 flavors exist:
        If interactive: prompts user with multiselect (Up/Down + Space + "Run all" option).
        If not interactive: returns all flavors.
    Note: Does NOT prompt to save default flavor.
    """
    flavors = get_product_flavors(module=module)
    if not flavors:
        return [None]

    flavor_map = {f.name.lower(): f for f in flavors}

    if flavor_arg:
        fl_lower = flavor_arg.lower()
        if fl_lower in flavor_map:
            return [flavor_map[fl_lower]]
        ui.error(f"Flavor '{flavor_arg}' không tồn tại trong module. Các flavor hiện có: {', '.join(flavor_map.keys())}")
        sys.exit(1)

    if len(flavors) == 1:
        return [flavors[0]]

    if not interactive:
        return flavors

    # Multiple flavors: interactive multiselect
    options = []
    for f in flavors:
        desc_parts = []
        if f.dimension:
            desc_parts.append(f"dimension: {f.dimension}")
        if f.application_id_suffix:
            desc_parts.append(f"suffix: {f.application_id_suffix}")
        desc = f"{ui.Colors.BOLD}{f.name}{ui.Colors.RESET}"
        if desc_parts:
            desc += f" ({', '.join(desc_parts)})"
        options.append((f.name, desc))

    chosen_names = ui.ask_multiselect(
        title="Phát hiện nhiều Product Flavors. Vui lòng chọn Flavor:",
        options=options,
        all_label="⚡ Run all (Tất cả flavors)"
    )

    chosen_set = {name.lower() for name in chosen_names}
    selected_flavors = [f for f in flavors if f.name.lower() in chosen_set]
    return selected_flavors if selected_flavors else flavors


def list_modules() -> List[str]:
    """
    Parse settings.gradle.kts and settings.gradle to discover all modules.
    """
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    modules = [":app"]

    settings_files = [root / "settings.gradle.kts", root / "settings.gradle"]
    found_modules = set()

    for sf in settings_files:
        if sf.exists():
            try:
                content = sf.read_text(encoding="utf-8")
                # Matches: include(":app", ":core", ":feature:login")
                matches = re.findall(r'include\s*\((.*?)\)', content, re.DOTALL)
                for block in matches:
                    items = re.findall(r'["\'](:[^"\']+)["\']', block)
                    found_modules.update(items)
                # Matches: include ":app", ":core"
                line_matches = re.findall(r'include\s+([^\r\n]+)', content)
                for line in line_matches:
                    items = re.findall(r'["\'](:[^"\']+)["\']', line)
                    found_modules.update(items)
            except Exception:
                pass

    if found_modules:
        modules = sorted(list(found_modules))
        # Ensure :app is first if present
        if ":app" in modules:
            modules.remove(":app")
            modules.insert(0, ":app")

    return modules


def execute_gradle(task: str, module: Optional[str] = None, extra_args: Optional[List[str]] = None, capture: bool = False) -> subprocess.CompletedProcess:
    cfg = ConfigManager.get_instance()
    cfg.ensure_local_properties()
    gradlew = get_gradlew_path()

    # Prepend target module if given (e.g. :app:assembleDebug)
    final_task = task
    if module and module != "(Project Root)" and not task.startswith(":"):
        final_task = f"{module}:{task}"

    cmd = [str(gradlew), final_task]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    if cfg.sdk_path:
        env.setdefault("ANDROID_HOME", cfg.sdk_path)
        env.setdefault("ANDROID_SDK_ROOT", cfg.sdk_path)

    ui.info(f"Thực thi Gradle: {ui.Colors.BOLD}{' '.join(cmd)}{ui.Colors.RESET}")
    ui.detail("Project Root", str(cfg.project_root))

    if capture:
        return subprocess.run(cmd, cwd=str(cfg.project_root), env=env, capture_output=True, text=True)
    else:
        return subprocess.run(cmd, cwd=str(cfg.project_root), env=env)
