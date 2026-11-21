#!/usr/bin/env python3
"""
Flavor management command: list, select, and clear target productFlavor.
"""

import sys
from typing import Optional
from core.gradle import (
    get_product_flavors,
    get_flavor_combinations,
    get_build_variants,
    get_flavor_dimensions,
)
from core.package_detector import get_package_from_gradle
from core.config import ConfigManager
from core import ui

def run_flavor(action: str = "list", flavor_name: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    mod = cfg.get_target_module()
    raw_flavors = get_product_flavors(module=mod)
    combos = get_flavor_combinations(module=mod)
    variants = get_build_variants(module=mod)

    if not raw_flavors and action != "clear":
        ui.header("Quản lý Product Flavors")
        ui.warning("Không tìm thấy productFlavors nào được định nghĩa trong module hiện tại.")
        if variants:
            print(f"Build Types hiện có: {', '.join(v.build_type for v in variants)}")
        return

    current_default = cfg.get_selected_flavor()

    if action == "list":
        ui.header("Danh sách Product Flavors & Build Variants")
        if mod:
            ui.detail("Module", mod)

        dims = get_flavor_dimensions(module=mod)
        if dims:
            ui.detail("Flavor Dimensions", ", ".join(dims))

        base_pkg = get_package_from_gradle(module=mod) or "com.example.app"

        # If multi-dimension matrix exists, show raw flavors first as a summary, then full combinations
        is_matrix = any(c.flavors and len(c.flavors) > 1 for c in combos)
        if is_matrix:
            print(f"\nProduct Flavors ({len(raw_flavors)} flavors):")
            for f in raw_flavors:
                dim_str = f" [{f.dimension}]" if f.dimension else ""
                suf_str = f" (suffix: {f.application_id_suffix})" if f.application_id_suffix else ""
                print(f"  • {ui.Colors.BOLD}{f.name}{ui.Colors.RESET}{dim_str}{suf_str}")

            print(f"\nFlavor Matrix ({len(combos)} tổ hợp):")
        else:
            print(f"\nTổng số: {len(combos)} flavors\n")

        for idx, f in enumerate(combos):
            is_def = (f.name.lower() == current_default.lower()) if current_default else False
            def_tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} MẶC ĐỊNH {ui.Colors.RESET}" if is_def else ""
            pkg = f"{base_pkg}{f.application_id_suffix}" if f.application_id_suffix else base_pkg
            print(f"  [{idx + 1}] {ui.Colors.BOLD}{f.name}{ui.Colors.RESET}{def_tag}")
            if f.dimension:
                label = "      Matrix" if is_matrix else "      Dimension"
                ui.detail(label, f.dimension)
            if f.application_id_suffix:
                ui.detail("      Suffix", f.application_id_suffix)
            ui.detail("      Package ID", pkg)
            print()

        if variants:
            ui.detail("Build Variants", ", ".join(v.name for v in variants))

        if current_default:
            ui.info(f"Flavor mặc định hiện tại: {ui.Colors.BOLD}{current_default}{ui.Colors.RESET}")
        else:
            ui.info("Chưa có flavor mặc định nào được lưu. Flash sẽ hỏi khi cần.")

    elif action == "select":
        ui.header("Chọn Product Flavor Mặc Định")
        flavor_map = {f.name.lower(): f for f in combos}

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
        for idx, f in enumerate(combos):
            desc = f"{f.name}"
            parts = []
            if f.dimension:
                parts.append(f.dimension)
            if f.application_id_suffix:
                parts.append(f"suffix: {f.application_id_suffix}")
            if parts:
                desc += f" ({', '.join(parts)})"
            options.append((f.name, desc))
            if current_default and f.name.lower() == current_default.lower():
                default_idx = idx

        chosen = ui.ask_choice("Chọn flavor bạn muốn đặt làm mặc định:", options, default_idx=default_idx)
        cfg.set_selected_flavor(chosen)
        ui.success(f"Đã đặt '{chosen}' làm flavor mặc định cho các lệnh build và run!")

    elif action == "clear":
        cfg.set_selected_flavor(None)
        ui.success("Đã xóa cài đặt flavor mặc định.")
