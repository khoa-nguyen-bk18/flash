#!/usr/bin/env python3
"""
One-click iOS Build, Install, Launch, and optional Log streaming.
Supports iOS Simulators (auto-boot) and Physical Devices (devicectl), multi-device and multi-scheme.
"""

import sys
from pathlib import Path
from typing import Optional

from core import ui
from core.config import ConfigManager
from core.ios_device import (
    IOSDeviceInfo,
    boot_simulator,
    resolve_target_ios_devices,
)
from core.xcode_project import (
    detect_ios_bundle_id,
    get_active_xcode_path,
    read_app_plist_info,
    resolve_target_xcode_variants,
)
from core.xcode_build import build_ios_app, find_built_app
from core.ios_actions import ios_install_app, ios_launch_app
from .cmd_ios_logs import run_ios_logs


def run_ios_app(
    variant: Optional[str] = None,
    device_id: Optional[str] = None,
    scheme: Optional[str] = None,
    no_build: bool = False,
    stream_logs: bool = False,
):
    cfg = ConfigManager.get_instance()
    xcode_path = get_active_xcode_path()
    if not xcode_path:
        ui.error("Không tìm thấy Xcode project (.xcodeproj) hoặc workspace (.xcworkspace).")
        sys.exit(1)

    # 1. Resolve Target iOS Devices (multi-device or 'run all')
    devices = resolve_target_ios_devices(device_arg=device_id, interactive=True)
    if not devices:
        sys.exit(1)

    # 2. Resolve Xcode Variants (Scheme x Configuration)
    target_variants = resolve_target_xcode_variants(
        scheme_arg=scheme,
        config_arg=variant,
        interactive=True,
        action_verb="Run",
        xcode_path=xcode_path,
    )
    if not target_variants:
        sys.exit(1)

    dev_names = ", ".join(d.name for d in devices)
    if len(devices) > 1:
        ui.header(f"Chạy ứng dụng iOS trên {len(devices)} thiết bị [{dev_names}]")
    else:
        ui.header(f"Chạy ứng dụng iOS trên thiết bị [{devices[0].name}]")

    display_xcode = target_variants[0].project_path or xcode_path
    ui.detail("Xcode Project", str(display_xcode))
    for d in devices:
        ui.detail("Thiết bị", d.display_name)
    ui.detail("Scheme / Config", ", ".join(v.name for v in target_variants))

    # 3. Auto-boot any selected Shutdown simulators before building/installing
    for d in devices:
        if d.is_simulator and not d.is_online:
            if not boot_simulator(d, open_simulator_app=True):
                ui.error(f"Không thể boot Simulator {d.name}.")
                if len(devices) == 1:
                    sys.exit(1)

    derived_data = cfg.get_derived_data_path()
    last_bundle_id: Optional[str] = None
    total_launches = 0
    failed_launches = 0

    for variant_info in target_variants:
        if len(target_variants) > 1:
            print()
            ui.info(f"{ui.Colors.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{ui.Colors.RESET}")
            ui.info(f"▶ Tiến hành với: {ui.Colors.CYAN}{ui.Colors.BOLD}{variant_info.name}{ui.Colors.RESET}")

        # Group devices by SDK type (simulator vs physical) so we only build once per SDK
        sim_devices = [d for d in devices if d.is_simulator]
        phys_devices = [d for d in devices if d.is_physical]

        groups = []
        if sim_devices:
            groups.append((True, sim_devices))
        if phys_devices:
            groups.append((False, phys_devices))

        for is_sim, group_devs in groups:
            app_path: Optional[Path] = None
            primary_dest = group_devs[0].xcodebuild_destination

            if not no_build:
                sdk_label = "Simulator" if is_sim else "Physical Device"
                ui.info(f"Đang biên dịch ({variant_info.scheme} - {variant_info.configuration} / {sdk_label})...")
                effective_xcode = variant_info.project_path or xcode_path
                build_kwargs = dict(
                    scheme=variant_info.scheme,
                    configuration=variant_info.configuration,
                    destination=primary_dest,
                    is_simulator=is_sim,
                    clean_first=False,
                    xcode_path=effective_xcode,
                )
                if variant_info.use_target:
                    build_kwargs["use_target"] = True
                app_path = build_ios_app(**build_kwargs)
                if not app_path or not app_path.exists():
                    ui.error(f"Build thất bại cho '{variant_info.name}' ({sdk_label})!")
                    if len(groups) == 1 and len(target_variants) == 1:
                        sys.exit(1)
                    failed_launches += len(group_devs)
                    continue
            else:
                app_path = find_built_app(
                    derived_data_path=derived_data,
                    configuration=variant_info.configuration,
                    is_simulator=is_sim,
                    scheme=variant_info.scheme,
                )
                if not app_path or not app_path.exists():
                    ui.error(
                        f"Không tìm thấy .app đã build cho '{variant_info.name}'. "
                        f"Hãy chạy 'flash build' trước hoặc bỏ cờ --no-build."
                    )
                    if len(groups) == 1 and len(target_variants) == 1:
                        sys.exit(1)
                    failed_launches += len(group_devs)
                    continue

            ui.success(f"Đã định vị App Bundle: {ui.Colors.BOLD}{app_path.name}{ui.Colors.RESET}")

            plist_info = read_app_plist_info(app_path)
            bundle_id = plist_info.get("bundle_id") or detect_ios_bundle_id(
                scheme=variant_info.scheme,
                configuration=variant_info.configuration,
                app_path=app_path,
                xcode_path=xcode_path,
            )
            if not bundle_id:
                ui.error(f"Không xác định được CFBundleIdentifier từ {app_path}.")
                if len(devices) == 1 and len(target_variants) == 1:
                    sys.exit(1)
                failed_launches += len(group_devs)
                continue

            last_bundle_id = bundle_id
            ui.detail("Bundle ID", bundle_id)

            for d_idx, dev in enumerate(group_devs):
                if len(devices) > 1 or len(target_variants) > 1:
                    print()
                    ui.info(f"[{d_idx + 1}/{len(group_devs)}] Cài đặt & khởi chạy trên {dev.display_name}...")

                if not ios_install_app(dev, app_path):
                    failed_launches += 1
                    if len(devices) == 1 and len(target_variants) == 1:
                        sys.exit(1)
                    continue

                if not ios_launch_app(dev, bundle_id):
                    failed_launches += 1
                    if len(devices) == 1 and len(target_variants) == 1:
                        sys.exit(1)
                    continue

                total_launches += 1

    # 4. Optional live log streaming
    if stream_logs and last_bundle_id and devices:
        print()
        target_dev = devices[0]
        if len(devices) > 1:
            ui.info(f"Đang chuyển sang theo dõi Logs trên thiết bị đầu tiên [{target_dev.name}]...")
        else:
            ui.info("Đang chuyển sang theo dõi Logs cho ứng dụng iOS...")
        run_ios_logs(app_filter=last_bundle_id, device_id=target_dev.udid)

    # 5. Summary for multi-device / multi-scheme
    if len(devices) > 1 or len(target_variants) > 1:
        print()
        if failed_launches == 0:
            ui.success(f"Hoàn tất! Đã khởi chạy thành công tất cả ({total_launches}/{total_launches}) lượt.")
        else:
            ui.warning(f"Hoàn tất với cảnh báo: {total_launches} thành công, {failed_launches} thất bại.")
        if total_launches == 0:
            sys.exit(1)
