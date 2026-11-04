#!/usr/bin/env python3
"""
Device listing, selection, and live event monitoring.
"""

import sys
from core.device import get_connected_devices, watch_devices
from core.config import ConfigManager
from core import ui

def run_devices(watch: bool = False, select: bool = False):
    if watch:
        watch_devices()
        return

    devs = get_connected_devices()
    cfg = ConfigManager.get_instance()
    default_dev = cfg.get_selected_device()

    ui.header("Danh sách thiết bị kết nối")
    if not devs:
        ui.warning("Không có thiết bị hoặc emulator nào đang kết nối.")
        ui.info("Dùng 'flash wireless setup' để kết nối không dây hoặc cắm cáp USB.")
        return

    print(f"Tổng số: {len(devs)} thiết bị\n")
    for idx, d in enumerate(devs):
        is_default = (d.serial == default_dev)
        def_tag = f" {ui.Colors.BG_GREEN}{ui.Colors.BLACK} MẶC ĐỊNH {ui.Colors.RESET}" if is_default else ""
        print(f"  [{idx + 1}] {d.display_name}{def_tag}")
        ui.detail("      Serial/IP", d.serial)
        if d.model:
            ui.detail("      Model", d.model)
        if d.product:
            ui.detail("      Product", d.product)

    print()
    if select:
        options = [(d.serial, d.display_name) for d in devs]
        chosen = ui.ask_choice("Chọn thiết bị làm mặc định:", options)
        cfg.set_selected_device(chosen)
        ui.success(f"Đã đặt thiết bị mặc định: {chosen}")
