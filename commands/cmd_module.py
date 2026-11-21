#!/usr/bin/env python3
"""
Target Gradle module selector and listing for multi-module projects.
"""

from typing import Optional
from core.gradle import list_modules
from core.config import ConfigManager
from core import ui


def run_ios_module(action: str = "list"):
    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    entries = ctx.all_xcode_entries
    active = ctx.active_xcode_path

    ui.header("Quản lý Xcode Project / Workspace")
    if not entries:
        ui.warning("Không tìm thấy file .xcworkspace hoặc .xcodeproj nào trong dự án.")
        return

    print(f"Tổng cộng tìm thấy: {len(entries)} Xcode project/workspace\n")
    for idx, entry in enumerate(entries):
        is_cur = active is not None and entry.resolve() == active.resolve()
        tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} ĐANG CHỌN {ui.Colors.RESET}" if is_cur else ""
        try:
            rel = str(entry.relative_to(ctx.root))
        except ValueError:
            rel = str(entry)
        kind = "Workspace" if entry.suffix == ".xcworkspace" else "Project"
        print(f"  [{idx + 1}] {ui.Colors.BOLD}{rel}{ui.Colors.RESET} ({kind}){tag}")

    if ctx.kmp_shared_modules:
        print()
        ui.detail("KMP Shared Modules", ", ".join(ctx.kmp_shared_modules))

    print()
    if action == "select":
        opts = []
        for entry in entries:
            try:
                rel = str(entry.relative_to(ctx.root))
            except ValueError:
                rel = str(entry)
            opts.append((rel, rel))
        chosen = ui.ask_choice("Chọn Xcode project/workspace mục tiêu:", opts)
        cfg.set_selected_xcode_project(chosen)
        ui.success(f"Đã chọn Xcode project mục tiêu: {chosen}")


def run_module(action: str = "list", platform: Optional[str] = None):
    if platform == "ios":
        run_ios_module(action=action)
        return

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
