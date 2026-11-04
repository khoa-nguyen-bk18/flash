#!/usr/bin/env python3
"""
Real-time colored Logcat streamer with smart App, Tag, and Level filters.
"""

import sys
import re
import subprocess
import threading
import time
from typing import Optional
from core.device import resolve_target_device
from core.package_detector import detect_package_name
from core.config import ConfigManager
from core import ui

def colorize_log_line(line: str) -> str:
    """Colorize standard Logcat lines based on log level."""
    # Common format: MM-DD HH:MM:SS.ms PID TID LEVEL TAG: MESSAGE
    m = re.search(r'\s+([VDIWEF])\s+([A-Za-z0-9_\-.$]+)\s*:\s*(.*)', line)
    if m:
        level = m.group(1)
        tag = m.group(2)
        msg = m.group(3)
        prefix = line[:m.start(1)]

        if level == "V":
            color = ui.Colors.DIM
        elif level == "D":
            color = ui.Colors.BLUE
        elif level == "I":
            color = ui.Colors.GREEN
        elif level == "W":
            color = ui.Colors.YELLOW
        elif level == "E":
            color = ui.Colors.RED + ui.Colors.BOLD
        elif level == "F":
            color = ui.Colors.BG_RED + ui.Colors.WHITE + ui.Colors.BOLD
        else:
            color = ""

        return f"{ui.Colors.DIM}{prefix}{ui.Colors.RESET}{color}{level} {ui.Colors.BOLD}{tag}{ui.Colors.RESET}: {color}{msg}{ui.Colors.RESET}"

    # Fallback search for Error/Fatal
    if " E " in line or "FATAL" in line or "Exception" in line:
        return f"{ui.Colors.RED}{line}{ui.Colors.RESET}"
    if " W " in line or "Warning" in line:
        return f"{ui.Colors.YELLOW}{line}{ui.Colors.RESET}"
    return line


def get_app_pid(serial: str, package_name: str) -> Optional[str]:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    try:
        res = subprocess.run([adb, "-s", serial, "shell", f"pidof -s {package_name}"],
                             capture_output=True, text=True, timeout=3)
        pid = res.stdout.strip()
        if pid and pid.isdigit():
            return pid
    except Exception:
        pass
    return None


def run_logcat(app_filter: Optional[str] = None, tag_filter: Optional[str] = None,
               level: Optional[str] = None, clear: bool = False, device_id: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    dev = resolve_target_device(device_arg=device_id)
    if not dev:
        sys.exit(1)

    if clear:
        ui.info(f"Đang xóa bộ đệm Logcat trên {dev.model or dev.serial}...")
        subprocess.run([adb, "-s", dev.serial, "logcat", "-c"])
        ui.success("Đã xóa bộ đệm Logcat thành công.")
        return

    # Determine Package if app filter requested
    pkg = None
    if app_filter is not None:
        if app_filter:
            pkg = app_filter
        else:
            # Auto-detect package from project
            pkg = detect_package_name(serial=dev.serial)
            if not pkg:
                pkg = ui.ask_input("Nhập Package Name cần lọc (ví dụ: com.devindie.ghi)")

    ui.header(f"Logcat Stream - [{dev.model or dev.serial}]")
    if pkg:
        ui.detail("Lọc theo App", pkg)
    if tag_filter:
        ui.detail("Lọc theo TAG", tag_filter)
    if level:
        ui.detail("Mức log tối thiểu", level.upper())
    print(f"{ui.Colors.DIM}Bấm Ctrl+C để dừng Logcat.{ui.Colors.RESET}\n")

    # Build command
    cmd = [adb, "-s", dev.serial, "logcat", "-v", "time"]

    if level:
        cmd.extend(["*:" + level.upper()])

    if tag_filter:
        cmd.extend(["-s", f"{tag_filter}:*"])

    # If filtering by app, attempt to obtain PID
    target_pid = None
    if pkg and not tag_filter:
        target_pid = get_app_pid(dev.serial, pkg)
        if target_pid:
            ui.info(f"Tìm thấy tiến trình đang chạy: PID {target_pid}")
            cmd.extend(["--pid", target_pid])
        else:
            ui.info(f"Ứng dụng {pkg} hiện chưa chạy. Đang stream log và tự động lọc theo chuỗi package...")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    try:
        for line in proc.stdout:
            line_str = line.rstrip()
            if not line_str:
                continue

            # If no target_pid was found, filter client-side by package name
            if pkg and not target_pid:
                if pkg in line_str:
                    print(colorize_log_line(line_str))
            else:
                print(colorize_log_line(line_str))

    except KeyboardInterrupt:
        print()
        ui.info("Đã dừng theo dõi Logcat.")
    finally:
        proc.terminate()
