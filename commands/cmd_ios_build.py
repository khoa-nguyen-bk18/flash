#!/usr/bin/env python3
"""
iOS Build, Clean, and Sync commands powered by xcodebuild, CocoaPods, and SPM.
"""

import sys
from pathlib import Path
from typing import List, Optional

from core.config import ConfigManager
from core import ui
from core.xcode_build import (
    archive_ios_app,
    build_ios_app,
    clean_xcode_project,
    sync_ios_dependencies,
)
from core.xcode_project import (
    XcodeVariantInfo,
    get_active_xcode_path,
    get_xcode_list_info,
    resolve_target_xcode_variants,
)


def _path_size_mb(target: Path) -> float:
    """Compute file or directory bundle size in megabytes."""
    try:
        if target.is_file():
            return target.stat().st_size / (1024 * 1024)
        total = 0
        for item in target.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
        return total / (1024 * 1024)
    except OSError:
        return 0.0


def run_ios_build(
    variant: Optional[str] = None,
    scheme: Optional[str] = None,
    clean_first: bool = False,
    signed: bool = False,
    all_schemes: bool = False,
    device_destination: Optional[str] = None,
):
    xcode_path = get_active_xcode_path()
    if xcode_path is None:
        ui.error("Không tìm thấy .xcworkspace hoặc .xcodeproj trong dự án hiện tại.")
        sys.exit(1)

    if device_destination:
        destination = device_destination
        is_simulator = "simulator" in device_destination.lower()
    elif signed:
        destination = "generic/platform=iOS"
        is_simulator = False
    else:
        destination = "generic/platform=iOS Simulator"
        is_simulator = True

    target_variants: List[XcodeVariantInfo]
    if all_schemes:
        info = get_xcode_list_info(xcode_path=xcode_path)
        if not info or not info.schemes:
            ui.error("Không tìm thấy Xcode Scheme nào để build.")
            sys.exit(1)

        configs = info.configurations or ["Debug", "Release"]
        cfg_map = {c.lower(): c for c in configs}
        if variant:
            if variant.lower() not in cfg_map:
                ui.error(
                    f"Configuration '{variant}' không tồn tại. "
                    f"Các configurations hiện có: {', '.join(configs)}"
                )
                sys.exit(1)
            target_config = cfg_map[variant.lower()]
        else:
            target_config = cfg_map.get("debug", configs[0])

        target_variants = [XcodeVariantInfo(scheme=s, configuration=target_config) for s in info.schemes]
    else:
        target_variants = resolve_target_xcode_variants(
            scheme_arg=scheme,
            config_arg=variant,
            interactive=True,
            action_verb="Build",
            xcode_path=xcode_path,
        )

    ui.header(f"Bắt đầu Build iOS ({', '.join(v.name for v in target_variants)})")
    ui.detail("Xcode Project", str(xcode_path))
    ui.detail("Destination", destination)
    if signed:
        ui.detail("Chế độ", "Signed / Archive (Device)")

    if clean_first:
        ui.info("Đang Clean Xcode project trước khi build...")
        clean_ok = clean_xcode_project(
            scheme=target_variants[0].scheme if len(target_variants) == 1 else None,
            clean_derived_data=True,
            clean_gradle_kmp=False,
            xcode_path=xcode_path,
        )
        if not clean_ok:
            ui.error("Lỗi khi Clean Xcode project. Dừng build.")
            sys.exit(1)

    for idx, v_info in enumerate(target_variants):
        if len(target_variants) > 1:
            print()
            ui.info(
                f"[{idx + 1}/{len(target_variants)}] Building: "
                f"{ui.Colors.BOLD}{v_info.name}{ui.Colors.RESET}"
            )

        if signed and v_info.configuration.lower() == "release":
            output_path = archive_ios_app(
                scheme=v_info.scheme,
                configuration=v_info.configuration,
                xcode_path=xcode_path,
            )
            if output_path is None:
                ui.error(f"Archive iOS thất bại ({v_info.name})!")
                sys.exit(1)

            size_mb = _path_size_mb(output_path)
            artifact_kind = "IPA" if output_path.suffix.lower() == ".ipa" else "Archive"
            ui.success(f"Archive thành công ({v_info.name})! File {artifact_kind}:")
            print(f"  {ui.Colors.BOLD}{output_path}{ui.Colors.RESET} ({size_mb:.2f} MB)")
        else:
            effective_xcode = v_info.project_path or xcode_path
            app_path = build_ios_app(
                scheme=v_info.scheme,
                configuration=v_info.configuration,
                destination=destination,
                is_simulator=is_simulator,
                clean_first=False,
                xcode_path=effective_xcode,
                use_target=v_info.use_target,
            )
            if app_path is None:
                ui.error(f"Build iOS thất bại ({v_info.name})!")
                sys.exit(1)

            size_mb = _path_size_mb(app_path)
            ui.success(f"Build thành công ({v_info.name})! Bundle .app:")
            print(f"  {ui.Colors.BOLD}{app_path}{ui.Colors.RESET} ({size_mb:.2f} MB)")


def run_ios_clean(clean_all_kmp: bool = False):
    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    title = "Dọn dẹp iOS & KMP Build Artifacts" if (clean_all_kmp and ctx.is_kmp) else "Dọn dẹp iOS Build Artifacts (Xcode Clean)"
    ui.header(title)

    ok = clean_xcode_project(
        clean_derived_data=True,
        clean_gradle_kmp=clean_all_kmp,
    )
    if ok:
        ui.success("Dọn dẹp iOS project thành công!")
    else:
        ui.error("Lệnh clean iOS gặp lỗi.")
        sys.exit(1)


def run_ios_sync():
    ui.header("Đồng bộ hóa iOS Dependencies (CocoaPods & SwiftPM)")
    ok = sync_ios_dependencies()
    if ok:
        ui.success("Đồng bộ iOS dependencies hoàn tất!")
    else:
        ui.error("Đồng bộ iOS dependencies gặp lỗi.")
        sys.exit(1)
