#!/usr/bin/env python3
"""
Build commands: assembleDebug, assembleRelease, clean, and sync.
"""

import sys
from pathlib import Path
from typing import Optional
from core.gradle import execute_gradle, resolve_target_flavor
from core.apk_finder import find_best_apk
from core.config import ConfigManager
from core import ui

def run_build(variant: str = "debug", module: Optional[str] = None, flavor: Optional[str] = None,
              clean_first: bool = False, signed: bool = False, all_flavors: bool = False):
    cfg = ConfigManager.get_instance()
    mod = module or cfg.get_target_module()

    flavor_info = None
    flavor_name = None
    if not all_flavors:
        flavor_info = resolve_target_flavor(module=mod, flavor_arg=flavor, interactive=True, allow_all=True)
        if flavor_info:
            flavor_name = flavor_info.name

    ui.header(f"Bắt đầu Build APK ({variant.upper()})")
    if mod:
        ui.detail("Target Module", mod)
    if flavor_name:
        ui.detail("Product Flavor", flavor_name)
    elif all_flavors:
        ui.detail("Product Flavor", "Tất cả flavors")

    if clean_first:
        ui.info("Đang Clean project trước khi build...")
        res_clean = execute_gradle("clean", module=mod)
        if res_clean.returncode != 0:
            ui.error("Lỗi khi Clean project. Dừng build.")
            sys.exit(res_clean.returncode)

    if flavor_name:
        task = f"assemble{flavor_name.capitalize()}{variant.capitalize()}"
    else:
        task = f"assemble{variant.capitalize()}"

    extra_args = []

    if variant.lower() == "release" and signed:
        # Check if local.properties already has signing keys or prompt
        local_props = cfg.project_root / "local.properties"
        keystore_path = None
        key_alias = None
        store_pw = None
        key_pw = None

        if local_props.exists():
            content = local_props.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("RELEASE_KEYSTORE_PATH="):
                    keystore_path = line.split("=", 1)[1].strip()
                elif line.startswith("RELEASE_KEY_ALIAS="):
                    key_alias = line.split("=", 1)[1].strip()
                elif line.startswith("RELEASE_STORE_PASSWORD="):
                    store_pw = line.split("=", 1)[1].strip()
                elif line.startswith("RELEASE_KEY_PASSWORD="):
                    key_pw = line.split("=", 1)[1].strip()

        if keystore_path and key_alias:
            ui.info(f"Sử dụng keystore cấu hình sẵn: {keystore_path} (alias: {key_alias})")
            extra_args.extend([
                f"-PANDROID_SIGNING_STORE_FILE={keystore_path}",
                f"-PANDROID_SIGNING_KEY_ALIAS={key_alias}",
                f"-PANDROID_SIGNING_STORE_PASSWORD={store_pw or ''}",
                f"-PANDROID_SIGNING_KEY_PASSWORD={key_pw or store_pw or ''}",
            ])

    res = execute_gradle(task, module=mod, extra_args=extra_args)
    if res.returncode != 0:
        ui.error(f"Build {variant} thất bại!")
        sys.exit(res.returncode)

    apk_file = find_best_apk(variant=variant, module=mod, flavor=flavor_name)
    if apk_file and apk_file.exists():
        size_mb = apk_file.stat().st_size / (1024 * 1024)
        ui.success(f"Build thành công! File APK:")
        print(f"  {ui.Colors.BOLD}{apk_file}{ui.Colors.RESET} ({size_mb:.2f} MB)")
    else:
        ui.warning("Gradle hoàn tất nhưng chưa định vị được file APK đầu ra.")


def run_clean(module: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    mod = module or cfg.get_target_module()
    ui.header("Dọn dẹp Build Artifacts (Gradle Clean)")
    res = execute_gradle("clean", module=mod)
    if res.returncode == 0:
        ui.success("Dọn dẹp project thành công!")
    else:
        ui.error("Lệnh clean thất bại.")
        sys.exit(res.returncode)


def run_sync():
    ui.header("Đồng bộ hóa Gradle dependencies (Sync)")
    res = execute_gradle("tasks")
    if res.returncode == 0:
        ui.success("Gradle Sync hoàn tất!")
    else:
        ui.error("Gradle Sync gặp lỗi.")
        sys.exit(res.returncode)
