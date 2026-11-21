#!/usr/bin/env python3
"""
iOS Device & Simulator listing, default selection, and live monitoring command.
"""

from core.ios_device import get_all_ios_devices, watch_ios_devices
from core.config import ConfigManager
from core import ui


def run_ios_devices(watch: bool = False, select: bool = False):
    if watch:
        watch_ios_devices()
        return

    devs = get_all_ios_devices(include_shutdown_sims=True)
    cfg = ConfigManager.get_instance()
    default_udid = cfg.get_selected_ios_device()

    ui.header("Danh sách thiết bị iOS & Simulator")
    if not devs:
        ui.warning("Không tìm thấy thiết bị iOS hoặc Simulator nào.")
        ui.info("Kiểm tra Xcode Simulator Runtimes (Xcode > Settings > Platforms) hoặc cắm cáp USB kết nối iPhone.")
        return

    physical = [d for d in devs if d.is_physical]
    booted_sims = [d for d in devs if d.is_simulator and d.is_online]
    shutdown_sims = [d for d in devs if d.is_simulator and not d.is_online]

    print(
        f"Tổng số: {len(devs)} thiết bị "
        f"({len(physical)} thiết bị thật, {len(booted_sims)} Simulator đang chạy, {len(shutdown_sims)} Simulator đang tắt)\n"
    )

    counter = 1

    def _print_group(title: str, group):
        nonlocal counter
        if not group:
            return
        print(f"{ui.Colors.BOLD}{title}:{ui.Colors.RESET}")
        for d in group:
            is_default = (d.udid == default_udid) or (bool(d.core_device_id) and d.core_device_id == default_udid)
            def_tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} MẶC ĐỊNH {ui.Colors.RESET}" if is_default else ""
            print(f"  [{counter}] {d.display_name}{def_tag}")
            if d.is_physical:
                conn_label = "Wi-Fi" if d.connection_type == "wifi" else "USB"
                ui.detail("      Kết nối", conn_label)
                if d.model:
                    ui.detail("      Model", d.model)
            counter += 1
        print()

    _print_group("📱 Thiết bị iOS vật lý (Physical Devices)", physical)
    _print_group("📲 Simulator đang chạy (Booted)", booted_sims)
    _print_group("🖥️  Simulator khả dụng (Shutdown)", shutdown_sims)

    if select:
        options = [(d.udid, d.display_name) for d in devs]
        chosen = ui.ask_choice("Chọn thiết bị iOS / Simulator làm mặc định:", options)
        cfg.set_selected_ios_device(chosen)
        ui.success(f"Đã đặt thiết bị iOS mặc định: {chosen}")
