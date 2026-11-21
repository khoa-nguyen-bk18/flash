#!/usr/bin/env python3
"""
iOS App & Simulator Actions.
Uses `xcrun simctl` for Simulators and `xcrun devicectl` for Physical Devices (Xcode 15+ / iOS 17+),
with fallback to `ios-deploy` if installed in PATH for older iOS < 17 physical devices.
Zero external dependencies.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from .ios_device import IOSDeviceInfo, boot_simulator
from . import ui


def _get_xcrun() -> Optional[str]:
    if sys.platform != "darwin":
        ui.error("Các thao tác iOS chỉ hỗ trợ trên macOS.")
        return None
    xcrun = shutil.which("xcrun")
    if not xcrun:
        ui.error("Không tìm thấy 'xcrun'. Hãy cài đặt Xcode Command Line Tools.")
        return None
    return xcrun


def _ensure_simulator_booted(dev: IOSDeviceInfo) -> bool:
    if dev.is_simulator and not dev.is_online:
        return boot_simulator(dev, open_simulator_app=True)
    return True


def ios_install_app(dev: IOSDeviceInfo, app_path: Path) -> bool:
    """Install a .app bundle onto an iOS Simulator or Physical Device."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    app_p = Path(app_path)
    if not app_p.exists():
        ui.error(f"Không tìm thấy gói ứng dụng: {app_p}")
        return False

    if dev.is_simulator:
        if not _ensure_simulator_booted(dev):
            return False
        ui.info(f"Đang cài đặt {app_p.name} lên Simulator {dev.name}...")
        res = subprocess.run(
            [xcrun, "simctl", "install", dev.udid, str(app_p)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã cài đặt {app_p.name} lên {dev.name}.")
            return True
        ui.error(f"Cài đặt thất bại: {(res.stderr or res.stdout).strip()}")
        return False

    # Physical device via devicectl
    ui.info(f"Đang cài đặt {app_p.name} lên thiết bị {dev.name}...")
    res = subprocess.run(
        [xcrun, "devicectl", "device", "install", "app", "--device", dev.devicectl_identifier, str(app_p)],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã cài đặt {app_p.name} lên {dev.name}.")
        return True

    # Fallback to ios-deploy for older iOS < 17 devices
    ios_deploy = shutil.which("ios-deploy")
    if ios_deploy:
        ui.warning("devicectl thất bại, đang thử fallback bằng 'ios-deploy'...")
        fb = subprocess.run(
            [ios_deploy, "--id", dev.udid, "--bundle", str(app_p)],
            capture_output=True,
            text=True,
        )
        if fb.returncode == 0:
            ui.success(f"Đã cài đặt {app_p.name} lên {dev.name} (qua ios-deploy).")
            return True
        ui.error(f"ios-deploy thất bại: {(fb.stderr or fb.stdout).strip()}")
        return False

    ui.error(f"Cài đặt lên thiết bị thật thất bại: {(res.stderr or res.stdout).strip()}")
    ui.info("Gợi ý: Với iOS < 17, bạn có thể cài 'brew install ios-deploy' để hỗ trợ fallback.")
    return False


def ios_launch_app(dev: IOSDeviceInfo, bundle_id: str) -> bool:
    """Launch an installed iOS app by Bundle ID."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if dev.is_simulator:
        if not _ensure_simulator_booted(dev):
            return False
        res = subprocess.run(
            [xcrun, "simctl", "launch", dev.udid, bundle_id],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã mở ứng dụng {bundle_id} trên {dev.name}.")
            return True
        ui.error(f"Không thể mở ứng dụng {bundle_id}: {(res.stderr or res.stdout).strip()}")
        return False

    res = subprocess.run(
        [xcrun, "devicectl", "device", "process", "launch", "--device", dev.devicectl_identifier, bundle_id],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã mở ứng dụng {bundle_id} trên {dev.name}.")
        return True

    ui.error(f"Không thể mở ứng dụng trên thiết bị thật: {(res.stderr or res.stdout).strip()}")
    return False


def _find_physical_app_pid(xcrun: str, dev: IOSDeviceInfo, bundle_id: str) -> Optional[int]:
    """Query running processes via devicectl and locate PID matching bundle_id."""
    try:
        with tempfile.TemporaryDirectory(prefix="flash_procs_") as tmpdir:
            out_path = Path(tmpdir) / "procs.json"
            res = subprocess.run(
                [
                    xcrun, "devicectl", "device", "info", "processes",
                    "--device", dev.devicectl_identifier,
                    "--json-output", str(out_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0 or not out_path.is_file():
                return None
            data = json.loads(out_path.read_text(encoding="utf-8", errors="ignore"))
            procs = data.get("result", {}).get("runningProcesses", [])
            for p in procs:
                exe = str(p.get("executable", ""))
                if bundle_id in exe or str(p.get("bundleIdentifier", "")) == bundle_id:
                    pid = p.get("processIdentifier")
                    if isinstance(pid, int):
                        return pid
    except Exception:
        pass
    return None


def ios_terminate_app(dev: IOSDeviceInfo, bundle_id: str) -> bool:
    """Force-stop / terminate an iOS app."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if dev.is_simulator:
        if not dev.is_online:
            ui.info(f"Simulator {dev.name} đang tắt, không cần dừng ứng dụng.")
            return True
        res = subprocess.run(
            [xcrun, "simctl", "terminate", dev.udid, bundle_id],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã dừng ứng dụng {bundle_id} trên {dev.name}.")
            return True
        err_text = (res.stderr or res.stdout or "").strip()
        if "found nothing to terminate" in err_text.lower() or "not running" in err_text.lower():
            ui.info(f"Ứng dụng {bundle_id} hiện không chạy trên {dev.name}.")
            return True
        ui.error(f"Không thể dừng ứng dụng: {err_text}")
        return False

    pid = _find_physical_app_pid(xcrun, dev, bundle_id)
    if pid is None:
        ui.info(f"Ứng dụng {bundle_id} hiện không chạy trên {dev.name}.")
        return True

    res = subprocess.run(
        [
            xcrun, "devicectl", "device", "process", "terminate",
            "--device", dev.devicectl_identifier,
            "--pid", str(pid),
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã dừng ứng dụng {bundle_id} (PID {pid}) trên {dev.name}.")
        return True
    ui.error(f"Không thể dừng ứng dụng trên thiết bị thật: {(res.stderr or res.stdout).strip()}")
    return False


def ios_restart_app(dev: IOSDeviceInfo, bundle_id: str) -> bool:
    """Terminate and relaunch an iOS app."""
    ios_terminate_app(dev, bundle_id)
    time.sleep(0.3)
    return ios_launch_app(dev, bundle_id)


def ios_uninstall_app(dev: IOSDeviceInfo, bundle_id: str, confirm: bool = True) -> bool:
    """Uninstall an iOS app from Simulator or Physical Device."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if confirm:
        if not ui.ask_confirm(f"Bạn có chắc muốn gỡ cài đặt '{bundle_id}' khỏi {dev.name}?", default=False):
            ui.info("Đã hủy gỡ cài đặt.")
            return False

    if dev.is_simulator:
        if not _ensure_simulator_booted(dev):
            return False
        res = subprocess.run(
            [xcrun, "simctl", "uninstall", dev.udid, bundle_id],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã gỡ cài đặt {bundle_id} khỏi {dev.name}.")
            return True
        ui.error(f"Gỡ cài đặt thất bại: {(res.stderr or res.stdout).strip()}")
        return False

    res = subprocess.run(
        [xcrun, "devicectl", "device", "uninstall", "app", "--device", dev.devicectl_identifier, bundle_id],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã gỡ cài đặt {bundle_id} khỏi {dev.name}.")
        return True

    ios_deploy = shutil.which("ios-deploy")
    if ios_deploy:
        fb = subprocess.run(
            [ios_deploy, "--id", dev.udid, "--uninstall_only", "--bundle_id", bundle_id],
            capture_output=True,
            text=True,
        )
        if fb.returncode == 0:
            ui.success(f"Đã gỡ cài đặt {bundle_id} khỏi {dev.name} (qua ios-deploy).")
            return True

    ui.error(f"Gỡ cài đặt trên thiết bị thật thất bại: {(res.stderr or res.stdout).strip()}")
    return False


def _clear_directory_contents(target_dir: Path) -> int:
    """Safely remove all files and subdirectories inside `target_dir` without deleting `target_dir` itself."""
    removed = 0
    if not target_dir.is_dir():
        return 0
    for child in target_dir.iterdir():
        try:
            if child.is_symlink() or child.is_file():
                child.unlink()
                removed += 1
            elif child.is_dir():
                shutil.rmtree(child)
                removed += 1
        except OSError:
            pass
    return removed


def ios_clear_data(dev: IOSDeviceInfo, bundle_id: str, restart: bool = False) -> bool:
    """
    Clear app data container on iOS Simulator.
    On Physical Devices, Apple sandbox restrictions prevent direct CLI container wiping.
    """
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if dev.is_physical:
        ui.warning("Không thể xóa trực tiếp dữ liệu ứng dụng trên thiết bị iOS vật lý do giới hạn Sandbox của Apple.")
        ui.info("Gợi ý: Hãy gỡ cài đặt và cài lại ứng dụng (flash uninstall && flash run) để làm sạch dữ liệu.")
        return False

    if not _ensure_simulator_booted(dev):
        return False

    # 1. Terminate running app
    ios_terminate_app(dev, bundle_id)

    # 2. Locate app data container
    res = subprocess.run(
        [xcrun, "simctl", "get_app_container", dev.udid, bundle_id, "data"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        ui.error(f"Không tìm thấy Data Container cho '{bundle_id}': {(res.stderr or res.stdout).strip()}")
        return False

    container_path = Path(res.stdout.strip())
    if not container_path.is_dir():
        ui.error(f"Đường dẫn Data Container không hợp lệ: {container_path}")
        return False

    # 3. Safely clear standard sandbox subdirectories
    sub_targets = [
        container_path / "Documents",
        container_path / "Library" / "Caches",
        container_path / "Library" / "Preferences",
        container_path / "Library" / "Application Support",
        container_path / "tmp",
    ]
    total_removed = 0
    for sub in sub_targets:
        total_removed += _clear_directory_contents(sub)

    ui.success(f"Đã xóa dữ liệu ứng dụng {bundle_id} trên {dev.name} ({total_removed} mục đã dọn dẹp).")

    if restart:
        return ios_launch_app(dev, bundle_id)
    return True


def ios_clear_restart(dev: IOSDeviceInfo, bundle_id: str) -> bool:
    """Clear app data and immediately relaunch the app."""
    return ios_clear_data(dev, bundle_id, restart=True)


def ios_grant_permissions(dev: IOSDeviceInfo, bundle_id: str) -> bool:
    """Grant all privacy permissions to an app on Simulator."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if dev.is_physical:
        ui.warning("Apple không hỗ trợ cấp quyền (privacy grant) qua CLI trên thiết bị vật lý.")
        ui.info("Vui lòng cấp quyền trực tiếp trong Settings trên iPhone/iPad.")
        return False

    if not _ensure_simulator_booted(dev):
        return False

    res = subprocess.run(
        [xcrun, "simctl", "privacy", dev.udid, "grant", "all", bundle_id],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã cấp toàn bộ quyền (privacy grant all) cho {bundle_id} trên {dev.name}.")
        return True
    ui.error(f"Cấp quyền thất bại: {(res.stderr or res.stdout).strip()}")
    return False


def ios_revoke_permissions(dev: IOSDeviceInfo, bundle_id: str, restart: bool = False) -> bool:
    """Reset/revoke all privacy permissions for an app on Simulator."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if dev.is_physical:
        ui.warning("Apple không hỗ trợ thu hồi quyền (privacy reset) qua CLI trên thiết bị vật lý.")
        ui.info("Vui lòng đặt lại quyền trực tiếp trong Settings trên iPhone/iPad.")
        return False

    if not _ensure_simulator_booted(dev):
        return False

    res = subprocess.run(
        [xcrun, "simctl", "privacy", dev.udid, "reset", "all", bundle_id],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã đặt lại toàn bộ quyền (privacy reset all) cho {bundle_id} trên {dev.name}.")
        if restart:
            return ios_restart_app(dev, bundle_id)
        return True

    ui.error(f"Đặt lại quyền thất bại: {(res.stderr or res.stdout).strip()}")
    return False


def ios_screenshot(
    dev: IOSDeviceInfo,
    output_path: Optional[str] = None,
    open_after: bool = False,
) -> bool:
    """Capture a screenshot from an iOS Simulator (or Physical Device via idevicescreenshot if installed)."""
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = Path(output_path) if output_path else Path(f"flash_ios_screenshot_{ts}.png")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if dev.is_simulator:
        if not _ensure_simulator_booted(dev):
            return False
        res = subprocess.run(
            [xcrun, "simctl", "io", dev.udid, "screenshot", str(out_file)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã chụp màn hình Simulator: {out_file.resolve()}")
            if open_after:
                subprocess.run(["open", str(out_file)], capture_output=True)
            return True
        ui.error(f"Chụp màn hình thất bại: {(res.stderr or res.stdout).strip()}")
        return False

    # Physical device fallback via libimobiledevice's idevicescreenshot
    idev_ss = shutil.which("idevicescreenshot")
    if idev_ss:
        res = subprocess.run(
            [idev_ss, "-u", dev.udid, str(out_file)],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            ui.success(f"Đã chụp màn hình thiết bị thật: {out_file.resolve()}")
            if open_after:
                subprocess.run(["open", str(out_file)], capture_output=True)
            return True
        ui.error(f"idevicescreenshot thất bại: {(res.stderr or res.stdout).strip()}")
        return False

    ui.warning("Apple devicectl chưa hỗ trợ chụp màn hình trực tiếp cho thiết bị vật lý qua CLI.")
    ui.info("Gợi ý: Cài 'brew install libimobiledevice' (cung cấp idevicescreenshot) hoặc dùng Xcode > Devices and Simulators.")
    return False


# --- Simulator-specific Extras ---

def ios_shutdown_simulator(dev: IOSDeviceInfo) -> bool:
    """Shut down a running iOS Simulator."""
    if not dev.is_simulator:
        ui.warning("Lệnh tắt Simulator chỉ áp dụng cho iOS Simulator.")
        return False
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    res = subprocess.run(
        [xcrun, "simctl", "shutdown", dev.udid],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 or "current state: Shutdown" in (res.stderr or ""):
        dev.state = "Shutdown"
        ui.success(f"Đã tắt Simulator {dev.name}.")
        return True
    ui.error(f"Không thể tắt Simulator: {(res.stderr or res.stdout).strip()}")
    return False


def ios_erase_simulator(dev: IOSDeviceInfo) -> bool:
    """Factory-reset (erase all content and settings) an iOS Simulator."""
    if not dev.is_simulator:
        ui.warning("Lệnh erase chỉ áp dụng cho iOS Simulator.")
        return False
    xcrun = _get_xcrun()
    if not xcrun:
        return False

    if not ui.ask_confirm(
        f"Bạn có chắc muốn xóa toàn bộ dữ liệu (Erase) của Simulator '{dev.name}' ({dev.os_version})?",
        default=False,
    ):
        ui.info("Đã hủy thao tác Erase Simulator.")
        return False

    if dev.is_online:
        subprocess.run([xcrun, "simctl", "shutdown", dev.udid], capture_output=True, text=True)

    res = subprocess.run(
        [xcrun, "simctl", "erase", dev.udid],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        dev.state = "Shutdown"
        ui.success(f"Đã đặt lại (Erase) Simulator {dev.name} thành công.")
        return True
    ui.error(f"Erase Simulator thất bại: {(res.stderr or res.stdout).strip()}")
    return False


def ios_toggle_appearance(dev: IOSDeviceInfo, mode: Optional[str] = None) -> bool:
    """Switch Simulator appearance between Dark and Light mode."""
    if not dev.is_simulator:
        ui.warning("Chuyển đổi giao diện Dark/Light chỉ hỗ trợ trên iOS Simulator.")
        return False
    xcrun = _get_xcrun()
    if not xcrun:
        return False
    if not _ensure_simulator_booted(dev):
        return False

    target_mode = mode.lower() if mode else None
    if target_mode is None:
        curr = subprocess.run(
            [xcrun, "simctl", "ui", dev.udid, "appearance"],
            capture_output=True,
            text=True,
        )
        current_str = (curr.stdout or "").strip().lower()
        target_mode = "light" if current_str == "dark" else "dark"

    if target_mode not in ("dark", "light"):
        ui.error(f"Chế độ giao diện không hợp lệ: '{target_mode}'. Chỉ hỗ trợ 'dark' hoặc 'light'.")
        return False

    res = subprocess.run(
        [xcrun, "simctl", "ui", dev.udid, "appearance", target_mode],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        icon = "🌙" if target_mode == "dark" else "☀️"
        ui.success(f"{icon} Đã chuyển giao diện {dev.name} sang chế độ {target_mode.upper()}.")
        return True
    ui.error(f"Không thể đổi giao diện Simulator: {(res.stderr or res.stdout).strip()}")
    return False


def ios_open_url(dev: IOSDeviceInfo, url: str) -> bool:
    """Open a deep link or URL on an iOS Simulator."""
    if not dev.is_simulator:
        ui.warning("Mở URL trực tiếp qua CLI hiện chỉ hỗ trợ trên iOS Simulator.")
        return False
    xcrun = _get_xcrun()
    if not xcrun:
        return False
    if not _ensure_simulator_booted(dev):
        return False

    res = subprocess.run(
        [xcrun, "simctl", "openurl", dev.udid, url],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        ui.success(f"Đã mở URL '{url}' trên {dev.name}.")
        return True
    ui.error(f"Không thể mở URL: {(res.stderr or res.stdout).strip()}")
    return False
