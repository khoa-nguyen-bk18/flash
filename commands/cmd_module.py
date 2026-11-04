#!/usr/bin/env python3
"""
Target Gradle module selector and listing for multi-module projects.
"""

from core.gradle import list_modules
from core.config import ConfigManager
from core import ui

def run_module(action: str = "list"):
    cfg = ConfigManager.get_instance()
    modules = list_modules()
    current = cfg.get_target_module() or ":app"

    ui.header("Quản lý Target Module (Multi-Module Project)")
    print(f"Tổng cộng tìm thấy: {len(modules)} module(s)\n")

    for idx, mod in enumerate(modules):
        is_cur = (mod == current)
        tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} ĐANG CHỌN {ui.Colors.RESET}" if is_cur else ""
        print(f"  [{idx + 1}] {ui.Colors.BOLD}{mod}{ui.Colors.RESET}{tag}")

    print()
    if action == "select":
        opts = [(m, m) for m in modules]
        # Option to select project root
        opts.append(("(Project Root)", "(Project Root) - Chạy task ở root"))
        chosen = ui.ask_choice("Chọn module làm mục tiêu:", opts)
        cfg.set_target_module(chosen)
        ui.success(f"Đã chọn module mục tiêu: {chosen}")
