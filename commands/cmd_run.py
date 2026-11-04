#!/usr/bin/env python3
"""
One-click Build, Install, Launch, and optional Logcat streaming.
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional
from core.device import resolve_target_device
from core.gradle import execute_gradle, resolve_target_flavor
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

    # 1. Resolve Target Device
    dev = resolve_target_device(device_arg=device_id)
    if not dev:
        sys.exit(1)

    # 2. Resolve Product Flavor (if multiple exist)
    flavor_info = resolve_target_flavor(module=mod, flavor_arg=flavor, interactive=True, allow_all=False)
    flavor_name = flavor_info.name if flavor_info else None

    ui.header(f"Chạy ứng dụng trên thiết bị [{dev.model or dev.serial}]")
    ui.detail("Thiết bị", dev.display_name)
    if flavor_name:
        ui.detail("Product Flavor", flavor_name)

    apk_path = None
    # 3. Build APK (unless --no-build is set)
    if not no_build:
        flavor_desc = f" ({flavor_name}, {variant})" if flavor_name else f" ({variant})"
        ui.info(f"Đang biên dịch APK{flavor_desc}...")
        if flavor_name:
            task = f"assemble{flavor_name.capitalize()}{variant.capitalize()}"
        else:
            task = f"assemble{variant.capitalize()}"
        res = execute_gradle(task, module=mod)
        if res.returncode != 0:
            ui.error("Build APK thất bại! Dừng thực thi.")
            sys.exit(res.returncode)

    # 4. Locate APK
    apk_path = find_best_apk(variant=variant, module=mod, flavor=flavor_name)
    if not apk_path or not apk_path.exists():
        flavor_err = f" và flavor '{flavor_name}'" if flavor_name else ""
        ui.error(f"Không tìm thấy file APK cho variant '{variant}'{flavor_err}. Hãy chạy 'flash build' trước.")
        sys.exit(1)

    size_mb = apk_path.stat().st_size / (1024 * 1024)
    ui.success(f"Đã định vị APK: {ui.Colors.BOLD}{apk_path.name}{ui.Colors.RESET} ({size_mb:.2f} MB)")

    # 5. Install APK
    ui.info(f"Đang cài đặt APK lên thiết bị {dev.serial}...")
    install_res = subprocess.run([adb, "-s", dev.serial, "install", "-r", str(apk_path)],
                                 capture_output=True, text=True)
    if install_res.returncode != 0 or "Failure" in install_res.stdout:
        ui.error(f"Cài đặt thất bại:\n{install_res.stdout}\n{install_res.stderr}")
        sys.exit(1)
    ui.success("Cài đặt APK thành công!")

    # 6. Detect Package Name
    pkg_name = detect_package_name(apk_path=apk_path, serial=dev.serial, flavor=flavor_name, module=mod)
    if not pkg_name:
        ui.error("Không xác định được Package Name của ứng dụng.")
        sys.exit(1)
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
        ui.error(f"Lỗi khi khởi chạy Activity:\n{combined_out.strip()}")
        sys.exit(1)

    ui.success(f"Ứng dụng đã khởi chạy thành công trên {dev.model or dev.serial}!")

    # 9. Optional Logcat
    if stream_logcat:
        print()
        ui.info("Đang chuyển sang theo dõi Logcat cho ứng dụng...")
        run_logcat(app_filter=pkg_name, device_id=dev.serial)
