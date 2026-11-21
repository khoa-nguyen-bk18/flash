#!/usr/bin/env python3
"""
Xcode Scheme management command: list, select, and clear default Xcode scheme.
"""

import sys
from typing import Optional

from core.config import ConfigManager
from core.xcode_project import (
    detect_ios_bundle_id,
    get_active_xcode_path,
    get_xcode_list_info,
)
from core import ui


def run_scheme(action: str = "list", scheme_name: Optional[str] = None):
    cfg = ConfigManager.get_instance()

    if action == "clear":
        cfg.set_selected_xcode_scheme(None)
        ui.success("Đã xóa cài đặt Xcode scheme mặc định.")
        return

    xcode_path = get_active_xcode_path()
    if xcode_path is None:
        ui.header("Quản lý Xcode Schemes")
        ui.error("Không tìm thấy .xcworkspace hoặc .xcodeproj trong dự án hiện tại.")
        sys.exit(1)

    info = get_xcode_list_info(xcode_path=xcode_path)
    if not info or not info.schemes:
        ui.header("Quản lý Xcode Schemes")
        ui.warning(f"Không tìm thấy Scheme nào trong {xcode_path.name}.")
        return

    current_default = cfg.get_selected_xcode_scheme()

    if action == "list":
        ui.header("Danh sách Xcode Schemes & Build Configurations")
        kind = "Workspace" if info.is_workspace else "Project"
        ui.detail(kind, str(info.path))
        if info.configurations:
            ui.detail("Configurations", ", ".join(info.configurations))
        if info.targets:
            ui.detail("Targets", ", ".join(info.targets))

        # Best-effort Bundle ID for default or first scheme
        probe_scheme = current_default if (current_default and current_default in info.schemes) else info.schemes[0]
        bundle_id = detect_ios_bundle_id(scheme=probe_scheme, xcode_path=xcode_path)
        if bundle_id:
            ui.detail("Bundle ID", f"{bundle_id} ({probe_scheme})")

        print(f"\nTổng số: {len(info.schemes)} schemes\n")
        for idx, s in enumerate(info.schemes):
            is_def = (s.lower() == current_default.lower()) if current_default else False
            def_tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} MẶC ĐỊNH {ui.Colors.RESET}" if is_def else ""
            print(f"  [{idx + 1}] {ui.Colors.BOLD}{s}{ui.Colors.RESET}{def_tag}")

        print()
        if current_default:
            ui.info(f"Scheme mặc định hiện tại: {ui.Colors.BOLD}{current_default}{ui.Colors.RESET}")
        else:
            ui.info("Chưa có scheme mặc định nào được lưu. Flash sẽ tự động chọn hoặc hỏi khi cần.")

    elif action == "select":
        ui.header("Chọn Xcode Scheme Mặc Định")
        scheme_map = {s.lower(): s for s in info.schemes}

        if scheme_name:
            if scheme_name.lower() in scheme_map:
                target = scheme_map[scheme_name.lower()]
                cfg.set_selected_xcode_scheme(target)
                ui.success(f"Đã lưu '{target}' làm Xcode scheme mặc định!")
                return
            ui.error(f"Scheme '{scheme_name}' không tồn tại. Các schemes hiện có: {', '.join(info.schemes)}")
            sys.exit(1)

        options = []
        default_idx = 0
        for idx, s in enumerate(info.schemes):
            options.append((s, s))
            if current_default and s.lower() == current_default.lower():
                default_idx = idx

        chosen = ui.ask_choice("Chọn Xcode scheme bạn muốn đặt làm mặc định:", options, default_idx=default_idx)
        cfg.set_selected_xcode_scheme(chosen)
        ui.success(f"Đã đặt '{chosen}' làm Xcode scheme mặc định cho các lệnh build và run!")

    else:
        ui.error(f"Hành động không hợp lệ: '{action}'. Hỗ trợ: list, select, clear.")
        sys.exit(1)
