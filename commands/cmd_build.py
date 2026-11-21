#!/usr/bin/env python3
"""
Build commands: assembleDebug, assembleRelease, clean, and sync.
"""

import sys
from pathlib import Path
from typing import Optional
from core.gradle import execute_gradle, resolve_target_variants, cap_first
from core.apk_finder import find_best_apk
from core.config import ConfigManager
from core import ui


def _get_signing_args(cfg: ConfigManager) -> list[str]:
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
        return [
            f"-PANDROID_SIGNING_STORE_FILE={keystore_path}",
            f"-PANDROID_SIGNING_KEY_ALIAS={key_alias}",
            f"-PANDROID_SIGNING_STORE_PASSWORD={store_pw or ''}",
            f"-PANDROID_SIGNING_KEY_PASSWORD={key_pw or store_pw or ''}",
        ]
    return []


def run_build(variant: Optional[str] = None, module: Optional[str] = None, flavor: Optional[str] = None,
              clean_first: bool = False, signed: bool = False, all_flavors: bool = False):
    cfg = ConfigManager.get_instance()
    mod = module or cfg.get_target_module()

    if all_flavors:
        target_bt = variant or "debug"
        ui.header(f"Bắt đầu Build APK ({target_bt.upper()})")
        if mod:
            ui.detail("Target Module", mod)
        ui.detail("Product Flavor", "Tất cả flavors")

        if clean_first:
            ui.info("Đang Clean project trước khi build...")
            res_clean = execute_gradle("clean", module=mod)
            if res_clean.returncode != 0:
                ui.error("Lỗi khi Clean project. Dừng build.")
                sys.exit(res_clean.returncode)

        task = f"assemble{cap_first(target_bt)}"
        extra_args = _get_signing_args(cfg) if (target_bt.lower() == "release" and signed) else []
        res = execute_gradle(task, module=mod, extra_args=extra_args)
        if res.returncode != 0:
            ui.error(f"Build {target_bt} thất bại!")
            sys.exit(res.returncode)

        apk_file = find_best_apk(variant=target_bt, module=mod, flavor=None)
        if apk_file and apk_file.exists():
            size_mb = apk_file.stat().st_size / (1024 * 1024)
            ui.success("Build thành công! File APK:")
            print(f"  {ui.Colors.BOLD}{apk_file}{ui.Colors.RESET} ({size_mb:.2f} MB)")
        else:
            ui.warning("Gradle hoàn tất nhưng chưa định vị được file APK đầu ra.")
        return

    target_variants = resolve_target_variants(
        module=mod,
        flavor_arg=flavor,
        variant_arg=variant,
        interactive=True,
        action_verb="Build",
    )

    ui.header(f"Bắt đầu Build APK ({', '.join(v.name for v in target_variants)})")
    if mod:
        ui.detail("Target Module", mod)

    if clean_first:
        ui.info("Đang Clean project trước khi build...")
        res_clean = execute_gradle("clean", module=mod)
        if res_clean.returncode != 0:
            ui.error("Lỗi khi Clean project. Dừng build.")
            sys.exit(res_clean.returncode)

    signing_args = None
    for idx, v_info in enumerate(target_variants):
        if len(target_variants) > 1:
            print()
            ui.info(f"[{idx + 1}/{len(target_variants)}] Building variant: {ui.Colors.BOLD}{v_info.name}{ui.Colors.RESET}")

        extra_args = []
        if v_info.build_type.lower() == "release" and signed:
            if signing_args is None:
                signing_args = _get_signing_args(cfg)
            extra_args = signing_args

        res = execute_gradle(v_info.gradle_task, module=mod, extra_args=extra_args)
        if res.returncode != 0:
            ui.error(f"Build {v_info.name} thất bại!")
            sys.exit(res.returncode)

        apk_file = find_best_apk(variant=v_info.build_type, module=mod, flavor=v_info.flavor_name)
        if apk_file and apk_file.exists():
            size_mb = apk_file.stat().st_size / (1024 * 1024)
            ui.success(f"Build thành công ({v_info.name})! File APK:")
            print(f"  {ui.Colors.BOLD}{apk_file}{ui.Colors.RESET} ({size_mb:.2f} MB)")
        else:
            ui.warning(f"Gradle hoàn tất ({v_info.name}) nhưng chưa định vị được file APK đầu ra.")


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
