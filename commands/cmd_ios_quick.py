#!/usr/bin/env python3
"""
iOS Quick Operations: App lifecycle, clear data, permissions, screenshot,
and Simulator utilities (boot, shutdown, erase, appearance, deep link).
Mirrors commands/cmd_quick.py UX for Xcode / iOS projects.
"""

import sys
from pathlib import Path
from typing import Optional, Tuple

from core import ui
from core.config import ConfigManager
from core.ios_device import IOSDeviceInfo, boot_simulator, resolve_target_ios_device
from core.xcode_project import detect_ios_bundle_id, get_active_xcode_path, get_xcode_list_info
from core.xcode_build import find_built_app
from core.ios_actions import (
    ios_clear_data,
    ios_clear_restart,
    ios_erase_simulator,
    ios_grant_permissions,
    ios_install_app,
    ios_launch_app,
    ios_open_url,
    ios_restart_app,
    ios_revoke_permissions,
    ios_screenshot,
    ios_shutdown_simulator,
    ios_terminate_app,
    ios_toggle_appearance,
    ios_uninstall_app,
)


def resolve_ios_app_context(
    device_id: Optional[str] = None,
    scheme: Optional[str] = None,
    bundle_id: Optional[str] = None,
    interactive: bool = True,
) -> Tuple[IOSDeviceInfo, str]:
    """
    Resolve target iOS device and app Bundle ID.
    """
    cfg = ConfigManager.get_instance()
    dev = resolve_target_ios_device(device_arg=device_id, interactive=interactive)
    if not dev:
        sys.exit(1)

    resolved_bundle = bundle_id
    if not resolved_bundle:
        target_scheme = scheme or cfg.get_selected_xcode_scheme()
        xcode_path = get_active_xcode_path()

        # Try reading from already-built .app first (instant, no xcodebuild overhead)
        derived_data = cfg.get_derived_data_path()
        cached_app = find_built_app(
            derived_data_path=derived_data,
            configuration=cfg.get_selected_xcode_config() or "Debug",
            is_simulator=dev.is_simulator,
            scheme=target_scheme,
        )
        if cached_app:
            resolved_bundle = detect_ios_bundle_id(app_path=cached_app)

        if not resolved_bundle and xcode_path:
            if not target_scheme:
                info = get_xcode_list_info(xcode_path)
                if info and info.schemes:
                    target_scheme = info.schemes[0]
            if target_scheme:
                resolved_bundle = detect_ios_bundle_id(
                    scheme=target_scheme,
                    configuration=cfg.get_selected_xcode_config() or "Debug",
                    xcode_path=xcode_path,
                )

    if not resolved_bundle:
        if interactive:
            resolved_bundle = ui.ask_input("Nhập Bundle Identifier (ví dụ: com.example.MyApp)")
        if not resolved_bundle:
            ui.error("Không xác định được Bundle Identifier. Hãy dùng cờ -p / --package hoặc -f / --flavor (scheme).")
            sys.exit(1)

    return dev, resolved_bundle


def run_ios_quick_menu(
    device_id: Optional[str] = None,
    scheme: Optional[str] = None,
    bundle_id: Optional[str] = None,
):
    """Interactive 1-click popup menu for iOS Simulator & Physical Device actions."""
    dev, bid = resolve_ios_app_context(
        device_id=device_id,
        scheme=scheme,
        bundle_id=bundle_id,
        interactive=True,
    )

    ui.header(f"iOS Quick Actions - [{dev.name}]")
    ui.detail("Thiết bị", dev.display_name)
    ui.detail("Bundle ID", bid)

    options = [
        ("restart", "🔄 Restart App (Dừng và mở lại ứng dụng)"),
        ("kill", "🛑 Kill App (Buộc dừng ứng dụng)"),
        ("clear", "🧹 Clear App Data (Xóa sạch dữ liệu app - Simulator)"),
        ("clear_restart", "♻️  Clear App Data and Restart (Xóa dữ liệu & mở lại)"),
        ("start", "▶️  Start App (Khởi chạy ứng dụng)"),
        ("uninstall", "🗑️  Uninstall App (Gỡ cài đặt ứng dụng)"),
        ("install", "📦 Install .app / .ipa..."),
        ("perm_grant", "🔓 Grant Permissions (Cấp toàn bộ quyền - Simulator)"),
        ("perm_revoke", "🔒 Revoke Permissions (Reset quyền - Simulator)"),
        ("perm_revoke_restart", "🔒 Revoke Permissions and Restart"),
        ("screenshot", "📸 Take Screenshot (Chụp màn hình lưu về máy)"),
        ("open_url", "🔗 Open Deep Link / URL (Mở URL trên Simulator)"),
        ("appearance", "🌗 Toggle Dark / Light Mode (Simulator)"),
        ("sim_boot", "📲 Boot Simulator"),
        ("sim_shutdown", "💤 Shutdown Simulator"),
        ("sim_erase", "⚠️  Erase Simulator (Reset máy ảo về mặc định)"),
    ]

    chosen = ui.ask_choice("Chọn thao tác nhanh iOS:", options, default_idx=0)

    if chosen == "restart":
        ios_restart_app(dev, bid)
    elif chosen == "kill":
        ios_terminate_app(dev, bid)
    elif chosen == "clear":
        ios_clear_data(dev, bid, restart=False)
    elif chosen == "clear_restart":
        ios_clear_restart(dev, bid)
    elif chosen == "start":
        ios_launch_app(dev, bid)
    elif chosen == "uninstall":
        ios_uninstall_app(dev, bid, confirm=True)
    elif chosen == "install":
        path_str = ui.ask_input("Nhập đường dẫn file .app hoặc .ipa")
        if path_str:
            ios_install_app(dev, Path(path_str).expanduser().resolve())
    elif chosen == "perm_grant":
        ios_grant_permissions(dev, bid)
    elif chosen == "perm_revoke":
        ios_revoke_permissions(dev, bid, restart=False)
    elif chosen == "perm_revoke_restart":
        ios_revoke_permissions(dev, bid, restart=True)
    elif chosen == "screenshot":
        ios_screenshot(dev, open_after=True)
    elif chosen == "open_url":
        url = ui.ask_input("Nhập URL / Deep Link (ví dụ: myapp://home)")
        if url:
            ios_open_url(dev, url)
    elif chosen == "appearance":
        mode = ui.ask_choice("Chọn giao diện:", [("dark", "🌙 Dark Mode"), ("light", "☀️ Light Mode")])
        ios_toggle_appearance(dev, mode=mode)
    elif chosen == "sim_boot":
        boot_simulator(dev, open_simulator_app=True)
    elif chosen == "sim_shutdown":
        ios_shutdown_simulator(dev)
    elif chosen == "sim_erase":
        ios_erase_simulator(dev)
