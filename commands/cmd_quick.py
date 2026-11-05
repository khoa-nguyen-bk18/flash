#!/usr/bin/env python3
"""
ADB Quick Operations: App lifecycle, permissions, network controls, screenshot, and shell.
Implements one-click popup menu and direct CLI shortcuts.
"""

import sys
import os
import re
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

from core.device import resolve_target_device, DeviceInfo
from core.package_detector import detect_package_name, resolve_launcher_activity, get_foreground_package
from core.gradle import get_product_flavors, resolve_target_flavor
from core.config import ConfigManager
from core import ui

def resolve_app_context(device_id: Optional[str] = None, flavor: Optional[str] = None,
                        package_name: Optional[str] = None, interactive: bool = True) -> Tuple[DeviceInfo, str, str]:
    """
    Resolve target device, package name, and launcher activity.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    dev = resolve_target_device(device_arg=device_id, interactive=interactive)
    if not dev:
        sys.exit(1)

    # 1. If explicit package name provided
    pkg = package_name
    if not pkg:
        # 2. Check if flavor is specified
        if flavor:
            pkg = detect_package_name(serial=dev.serial, flavor=flavor)
        else:
            # 3. Check if foreground app belongs to project
            fg = get_foreground_package(dev.serial)
            flavors = get_product_flavors()
            if flavors:
                possible_pkgs = []
                for f in flavors:
                    p = detect_package_name(flavor=f.name)
                    if p:
                        possible_pkgs.append((f.name, p))

                if fg and any(fg == p for _, p in possible_pkgs):
                    pkg = fg
                else:
                    # Check saved default flavor
                    saved_flavor = cfg.get_selected_flavor()
                    if saved_flavor:
                        pkg = detect_package_name(flavor=saved_flavor)
                    elif interactive and len(flavors) > 1 and sys.stdout.isatty():
                        fl = resolve_target_flavor(flavor_arg=flavor, interactive=True)
                        if fl:
                            pkg = detect_package_name(flavor=fl.name)
            
            if not pkg:
                pkg = detect_package_name(serial=dev.serial)

    if not pkg:
        ui.error("Không xác định được Package Name. Hãy dùng cờ -p / --package hoặc -f / --flavor.")
        sys.exit(1)

    launcher = resolve_launcher_activity(pkg, dev.serial)
    return dev, pkg, launcher


# --- App Lifecycle Actions ---

def action_start(dev: DeviceInfo, pkg: str, launcher: str):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    full_act = launcher if "/" in launcher else f"{pkg}/{launcher}"
    ui.info(f"Khởi chạy ứng dụng {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")
    res = subprocess.run([adb, "-s", dev.serial, "shell", "am", "start", "-n", full_act],
                         capture_output=True, text=True)
    if res.returncode == 0 and "Error" not in res.stdout:
        ui.success(f"Đã mở {full_act} trên {dev.model or dev.serial}")
    else:
        ui.error(f"Khởi chạy thất bại: {res.stdout.strip()} {res.stderr.strip()}")


def action_kill(dev: DeviceInfo, pkg: str):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.info(f"Buộc dừng ứng dụng {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")
    res = subprocess.run([adb, "-s", dev.serial, "shell", "am", "force-stop", pkg],
                         capture_output=True, text=True)
    if res.returncode == 0:
        ui.success(f"Đã buộc dừng ứng dụng {pkg} thành công!")
    else:
        ui.error(f"Lỗi khi dừng ứng dụng: {res.stderr.strip()}")


def action_restart(dev: DeviceInfo, pkg: str, launcher: str):
    ui.info(f"Đang khởi động lại ứng dụng {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")
    action_kill(dev, pkg)
    time.sleep(0.3)
    action_start(dev, pkg, launcher)


def action_clear_data(dev: DeviceInfo, pkg: str, restart: bool = False, launcher: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.info(f"Đang xóa dữ liệu ứng dụng (Clear App Data) cho {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")
    res = subprocess.run([adb, "-s", dev.serial, "shell", "pm", "clear", pkg],
                         capture_output=True, text=True)
    if "Success" in res.stdout:
        ui.success(f"Đã xóa sạch bộ nhớ & dữ liệu của {pkg}!")
    else:
        ui.error(f"Lỗi khi xóa dữ liệu: {res.stdout.strip()} {res.stderr.strip()}")

    if restart and launcher:
        time.sleep(0.3)
        action_start(dev, pkg, launcher)


def action_clear_restart(dev: DeviceInfo, pkg: str, launcher: str):
    """
    Xóa toàn bộ dữ liệu ứng dụng (Clear Data) và khởi động lại ứng dụng trên thiết bị.
    """
    action_clear_data(dev, pkg, restart=True, launcher=launcher)


def action_uninstall(dev: DeviceInfo, pkg: str):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    if not ui.ask_confirm(f"Bạn có chắc chắn muốn gỡ cài đặt (Uninstall) {pkg} trên {dev.model or dev.serial}?", default=False):
        ui.info("Đã hủy thao tác.")
        return

    ui.info(f"Đang gỡ cài đặt {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")
    res = subprocess.run([adb, "-s", dev.serial, "uninstall", pkg],
                         capture_output=True, text=True)
    if "Success" in res.stdout:
        ui.success(f"Đã gỡ cài đặt {pkg} thành công!")
    else:
        ui.error(f"Gỡ cài đặt thất bại: {res.stdout.strip()} {res.stderr.strip()}")


def action_install_apk(dev: DeviceInfo, apk_path_str: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    if not apk_path_str:
        apk_path_str = ui.ask_input("Nhập đường dẫn file APK cần cài đặt")

    if not apk_path_str:
        ui.error("Đường dẫn APK không hợp lệ.")
        return

    apk_file = Path(apk_path_str).resolve()
    if not apk_file.exists():
        ui.error(f"Không tìm thấy file APK tại: {apk_file}")
        return

    ui.info(f"Đang cài đặt {apk_file.name} lên {dev.model or dev.serial}...")
    res = subprocess.run([adb, "-s", dev.serial, "install", "-r", str(apk_file)],
                         capture_output=True, text=True)
    if "Success" in res.stdout:
        ui.success(f"Cài đặt APK {apk_file.name} thành công!")
    else:
        ui.error(f"Cài đặt thất bại:\n{res.stdout}\n{res.stderr}")


# --- Permissions Management ---

def action_grant_permissions(dev: DeviceInfo, pkg: str):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.info(f"Đang phân tích và cấp toàn bộ quyền runtime cho {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")

    # Get requested permissions from dumpsys package
    res = subprocess.run([adb, "-s", dev.serial, "shell", f"dumpsys package {pkg}"],
                         capture_output=True, text=True)
    if res.returncode != 0:
        ui.error(f"Không thể đọc thông tin package {pkg}.")
        return

    # Extract permissions under 'requested permissions:'
    req_perms = []
    in_section = False
    for line in res.stdout.splitlines():
        if "requested permissions:" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("    ") and not line.startswith("      "):
                in_section = False
                break
            stripped = line.strip()
            if stripped.startswith("android.permission."):
                req_perms.append(stripped)

    if not req_perms:
        # Fallback list of common runtime permissions
        req_perms = [
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.RECORD_AUDIO",
            "android.permission.READ_PHONE_STATE",
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.READ_CONTACTS",
            "android.permission.WRITE_CONTACTS",
            "android.permission.READ_CALL_LOG",
            "android.permission.WRITE_CALL_LOG",
        ]

    granted_count = 0
    for perm in req_perms:
        cmd = [adb, "-s", dev.serial, "shell", "pm", "grant", pkg, perm]
        p_res = subprocess.run(cmd, capture_output=True, text=True)
        if p_res.returncode == 0 and "SecurityException" not in p_res.stderr:
            granted_count += 1
            perm_name = perm.replace("android.permission.", "")
            print(f"  {ui.Colors.GREEN}✔{ui.Colors.RESET} Cấp quyền: {perm_name}")

    if granted_count > 0:
        ui.success(f"Đã cấp thành công {granted_count} quyền runtime cho {pkg}!")
    else:
        ui.warning("Không có quyền runtime nào cần cấp hoặc app chưa được cài đặt.")


def action_revoke_permissions(dev: DeviceInfo, pkg: str, restart: bool = False, launcher: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.info(f"Đang thu hồi tất cả quyền runtime (Reset Permissions) cho {ui.Colors.BOLD}{pkg}{ui.Colors.RESET}...")

    res = subprocess.run([adb, "-s", dev.serial, "shell", "pm", "reset-permissions", pkg],
                         capture_output=True, text=True)
    if res.returncode == 0:
        ui.success(f"Đã reset toàn bộ quyền của {pkg} về trạng thái mặc định!")
    else:
        ui.error(f"Thu hồi quyền thất bại: {res.stderr.strip()}")

    if restart and launcher:
        time.sleep(0.3)
        action_restart(dev, pkg, launcher)


# --- Network & System Toggles ---

def get_wifi_status(dev: DeviceInfo) -> bool:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    res = subprocess.run([adb, "-s", dev.serial, "shell", "settings get global wifi_on"],
                         capture_output=True, text=True)
    return res.stdout.strip() == "1"


def action_wifi(dev: DeviceInfo, mode: str = "toggle"):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    current = get_wifi_status(dev)

    if mode == "status":
        ui.info(f"Trạng thái Wi-Fi hiện tại: {ui.Colors.BOLD}{'BẬT' if current else 'TẮT'}{ui.Colors.RESET}")
        return

    if mode == "toggle":
        target = not current
    elif mode in ("on", "enable"):
        target = True
    else:
        target = False

    cmd_arg = "enable" if target else "disable"
    subprocess.run([adb, "-s", dev.serial, "shell", "svc", "wifi", cmd_arg], capture_output=True)
    state_str = f"{ui.Colors.GREEN}BẬT{ui.Colors.RESET}" if target else f"{ui.Colors.RED}TẮT{ui.Colors.RESET}"
    ui.success(f"Đã chuyển Wi-Fi sang: {state_str}")


def get_mobile_data_status(dev: DeviceInfo) -> bool:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    res = subprocess.run([adb, "-s", dev.serial, "shell", "settings get global mobile_data"],
                         capture_output=True, text=True)
    return res.stdout.strip() == "1"


def action_mobile_data(dev: DeviceInfo, mode: str = "toggle"):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    current = get_mobile_data_status(dev)

    if mode == "status":
        ui.info(f"Trạng thái Mobile Data: {ui.Colors.BOLD}{'BẬT' if current else 'TẮT'}{ui.Colors.RESET}")
        return

    if mode == "toggle":
        target = not current
    elif mode in ("on", "enable"):
        target = True
    else:
        target = False

    cmd_arg = "enable" if target else "disable"
    subprocess.run([adb, "-s", dev.serial, "shell", "svc", "data", cmd_arg], capture_output=True)
    state_str = f"{ui.Colors.GREEN}BẬT{ui.Colors.RESET}" if target else f"{ui.Colors.RED}TẮT{ui.Colors.RESET}"
    ui.success(f"Đã chuyển Dữ liệu di động (Mobile Data) sang: {state_str}")


def get_airplane_mode_status(dev: DeviceInfo) -> bool:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    res = subprocess.run([adb, "-s", dev.serial, "shell", "cmd connectivity airplane-mode"],
                         capture_output=True, text=True)
    if "enabled" in res.stdout:
        return True
    res2 = subprocess.run([adb, "-s", dev.serial, "shell", "settings get global airplane_mode_on"],
                          capture_output=True, text=True)
    return res2.stdout.strip() == "1"


def action_airplane(dev: DeviceInfo, mode: str = "toggle"):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    current = get_airplane_mode_status(dev)

    if mode == "status":
        ui.info(f"Trạng thái Chế độ máy bay: {ui.Colors.BOLD}{'BẬT' if current else 'TẮT'}{ui.Colors.RESET}")
        return

    if mode == "toggle":
        target = not current
    elif mode in ("on", "enable"):
        target = True
    else:
        target = False

    cmd_arg = "enable" if target else "disable"
    subprocess.run([adb, "-s", dev.serial, "shell", "cmd", "connectivity", "airplane-mode", cmd_arg],
                   capture_output=True)
    # Also sync setting & broadcast for full compatibility
    val = "1" if target else "0"
    bool_str = "true" if target else "false"
    subprocess.run([adb, "-s", dev.serial, "shell", f"settings put global airplane_mode_on {val}"], capture_output=True)
    subprocess.run([adb, "-s", dev.serial, "shell", f"am broadcast -a android.intent.action.AIRPLANE_MODE --ez state {bool_str}"], capture_output=True)

    state_str = f"{ui.Colors.YELLOW}BẬT{ui.Colors.RESET}" if target else f"{ui.Colors.DIM}TẮT{ui.Colors.RESET}"
    ui.success(f"Đã chuyển Chế độ máy bay (Airplane Mode) sang: {state_str}")


# --- Utilities ---

def action_screenshot(dev: DeviceInfo, output_path: Optional[str] = None, open_after: bool = False):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    if output_path:
        out_file = Path(output_path).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_file = Path.cwd() / f"screenshot_{timestamp}.png"

    ui.info(f"Đang chụp màn hình thiết bị {dev.model or dev.serial}...")
    try:
        with open(out_file, "wb") as f:
            res = subprocess.run([adb, "-s", dev.serial, "exec-out", "screencap", "-p"],
                                 stdout=f, stderr=subprocess.PIPE)

        if res.returncode == 0 and out_file.exists() and out_file.stat().st_size > 0:
            size_kb = out_file.stat().st_size / 1024
            ui.success(f"Đã lưu ảnh chụp màn hình thành công ({size_kb:.1f} KB):")
            print(f"  {ui.Colors.BOLD}{out_file}{ui.Colors.RESET}")
            if open_after:
                if sys.platform == "darwin":
                    subprocess.run(["open", str(out_file)])
                elif sys.platform == "win32":
                    os.startfile(str(out_file))
                else:
                    subprocess.run(["xdg-open", str(out_file)])
        else:
            ui.error(f"Lỗi khi chụp màn hình: {res.stderr.decode('utf-8', errors='ignore')}")
    except Exception as e:
        ui.error(f"Không thể lưu file screenshot: {e}")


def action_shell(dev: DeviceInfo):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.header(f"ADB Shell - {dev.model or dev.serial}")
    ui.info("Gõ 'exit' để quay lại terminal của bạn.\n")
    try:
        subprocess.run([adb, "-s", dev.serial, "shell"])
    except KeyboardInterrupt:
        print()


# --- Interactive Menu ---

def run_quick_menu(device_id: Optional[str] = None, flavor: Optional[str] = None, package_name: Optional[str] = None):
    dev, pkg, launcher = resolve_app_context(device_id=device_id, flavor=flavor,
                                             package_name=package_name, interactive=True)

    wifi_status = "BẬT" if get_wifi_status(dev) else "TẮT"
    data_status = "BẬT" if get_mobile_data_status(dev) else "TẮT"
    air_status = "BẬT" if get_airplane_mode_status(dev) else "TẮT"

    ui.header(f"ADB Quick Operations [{dev.model or dev.serial}]")
    ui.detail("Target Device", dev.display_name)
    ui.detail("Target Package", pkg)
    ui.detail("Launcher", launcher)
    print()

    menu = [
        # App Operations
        ("1", "Restart App", lambda: action_restart(dev, pkg, launcher)),
        ("2", "Kill App (Force Stop)", lambda: action_kill(dev, pkg)),
        ("3", "Clear App Data", lambda: action_clear_data(dev, pkg)),
        ("4", "Clear App Data and Restart", lambda: action_clear_restart(dev, pkg, launcher)),
        ("5", "Start App", lambda: action_start(dev, pkg, launcher)),
        ("6", "Uninstall App", lambda: action_uninstall(dev, pkg)),
        ("7", "Install APK...", lambda: action_install_apk(dev)),

        # Permissions
        ("8", "Grant Permissions (Cấp toàn bộ quyền runtime)", lambda: action_grant_permissions(dev, pkg)),
        ("9", "Revoke Permissions (Reset quyền)", lambda: action_revoke_permissions(dev, pkg)),
        ("10", "Revoke Permissions and Restart", lambda: action_revoke_permissions(dev, pkg, restart=True, launcher=launcher)),

        # Network Controls
        ("11", f"Toggle Wi-Fi (Hiện tại: {wifi_status})", lambda: action_wifi(dev, "toggle")),
        ("12", "Enable Wi-Fi", lambda: action_wifi(dev, "enable")),
        ("13", "Disable Wi-Fi", lambda: action_wifi(dev, "disable")),
        ("14", f"Toggle Mobile Data (Hiện tại: {data_status})", lambda: action_mobile_data(dev, "toggle")),
        ("15", "Enable Mobile Data", lambda: action_mobile_data(dev, "enable")),
        ("16", "Disable Mobile Data", lambda: action_mobile_data(dev, "disable")),
        ("17", f"Toggle Airplane Mode (Hiện tại: {air_status})", lambda: action_airplane(dev, "toggle")),

        # Utilities
        ("18", "Take Screenshot (Chụp ảnh màn hình)", lambda: action_screenshot(dev, open_after=True)),
        ("19", "Open Interactive Shell", lambda: action_shell(dev)),
    ]

    print(f"{ui.Colors.CYAN}{ui.Colors.BOLD}[ App Operations ]{ui.Colors.RESET}")
    for k, title, _ in menu[:7]:
        print(f"  {ui.Colors.BOLD}{k:>2}){ui.Colors.RESET} {title}")

    print(f"\n{ui.Colors.CYAN}{ui.Colors.BOLD}[ Permissions ]{ui.Colors.RESET}")
    for k, title, _ in menu[7:10]:
        print(f"  {ui.Colors.BOLD}{k:>2}){ui.Colors.RESET} {title}")

    print(f"\n{ui.Colors.CYAN}{ui.Colors.BOLD}[ Device Controls ]{ui.Colors.RESET}")
    for k, title, _ in menu[10:17]:
        print(f"  {ui.Colors.BOLD}{k:>2}){ui.Colors.RESET} {title}")

    print(f"\n{ui.Colors.CYAN}{ui.Colors.BOLD}[ Utilities ]{ui.Colors.RESET}")
    for k, title, _ in menu[17:]:
        print(f"  {ui.Colors.BOLD}{k:>2}){ui.Colors.RESET} {title}")

    print(f"\n  {ui.Colors.DIM} 0) Thoát{ui.Colors.RESET}\n")

    while True:
        try:
            choice = input(f"{ui.Colors.BOLD}Chọn thao tác (1-{len(menu)}, 0 để thoát):{ui.Colors.RESET} ").strip()
            if not choice or choice == "0":
                ui.info("Đã thoát.")
                return
            for k, _, func in menu:
                if choice == k:
                    print()
                    func()
                    return
            print(f"{ui.Colors.RED}Lựa chọn không hợp lệ. Vui lòng nhập số từ 1 đến {len(menu)}.{ui.Colors.RESET}")
        except (KeyboardInterrupt, EOFError):
            print()
            return
