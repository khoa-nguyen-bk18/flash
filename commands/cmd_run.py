#!/usr/bin/env python3
"""
One-click Build, Install, Launch, and optional Logcat streaming.
Supports multi-device and multi-flavor execution.
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional, List
from core.device import resolve_target_devices, DeviceInfo
from core.gradle import execute_gradle, resolve_target_flavors, FlavorInfo
from core.apk_finder import find_best_apk
from core.package_detector import detect_package_name, resolve_launcher_activity
from core.config import ConfigManager
from core import ui
from .cmd_logcat import run_logcat

def run_app(variant: str = "debug", device_id: Optional[str] = None, module: Optional[str] = None,
            flavor: Optional[str] = None, no_build: bool = False, stream_logcat: bool = False):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    mod = module or cfg.get_target_module()

    # 1. Resolve Target Devices (multi-device selection or 'run all')
    devices = resolve_target_devices(device_arg=device_id)
    if not devices:
        sys.exit(1)

    # 2. Resolve Product Flavors (multi-flavor selection or 'run all', no default save prompt)
    target_flavors = resolve_target_flavors(module=mod, flavor_arg=flavor, interactive=True)
    if not target_flavors:
        sys.exit(1)

    dev_names = ", ".join(d.model or d.serial for d in devices)
    if len(devices) > 1:
        ui.header(f"Chạy ứng dụng trên {len(devices)} thiết bị [{dev_names}]")
    else:
        dev = devices[0]
        ui.header(f"Chạy ứng dụng trên thiết bị [{dev.model or dev.serial}]")

    for d in devices:
        ui.detail("Thiết bị", d.display_name)

    flavor_names = [f.name for f in target_flavors if f]
    if flavor_names:
        ui.detail("Product Flavor(s)", ", ".join(flavor_names))
    ui.detail("Build Variant", variant)

    last_apk_path = None
    last_pkg_name = None
    total_launches = 0
    failed_launches = 0

    for f_idx, flavor_info in enumerate(target_flavors):
        flavor_name = flavor_info.name if flavor_info else None
        if len(target_flavors) > 1:
            print()
            ui.info(f"{ui.Colors.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{ui.Colors.RESET}")
            ui.info(f"▶ Tiến hành với Flavor: {ui.Colors.CYAN}{ui.Colors.BOLD}{flavor_name or 'Default'}{ui.Colors.RESET}")

        apk_path = None
        # 3. Build APK (unless --no-build is set) - built once per flavor
        if not no_build:
            flavor_desc = f" ({flavor_name}, {variant})" if flavor_name else f" ({variant})"
            ui.info(f"Đang biên dịch APK{flavor_desc}...")
            if flavor_name:
                task = f"assemble{flavor_name.capitalize()}{variant.capitalize()}"
            else:
                task = f"assemble{variant.capitalize()}"
            res = execute_gradle(task, module=mod)
            if res.returncode != 0:
                ui.error(f"Build APK thất bại cho flavor '{flavor_name or variant}'! Dừng thực thi.")
                sys.exit(res.returncode)

        # 4. Locate APK
        apk_path = find_best_apk(variant=variant, module=mod, flavor=flavor_name)
        if not apk_path or not apk_path.exists():
            flavor_err = f" và flavor '{flavor_name}'" if flavor_name else ""
            ui.error(f"Không tìm thấy file APK cho variant '{variant}'{flavor_err}. Hãy chạy 'flash build' trước.")
            sys.exit(1)

        last_apk_path = apk_path
        size_mb = apk_path.stat().st_size / (1024 * 1024)
        ui.success(f"Đã định vị APK: {ui.Colors.BOLD}{apk_path.name}{ui.Colors.RESET} ({size_mb:.2f} MB)")

        # 5. Install & Launch on each device
        for d_idx, dev in enumerate(devices):
            if len(devices) > 1 or len(target_flavors) > 1:
                print()
                ui.info(f"[{d_idx + 1}/{len(devices)}] Cài đặt & khởi chạy trên {dev.display_name}...")

            # Install APK
            ui.info(f"Đang cài đặt APK lên thiết bị {dev.serial}...")
            install_res = subprocess.run([adb, "-s", dev.serial, "install", "-r", str(apk_path)],
                                         capture_output=True, text=True)
            if install_res.returncode != 0 or "Failure" in install_res.stdout:
                ui.error(f"Cài đặt thất bại trên {dev.serial}:\n{install_res.stdout}\n{install_res.stderr}")
                failed_launches += 1
                if len(devices) == 1 and len(target_flavors) == 1:
                    sys.exit(1)
                continue
            ui.success(f"Cài đặt APK thành công trên {dev.serial}!")

            # 6. Detect Package Name
            pkg_name = detect_package_name(apk_path=apk_path, serial=dev.serial, flavor=flavor_name, module=mod)
            if not pkg_name:
                ui.error(f"Không xác định được Package Name của ứng dụng trên {dev.serial}.")
                failed_launches += 1
                if len(devices) == 1 and len(target_flavors) == 1:
                    sys.exit(1)
                continue
            last_pkg_name = pkg_name
            ui.detail("Package Name", pkg_name)

            # 7. Resolve Launcher Activity
            activity = resolve_launcher_activity(pkg_name, dev.serial)
            ui.detail("Launcher Activity", activity)

            # 8. Launch App via am start
            full_activity = activity if "/" in activity else f"{pkg_name}/{activity}"
            ui.info(f"Khởi chạy: {full_activity}")
            launch_res = subprocess.run([adb, "-s", dev.serial, "shell", "am", "start", "-n", full_activity],
                                        capture_output=True, text=True)

            combined_out = f"{launch_res.stdout}\n{launch_res.stderr}"
            if "Error:" in combined_out or "Error type" in combined_out:
                ui.error(f"Lỗi khi khởi chạy Activity trên {dev.serial}:\n{combined_out.strip()}")
                failed_launches += 1
                if len(devices) == 1 and len(target_flavors) == 1:
                    sys.exit(1)
                continue

            total_launches += 1
            ui.success(f"Ứng dụng đã khởi chạy thành công trên {dev.model or dev.serial}!")

    # 9. Optional Logcat
    if stream_logcat and last_pkg_name and devices:
        print()
        target_dev = devices[0]
        if len(devices) > 1:
            ui.info(f"Đang chuyển sang theo dõi Logcat trên thiết bị đầu tiên [{target_dev.serial}]...")
        else:
            ui.info("Đang chuyển sang theo dõi Logcat cho ứng dụng...")
        run_logcat(app_filter=last_pkg_name, device_id=target_dev.serial)

    # 10. Summary if multiple operations
    if len(devices) > 1 or len(target_flavors) > 1:
        print()
        if failed_launches == 0:
            ui.success(f"Hoàn tất! Đã khởi chạy thành công tất cả ({total_launches}/{total_launches}) lượt trên các mục tiêu.")
        else:
            ui.warning(f"Hoàn tất với cảnh báo: {total_launches} thành công, {failed_launches} thất bại.")
        if total_launches == 0:
            sys.exit(1)
