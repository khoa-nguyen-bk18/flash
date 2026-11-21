#!/usr/bin/env python3
"""
Real-time colored iOS Unified Log streamer (`log stream` on Simulator / `idevicesyslog` on Physical Device).
Zero external dependencies.
"""

import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

from core.ios_device import boot_simulator, resolve_target_ios_device
from core import ui


# Matches Apple `log stream --style compact` lines:
# 2026-11-21 08:10:12.123 Df MyApp[1234:5678] [com.example:ui] message
# Also supports full level names (Default, Info, Debug, Error, Fault).
_COMPACT_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)\s+"
    r"(Db|Debug|In|Info|I|Df|Default|Er|Error|E|Ft|Fault|F)\s+"
    r"([^\s]+)\s*(.*)$"
)


def colorize_ios_log_line(line: str) -> str:
    """Colorize Apple unified log compact format lines (Default/Info/Debug/Error/Fault)."""
    m = _COMPACT_LOG_RE.match(line)
    if m:
        ts, level, proc_info, msg = m.group(1), m.group(2), m.group(3), m.group(4)
        lvl_upper = level.upper()

        if lvl_upper in ("DB", "DEBUG"):
            color = ui.Colors.BLUE
        elif lvl_upper in ("I", "IN", "INFO"):
            color = ui.Colors.GREEN
        elif lvl_upper in ("DF", "DEFAULT"):
            color = ui.Colors.CYAN
        elif lvl_upper in ("E", "ER", "ERROR"):
            color = ui.Colors.RED + ui.Colors.BOLD
        elif lvl_upper in ("F", "FT", "FAULT"):
            color = ui.Colors.BG_RED + ui.Colors.WHITE + ui.Colors.BOLD
        else:
            color = ""

        return (
            f"{ui.Colors.DIM}{ts}{ui.Colors.RESET} "
            f"{color}{level}{ui.Colors.RESET} "
            f"{ui.Colors.BOLD}{proc_info}{ui.Colors.RESET} "
            f"{color}{msg}{ui.Colors.RESET}"
        )

    # Fallback highlighting for non-compact lines (e.g., idevicesyslog / crash traces)
    if "<Fault>" in line or "FAULT" in line or "Fatal error" in line:
        return f"{ui.Colors.BG_RED}{ui.Colors.WHITE}{ui.Colors.BOLD}{line}{ui.Colors.RESET}"
    if "<Error>" in line or " ERROR " in line or "Exception" in line or "NSError" in line:
        return f"{ui.Colors.RED}{line}{ui.Colors.RESET}"
    if "<Warning>" in line or "Warning" in line:
        return f"{ui.Colors.YELLOW}{line}{ui.Colors.RESET}"
    if "<Debug>" in line:
        return f"{ui.Colors.BLUE}{line}{ui.Colors.RESET}"
    return line


