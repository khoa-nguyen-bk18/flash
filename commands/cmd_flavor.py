#!/usr/bin/env python3
"""
Flavor management command: list, select, and clear target productFlavor.
"""

import sys
from typing import Optional
from core.gradle import get_product_flavors
from core.package_detector import get_package_from_gradle
from core.config import ConfigManager
from core import ui

def run_flavor(action: str = "list", flavor_name: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    mod = cfg.get_target_module()
    flavors = get_product_flavors(module=mod)

    if not flavors:
        ui.header("Quản lý Product Flavors")
        ui.warning("Không tìm thấy productFlavors nào được định nghĩa trong module hiện tại.")
        return

    current_default = cfg.get_selected_flavor()

    if action == "list":
        ui.header("Danh sách Product Flavors trong Project")
        if mod:
            ui.detail("Module", mod)
        print(f"Tổng số: {len(flavors)} flavors\n")

        base_pkg = get_package_from_gradle(module=mod) or "com.example.app"

        for idx, f in enumerate(flavors):
            is_def = (f.name.lower() == current_default.lower()) if current_default else False
            def_tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} MẶC ĐỊNH {ui.Colors.RESET}" if is_def else ""
            pkg = f"{base_pkg}{f.application_id_suffix}" if f.application_id_suffix else base_pkg
            print(f"  [{idx + 1}] {ui.Colors.BOLD}{f.name}{ui.Colors.RESET}{def_tag}")
            if f.dimension:
                ui.detail("      Dimension", f.dimension)
            if f.application_id_suffix:
                ui.detail("      Suffix", f.application_id_suffix)
            ui.detail("      Package ID", pkg)
            print()

        if current_default:
            ui.info(f"Flavor mặc định hiện tại: {ui.Colors.BOLD}{current_default}{ui.Colors.RESET}")
        else:
            ui.info("Chưa có flavor mặc định nào được lưu. Flash sẽ hỏi khi cần hoặc dùng flavor đầu tiên.")

    elif action == "select":
        ui.header("Chọn Product Flavor Mặc Định")
        flavor_map = {f.name.lower(): f for f in flavors}

        if flavor_name:
            if flavor_name.lower() in flavor_map:
                target = flavor_map[flavor_name.lower()].name
                cfg.set_selected_flavor(target)
                ui.success(f"Đã lưu '{target}' làm flavor mặc định!")
                return
            else:
                ui.error(f"Flavor '{flavor_name}' không tồn tại. Các flavor: {', '.join(flavor_map.keys())}")
                sys.exit(1)

        options = []
        default_idx = 0
        for idx, f in enumerate(flavors):
            desc = f"{f.name}"
            if f.application_id_suffix:
                desc += f" (suffix: {f.application_id_suffix})"
            options.append((f.name, desc))
            if current_default and f.name.lower() == current_default.lower():
                default_idx = idx

        chosen = ui.ask_choice("Chọn flavor bạn muốn đặt làm mặc định:", options, default_idx=default_idx)
        cfg.set_selected_flavor(chosen)
        ui.success(f"Đã đặt '{chosen}' làm flavor mặc định cho các lệnh build và run!")

    elif action == "clear":
        cfg.set_selected_flavor(None)
        ui.success("Đã xóa cài đặt flavor mặc định.")
