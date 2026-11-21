#!/usr/bin/env python3
"""
Platform management command for Kotlin Multiplatform (KMP) and multi-platform projects.
Allows inspecting detected platforms and pinning default target platform (android / ios).
"""

import sys
from typing import Optional
from core.config import ConfigManager
from core.project import ProjectType
from core import ui


def run_platform(action: str = "list", platform_name: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    saved = cfg.get_target_platform()

    if action == "clear":
        cfg.set_target_platform(None)
        ui.success("Đã xóa cài đặt nền tảng mặc định. Flash sẽ tự nhận diện hoặc hỏi lại khi cần.")
        return

    if action == "list":
        ui.header("Quản lý Nền tảng (Platform / KMP)")
        ui.detail("Project Root", str(ctx.root))
        ui.detail("Loại dự án", ctx.project_type.value.upper())

        if ctx.has_android:
            ui.success("Android: Phát hiện Gradle / Android project")
        if ctx.has_ios:
            xcode_label = str(ctx.active_xcode_path) if ctx.active_xcode_path else str(ctx.ios_dir)
            ui.success(f"iOS (Xcode): {xcode_label}")
        if ctx.kmp_shared_modules:
            ui.detail("KMP Modules", ", ".join(ctx.kmp_shared_modules))

        print()
        if saved:
            ui.info(f"Nền tảng mặc định đã lưu: {ui.Colors.BOLD}{saved}{ui.Colors.RESET}")
        else:
            ui.info("Chưa ghim nền tảng mặc định (chế độ auto).")
        ui.info("Gợi ý: dùng 'flash platform select ios' hoặc 'flash --ios <command>' để chạy trực tiếp.")
        return

    if action == "select":
        ui.header("Chọn Nền tảng Mặc định (KMP)")
        available = []
        if ctx.has_android or ctx.project_type == ProjectType.UNKNOWN:
            available.append(("android", "🤖 Android (Gradle / ADB)"))
        if ctx.has_ios or ctx.project_type == ProjectType.UNKNOWN:
            available.append(("ios", "🍎 iOS (Xcode / Simulator & Physical Device)"))

        if platform_name:
            p_lower = platform_name.lower()
            if p_lower not in ("android", "ios"):
                ui.error(f"Nền tảng '{platform_name}' không hợp lệ. Chỉ hỗ trợ: android, ios.")
                sys.exit(1)
            cfg.set_target_platform(p_lower)
            ui.success(f"Đã đặt '{p_lower}' làm nền tảng mặc định cho dự án!")
            return

        default_idx = 1 if saved == "ios" and len(available) > 1 else 0
        chosen = ui.ask_choice("Chọn nền tảng mặc định:", available, default_idx=default_idx)
        cfg.set_target_platform(chosen)
        ui.success(f"Đã đặt '{chosen}' làm nền tảng mặc định!")