def _map_flash_log_level(level: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Map Flash log levels (V/D/I/W/E/F) to `log stream --level` argument and optional predicate.
    Returns (log_stream_level, optional_level_predicate).
    """
    if not level:
        return "default", None

    lvl = level.strip().upper()
    if lvl in ("V", "VERBOSE", "D", "DEBUG"):
        return "debug", None
    if lvl in ("I", "INFO"):
        return "info", None
    if lvl in ("W", "WARN", "WARNING", "DEFAULT"):
        return "default", None
    if lvl in ("E", "ERROR"):
        return "default", '(messageType == error OR messageType == fault)'
    if lvl in ("F", "FAULT", "FATAL"):
        return "default", '(messageType == fault)'
    return "default", None


def _escape_predicate_str(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"')


def _build_log_predicate(
    app_filter: Optional[str],
    tag_filter: Optional[str],
    level_predicate: Optional[str],
) -> Optional[str]:
    clauses: List[str] = []

    if app_filter:
        esc = _escape_predicate_str(app_filter)
        clauses.append(
            f'(process CONTAINS[c] "{esc}" OR subsystem CONTAINS[c] "{esc}" OR sender CONTAINS[c] "{esc}")'
        )
    if tag_filter:
        esc = _escape_predicate_str(tag_filter)
        clauses.append(
            f'(category CONTAINS[c] "{esc}" OR subsystem CONTAINS[c] "{esc}" OR eventMessage CONTAINS[c] "{esc}")'
        )
    if level_predicate:
        clauses.append(level_predicate)

    return " AND ".join(clauses) if clauses else None


def run_ios_logs(
    app_filter: Optional[str] = None,
    tag_filter: Optional[str] = None,
    level: Optional[str] = None,
    clear: bool = False,
    device_id: Optional[str] = None,
):
    """Stream real-time colored iOS logs from Simulator or Physical Device."""
    if sys.platform != "darwin":
        ui.error("Xem log iOS chỉ hỗ trợ trên macOS.")
        sys.exit(1)

    dev = resolve_target_ios_device(device_arg=device_id)
    if not dev:
        sys.exit(1)

    if clear:
        ui.info("Apple Unified Logging là dạng stream thời gian thực nên không cần xóa bộ đệm như Android Logcat.")
        return

    # Resolve app_filter if passed as empty string (--app without value)
    resolved_app = app_filter
    if app_filter == "":
        resolved_app = ui.ask_input("Nhập tên tiến trình hoặc Bundle ID cần lọc (ví dụ: MyApp hoặc com.example.app)")

    # Physical device handling
    if dev.is_physical:
        idevicesyslog = shutil.which("idevicesyslog")
        if idevicesyslog:
            ui.header(f"iOS Syslog Stream - [{dev.name}]")
            if resolved_app:
                ui.detail("Lọc theo App", resolved_app)
            if tag_filter:
                ui.detail("Lọc theo TAG", tag_filter)
            print(f"{ui.Colors.DIM}Bấm Ctrl+C để dừng xem log.{ui.Colors.RESET}\n")

            proc = subprocess.Popen(
                [idevicesyslog, "-u", dev.udid],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line_str = line.rstrip()
                    if not line_str:
                        continue
                    if resolved_app and resolved_app.lower() not in line_str.lower():
                        continue
                    if tag_filter and tag_filter.lower() not in line_str.lower():
                        continue
                    print(colorize_ios_log_line(line_str))
            except KeyboardInterrupt:
                print()
                ui.info("Đã dừng theo dõi iOS logs.")
            finally:
                proc.terminate()
            return

        ui.header(f"iOS Logs - Thiết bị thật [{dev.name}]")
        ui.warning("Không tìm thấy 'idevicesyslog' để stream toàn bộ syslog từ thiết bị thật.")
        ui.info("Bạn có thể xem log trực tiếp trên thiết bị thật bằng một trong các cách sau:")
        print(f"  1. Dùng {ui.Colors.BOLD}flash run --logcat{ui.Colors.RESET} (gắn console trực tiếp khi khởi chạy ứng dụng)")
        print(
            f"  2. Dùng Apple CLI: {ui.Colors.CYAN}xcrun devicectl device process launch --console "
            f"--device {dev.devicectl_identifier} <BUNDLE_ID>{ui.Colors.RESET}"
        )
        print(f"  3. Cài đặt libimobiledevice: {ui.Colors.CYAN}brew install libimobiledevice{ui.Colors.RESET} (cung cấp idevicesyslog)")
        return

    # Simulator handling via `xcrun simctl spawn <udid> log stream`
    xcrun = shutil.which("xcrun")
    if not xcrun:
        ui.error("Không tìm thấy 'xcrun'. Hãy cài đặt Xcode Command Line Tools.")
        sys.exit(1)

    if not dev.is_online:
        if not boot_simulator(dev, open_simulator_app=False):
            sys.exit(1)

    mapped_level, level_pred = _map_flash_log_level(level)
    predicate = _build_log_predicate(resolved_app, tag_filter, level_pred)

    ui.header(f"iOS Log Stream - [{dev.name} ({dev.os_version})]")
    if resolved_app:
        ui.detail("Lọc theo App", resolved_app)
    if tag_filter:
        ui.detail("Lọc theo TAG", tag_filter)
    ui.detail("Mức log (log stream)", mapped_level + (f" ({level.upper()})" if level else ""))
    if predicate:
        ui.detail("Predicate", predicate)
    print(f"{ui.Colors.DIM}Bấm Ctrl+C để dừng theo dõi log.{ui.Colors.RESET}\n")

    cmd = [
        xcrun, "simctl", "spawn", dev.udid,
        "log", "stream",
        "--style", "compact",
        "--level", mapped_level,
    ]
    if predicate:
        cmd.extend(["--predicate", predicate])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line_str = line.rstrip()
            if not line_str:
                continue
            print(colorize_ios_log_line(line_str))
    except KeyboardInterrupt:
        print()
        ui.info("Đã dừng theo dõi iOS logs.")
    finally:
        proc.terminate()
