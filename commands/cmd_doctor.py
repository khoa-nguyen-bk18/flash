#!/usr/bin/env python3
"""
Diagnostic tool for testing SDK, ADB, JDK, devices, and project configuration.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
from core.config import ConfigManager
from core.device import get_connected_devices
from core import ui

def run_doctor():
    ui.header("Android Flash Doctor - Kiểm tra chẩn đoán môi trường")
    cfg = ConfigManager.get_instance()
    has_issues = False

    # 1. Check Project Root
    print(f"\n{ui.Colors.BOLD}1. Thư mục Android Project:{ui.Colors.RESET}")
    if cfg.project_root:
        ui.success(f"Project root: {cfg.project_root}")
        # Check settings.gradle
        has_settings = (cfg.project_root / "settings.gradle.kts").exists() or (cfg.project_root / "settings.gradle").exists()
        if has_settings:
            ui.success("Tìm thấy settings.gradle / settings.gradle.kts")
        else:
            ui.warning("Không tìm thấy settings.gradle. Có thể bạn đang ở trong sub-directory?")
    else:
        ui.error("Không tìm thấy Android project root.")
        has_issues = True

    # 2. Check Android SDK
    print(f"\n{ui.Colors.BOLD}2. Android SDK & Biến môi trường:{ui.Colors.RESET}")
    sdk_path = cfg.get_sdk_path()
    if sdk_path and Path(sdk_path).exists():
        ui.success(f"Android SDK: {sdk_path}")
    else:
        ui.error("Không tìm thấy Android SDK!")
        ui.info("Khắc phục: Cài Android Command-Line Tools hoặc set biến ANDROID_HOME trong ~/.zshrc")
        has_issues = True

    # 3. Check ADB
    print(f"\n{ui.Colors.BOLD}3. Android Debug Bridge (ADB):{ui.Colors.RESET}")
    try:
        adb_path = cfg.get_adb_path()
        ui.success(f"ADB executable: {adb_path}")
        res = subprocess.run([adb_path, "version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            first_line = res.stdout.strip().splitlines()[0]
            ui.success(f"Phiên bản: {first_line}")
        else:
            ui.warning("Không lấy được phiên bản ADB.")
    except Exception as e:
        ui.error(f"Lỗi ADB: {e}")
        has_issues = True

    # 4. Check ADB Server & Restart test
    print(f"\n{ui.Colors.BOLD}4. ADB Server:{ui.Colors.RESET}")
    try:
        adb = cfg.get_adb_path()
        subprocess.run([adb, "start-server"], capture_output=True, text=True, timeout=5)
        ui.success("ADB Server đang hoạt động tốt.")
    except Exception as e:
        ui.warning(f"Cảnh báo ADB Server: {e}")

    # 5. Check Connected Devices
    print(f"\n{ui.Colors.BOLD}5. Thiết bị kết nối:{ui.Colors.RESET}")
    devices = get_connected_devices()
    if devices:
        ui.success(f"Tìm thấy {len(devices)} thiết bị:")
        for d in devices:
            print(f"    {d.display_name}")
            if d.state == "unauthorized":
                ui.warning(f"  -> Thiết bị {d.serial} chưa được cấp quyền (Unauthorized)! Mở màn hình điện thoại và bấm 'Allow USB debugging'.")
            elif d.state == "offline":
                ui.warning(f"  -> Thiết bị {d.serial} đang ở trạng thái Offline. Thử cắm lại cáp hoặc chạy 'flash doctor'.")
    else:
        ui.warning("Chưa có thiết bị nào được kết nối.")
        ui.info("Vui lòng cắm cáp USB hoặc kết nối Wi-Fi (Settings -> Developer Options -> Wireless debugging).")

    # 6. Check Java JDK & keytool
    print(f"\n{ui.Colors.BOLD}6. Java JDK & keytool:{ui.Colors.RESET}")
    java_home = os.getenv("JAVA_HOME")
    if java_home and Path(java_home).exists():
        ui.success(f"JAVA_HOME: {java_home}")
    else:
        which_java = shutil.which("java")
        if which_java:
            ui.info(f"Java tìm thấy qua PATH: {which_java}")
        else:
            ui.warning("Chưa cấu hình JAVA_HOME và không tìm thấy java trong PATH.")

    try:
        kt = cfg.get_keytool_path()
        ui.success(f"keytool: {kt}")
    except Exception:
        ui.warning("Không tìm thấy keytool (cần cho tính năng tạo Keystore).")

    # 7. Check local.properties & gradlew
    print(f"\n{ui.Colors.BOLD}7. Cấu hình local.properties & Gradle Wrapper:{ui.Colors.RESET}")
    local_props = cfg.project_root / "local.properties"
    if local_props.exists():
        ui.success(f"local.properties: {local_props}")
    else:
        ui.warning("Chưa có local.properties. Flash sẽ tự động tạo khi chạy build/run.")
        cfg.ensure_local_properties()

    wrapper_name = "gradlew.bat" if sys.platform == "win32" else "gradlew"
    wrapper = cfg.project_root / wrapper_name
    if wrapper.exists():
        ui.success(f"Gradle wrapper: {wrapper}")
        if sys.platform != "win32" and not os.access(wrapper, os.X_OK):
            ui.warning(f"{wrapper_name} chưa có quyền thực thi. Đang cấp quyền chmod +x...")
            os.chmod(wrapper, 0o755)
    else:
        ui.error(f"Không tìm thấy {wrapper_name} tại {cfg.project_root}!")
        has_issues = True

    # Summary
    print()
    if has_issues:
        ui.error("Phát hiện một số vấn đề cần xử lý trước khi build/run ứng dụng.")
    else:
        ui.success("Mọi thứ đã sẵn sàng! Bạn có thể sử dụng các lệnh: flash run, flash build, flash logcat, v.v.")
