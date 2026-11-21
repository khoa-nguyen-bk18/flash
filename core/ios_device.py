#!/usr/bin/env python3
"""
iOS Device & Simulator detection, parsing, resolution, and live monitoring.
Uses native Apple CLI tools (xcrun simctl, xcrun devicectl, xcrun xcdevice).
Zero external dependencies.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .config import ConfigManager
from . import ui


@dataclass
class IOSDeviceInfo:
    udid: str
    name: str
    state: str  # Booted, Shutdown, Connected, Unavailable, etc.
    os_version: str = ""
    device_type: str = "simulator"  # "simulator" | "physical"
    connection_type: str = "local"  # "local" | "usb" | "wifi"
    model: str = ""
    runtime: str = ""
    core_device_id: str = ""

    @property
    def is_simulator(self) -> bool:
        return self.device_type == "simulator"

    @property
    def is_physical(self) -> bool:
        return self.device_type == "physical"

    @property
    def is_online(self) -> bool:
        state_lower = self.state.lower()
        if self.is_simulator:
            return state_lower == "booted"
        return state_lower in ("connected", "online", "available")

    @property
    def devicectl_identifier(self) -> str:
        """Identifier accepted by `xcrun devicectl --device`."""
        return self.core_device_id or self.udid

    @property
    def xcodebuild_destination(self) -> str:
        if self.is_simulator:
            return f"platform=iOS Simulator,id={self.udid}"
        return f"platform=iOS,id={self.udid}"

    @property
    def display_name(self) -> str:
        if self.is_simulator:
            icon = "📲" if self.is_online else "🖥️"
            status_dot = (
                f"{ui.Colors.GREEN}●{ui.Colors.RESET}"
                if self.is_online
                else f"{ui.Colors.DIM}○{ui.Colors.RESET}"
            )
        else:
            icon = "📶" if self.connection_type == "wifi" else "🔌"
            status_dot = (
                f"{ui.Colors.GREEN}●{ui.Colors.RESET}"
                if self.is_online
                else f"{ui.Colors.RED}●{ui.Colors.RESET}"
            )

        os_part = f" {self.os_version}" if self.os_version else ""
        state_part = f" ({self.state})" if self.state else ""
        return (
            f"{status_dot} {icon} {ui.Colors.BOLD}{self.name}{ui.Colors.RESET}"
            f"{os_part} [{ui.Colors.CYAN}{self.udid}{ui.Colors.RESET}]{state_part}"
        )


def _extract_ios_os_version_from_runtime(runtime_id: str) -> Optional[str]:
    """
    Extract readable iOS version from a CoreSimulator runtime identifier.
    Example: 'com.apple.CoreSimulator.SimRuntime.iOS-18-2' -> 'iOS 18.2'
    Returns None for non-iOS runtimes (tvOS, watchOS, xrOS/visionOS).
    """
    m = re.search(r"SimRuntime\.iOS-(\d+(?:-\d+)*)", runtime_id)
    if m:
        version_str = m.group(1).replace("-", ".")
        return f"iOS {version_str}"

    m_plain = re.match(r"^iOS\s+(\d+(?:\.\d+)*)$", runtime_id.strip(), re.IGNORECASE)
    if m_plain:
        return f"iOS {m_plain.group(1)}"

    return None


def _os_version_sort_key(os_version: str) -> Tuple[int, ...]:
    """Convert 'iOS 18.2.1' -> (18, 2, 1) for version-aware sorting."""
    nums = re.findall(r"\d+", os_version or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def parse_simctl_devices_json(raw_json: str) -> List[IOSDeviceInfo]:
    """
    Parse JSON output from `xcrun simctl list devices available -j`.
    Filters to available iOS simulators and extracts readable OS versions.
    """
    if not raw_json or not raw_json.strip():
        return []
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []

    devices_map = data.get("devices", {})
    if not isinstance(devices_map, dict):
        return []

    results: List[IOSDeviceInfo] = []
    for runtime_id, dev_list in devices_map.items():
        os_version = _extract_ios_os_version_from_runtime(str(runtime_id))
        if not os_version:
            continue
        if not isinstance(dev_list, list):
            continue

        for item in dev_list:
            if not isinstance(item, dict):
                continue
            if item.get("isAvailable") is not True:
                continue

            udid = str(item.get("udid", "")).strip()
            name = str(item.get("name", "")).strip()
            if not udid:
                continue

            state = str(item.get("state", "Shutdown")).strip() or "Shutdown"
            model = str(item.get("deviceTypeIdentifier", "")).strip()
            results.append(
                IOSDeviceInfo(
                    udid=udid,
                    name=name or udid,
                    state=state,
                    os_version=os_version,
                    device_type="simulator",
                    connection_type="local",
                    model=model,
                    runtime=str(runtime_id),
                )
            )

    return results


def parse_devicectl_devices_json(raw_json: str) -> List[IOSDeviceInfo]:
    """
    Parse JSON output from `xcrun devicectl list devices --json-output <file>`.
    Filters to iOS/iPadOS physical devices.
    """
    if not raw_json or not raw_json.strip():
        return []
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return []

    result_obj = data.get("result", {})
    if not isinstance(result_obj, dict):
        return []

    raw_devices = result_obj.get("devices", [])
    if not isinstance(raw_devices, list):
        return []

    results: List[IOSDeviceInfo] = []
    for item in raw_devices:
        if not isinstance(item, dict):
            continue

        hw = item.get("hardwareProperties") or {}
        dev_props = item.get("deviceProperties") or {}
        conn = item.get("connectionProperties") or {}

        platform = str(hw.get("platform", "")).strip()
        if platform.lower() not in ("ios", "ipados"):
            continue

        reality = str(hw.get("reality", "physical")).strip().lower()
        if reality and reality != "physical":
            continue

        core_device_id = str(item.get("identifier", "")).strip()
        udid = str(hw.get("udid", "")).strip() or core_device_id
        if not udid:
            continue

        name = (
            str(dev_props.get("name", "")).strip()
            or str(hw.get("marketingName", "")).strip()
            or udid
        )

        os_ver_raw = str(dev_props.get("osVersionNumber", "")).strip()
        if os_ver_raw:
            os_version = os_ver_raw if os_ver_raw.lower().startswith("ios") else f"iOS {os_ver_raw}"
        else:
            os_version = ""

        model = (
            str(hw.get("marketingName", "")).strip()
            or str(hw.get("productType", "")).strip()
        )

        transport = str(conn.get("transportType", "")).strip().lower()
        if transport in ("localnetwork", "wifi", "network"):
            connection_type = "wifi"
        else:
            connection_type = "usb"

        tunnel_state = str(conn.get("tunnelState", "")).strip().lower()
        pairing_state = str(conn.get("pairingState", "")).strip().lower()
        transport_active = transport in ("wired", "usb", "localnetwork", "wifi", "network")

        if tunnel_state in ("connected", "available") or (
            pairing_state == "paired" and transport_active and tunnel_state != "unavailable"
        ):
            state = "Connected"
        else:
            state = "Unavailable"

        results.append(
            IOSDeviceInfo(
                udid=udid,
                name=name,
                state=state,
                os_version=os_version,
                device_type="physical",
                connection_type=connection_type,
                model=model,
                runtime="",
                core_device_id=core_device_id,
            )
        )

    return results


def get_ios_simulators() -> List[IOSDeviceInfo]:
    """Query available iOS simulators via `xcrun simctl`."""
    if sys.platform != "darwin":
        return []
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return []

    try:
        res = subprocess.run(
            [xcrun, "simctl", "list", "devices", "available", "-j"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode != 0:
            return []
        return parse_simctl_devices_json(res.stdout)
    except Exception:
        return []


def get_ios_physical_devices() -> List[IOSDeviceInfo]:
    """Query physical iOS devices via `xcrun devicectl`."""
    if sys.platform != "darwin":
        return []
    xcrun = shutil.which("xcrun")
    if not xcrun:
        return []

    try:
        with tempfile.TemporaryDirectory(prefix="flash_devicectl_") as tmpdir:
            out_path = Path(tmpdir) / "devices.json"
            res = subprocess.run(
                [xcrun, "devicectl", "list", "devices", "--json-output", str(out_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode != 0 or not out_path.is_file():
                return []
            raw = out_path.read_text(encoding="utf-8", errors="ignore")
            return parse_devicectl_devices_json(raw)
    except Exception:
        return []


def get_all_ios_devices(include_shutdown_sims: bool = True) -> List[IOSDeviceInfo]:
    """
    Return all discovered iOS devices sorted by priority:
      1. Connected Physical Devices
      2. Booted Simulators
      3. Shutdown Simulators (newest OS version first)
      4. Unavailable Physical Devices
    """
    physical = get_ios_physical_devices()
    simulators = get_ios_simulators()

    if not include_shutdown_sims:
        simulators = [s for s in simulators if s.is_online]

    combined = physical + simulators

    def _sort_key(dev: IOSDeviceInfo):
        if dev.is_physical and dev.is_online:
            group = 0
        elif dev.is_simulator and dev.is_online:
            group = 1
        elif dev.is_simulator:
            group = 2
        else:
            group = 3

        ver_nums = _os_version_sort_key(dev.os_version)
        # Pad to 3 components and negate for descending version sort
        padded = (ver_nums + (0, 0, 0))[:3]
        neg_ver = tuple(-v for v in padded)
        return (group, neg_ver, dev.name.lower())

    combined.sort(key=_sort_key)
    return combined


def boot_simulator(device: IOSDeviceInfo, open_simulator_app: bool = True) -> bool:
    """Boot an iOS Simulator and wait until it is ready."""
    if not device.is_simulator:
        return True
    if sys.platform != "darwin":
        ui.error("iOS Simulator chỉ hỗ trợ trên macOS.")
        return False

    xcrun = shutil.which("xcrun")
    if not xcrun:
        ui.error("Không tìm thấy 'xcrun'. Hãy cài đặt Xcode Command Line Tools.")
        return False

    ui.info(f"Đang khởi động Simulator {device.name} ({device.os_version})...")
    try:
        res = subprocess.run(
            [xcrun, "simctl", "boot", device.udid],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            err_text = (res.stderr or "") + (res.stdout or "")
            if "current state: Booted" not in err_text:
                ui.error(f"Không thể khởi động Simulator: {err_text.strip()}")
                return False

        boot_res = subprocess.run(
            [xcrun, "simctl", "bootstatus", device.udid, "-b"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if boot_res.returncode != 0:
            err_text = (boot_res.stderr or boot_res.stdout or "").strip()
            ui.error(f"Simulator bootstatus thất bại: {err_text}")
            return False

        device.state = "Booted"

        if open_simulator_app:
            try:
                subprocess.run(["open", "-a", "Simulator"], capture_output=True, timeout=10)
            except Exception:
                pass

        ui.success(f"Simulator {device.name} đã sẵn sàng!")
        return True
    except subprocess.TimeoutExpired:
        ui.error("Hết thời gian chờ khởi động Simulator.")
        return False
    except Exception as e:
        ui.error(f"Lỗi khi khởi động Simulator: {e}")
        return False


def _match_ios_device(devices: List[IOSDeviceInfo], query: str) -> Optional[IOSDeviceInfo]:
    """Match an iOS device by exact UDID, CoreDevice ID, prefix/substring, or name."""
    q_lower = query.lower()
    for d in devices:
        if d.udid == query or (d.core_device_id and d.core_device_id == query):
            return d
    for d in devices:
        if q_lower in d.udid.lower() or q_lower == d.name.lower():
            return d
    for d in devices:
        if q_lower in d.name.lower():
            return d
    return None


def resolve_target_ios_device(
    device_arg: Optional[str] = None,
    interactive: bool = True,
) -> Optional[IOSDeviceInfo]:
    """Resolve a single target iOS device or simulator."""
    devices = get_all_ios_devices(include_shutdown_sims=True)
    if not devices:
        ui.error("Không tìm thấy thiết bị iOS hoặc Simulator nào!")
        ui.info("Kiểm tra: 1) Đang chạy trên macOS có Xcode  2) Đã cài iOS Simulator Runtime hoặc cắm iPhone.")
        return None

    if device_arg:
        matched = _match_ios_device(devices, device_arg)
        if matched:
            return matched
        ui.error(f"Không tìm thấy thiết bị iOS '{device_arg}'.")
        return None

    cfg = ConfigManager.get_instance()
    saved = cfg.get_selected_ios_device()
    if saved:
        for d in devices:
            if d.udid == saved or (d.core_device_id and d.core_device_id == saved):
                return d

    online_devices = [d for d in devices if d.is_online]
    if len(online_devices) == 1:
        return online_devices[0]

    if not interactive:
        return online_devices[0] if online_devices else devices[0]

    options = [(d.udid, d.display_name) for d in devices]
    chosen = ui.ask_choice("Chọn thiết bị iOS / Simulator:", options)
    for d in devices:
        if d.udid == chosen:
            cfg.set_selected_ios_device(d.udid)
            return d

    return devices[0]


def resolve_target_ios_devices(
    device_arg: Optional[str] = None,
    interactive: bool = True,
) -> List[IOSDeviceInfo]:
    """
    Resolve one or more target iOS devices/simulators for execution.
    Mirrors `core/device.py:resolve_target_devices` with `ui.ask_multiselect`.
    """
    devices = get_all_ios_devices(include_shutdown_sims=True)
    if not devices:
        ui.error("Không tìm thấy thiết bị iOS hoặc Simulator nào!")
        ui.info("Kiểm tra: 1) Đang chạy trên macOS có Xcode  2) Đã cài iOS Simulator Runtime hoặc cắm iPhone.")
        return []

    if device_arg:
        matched = _match_ios_device(devices, device_arg)
        if matched:
            return [matched]
        ui.error(f"Không tìm thấy thiết bị iOS '{device_arg}'.")
        return []

    if len(devices) == 1:
        return devices

    online_devices = [d for d in devices if d.is_online]
    if len(online_devices) == 1:
        return online_devices

    if not interactive:
        return online_devices if online_devices else [devices[0]]

    # When multiple online devices exist, present them; otherwise show all available simulators
    pool = online_devices if len(online_devices) > 1 else devices
    options = [(d.udid, d.display_name) for d in pool]
    all_label = (
        "⚡ Run all (Tất cả thiết bị iOS đang hoạt động)"
        if len(online_devices) > 1
        else "⚡ Run all (Tất cả thiết bị iOS)"
    )

    chosen_udids = ui.ask_multiselect(
        title="Có nhiều thiết bị iOS / Simulator. Vui lòng chọn thiết bị:",
        options=options,
        all_label=all_label,
        default="1" if len(online_devices) == 0 else "a",
    )

    selected = [d for d in pool if d.udid in chosen_udids]
    return selected if selected else [pool[0]]


def _print_ios_device_snapshot(devs: List[IOSDeviceInfo], header_prefix: str = ""):
    online = [d for d in devs if d.is_online]
    if header_prefix:
        print(f"{header_prefix} ({len(online)} đang hoạt động / {len(devs)} tổng số)")
    else:
        print(f"{ui.Colors.BOLD}Thiết bị iOS hiện tại ({len(online)} đang hoạt động / {len(devs)} tổng số):{ui.Colors.RESET}")
    for d in online:
        print(f"  {d.display_name}")
    if not online:
        print(f"  {ui.Colors.DIM}(Chưa có thiết bị vật lý kết nối hoặc Simulator nào đang Booted){ui.Colors.RESET}")
    print()


def watch_ios_devices():
    """
    Monitor iOS physical devices & simulators in real time using `xcrun xcdevice observe`,
    with lightweight fallback polling if `xcdevice observe` is unavailable.
    """
    if sys.platform != "darwin":
        ui.error("Giám sát thiết bị iOS chỉ hỗ trợ trên macOS.")
        return

    xcrun = shutil.which("xcrun")
    if not xcrun:
        ui.error("Không tìm thấy 'xcrun'. Hãy cài đặt Xcode Command Line Tools.")
        return

    ui.header("Giám sát thiết bị iOS theo thời gian thực (xcdevice observe)")
    ui.info("Cắm/rút iPhone hoặc bật/tắt Simulator để thấy trạng thái thay đổi. Bấm Ctrl+C để thoát.\n")

    devs = get_all_ios_devices(include_shutdown_sims=True)
    _print_ios_device_snapshot(devs)

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            [xcrun, "xcdevice", "observe"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Brief check to see if xcdevice observe exited immediately with error
        time.sleep(0.4)
        if proc.poll() is not None and proc.returncode != 0:
            raise RuntimeError("xcdevice observe unavailable")

        assert proc.stdout is not None
        for line in proc.stdout:
            if not line.strip():
                continue
            time.sleep(0.5)  # Debounce rapid events
            updated = get_all_ios_devices(include_shutdown_sims=True)
            ts = time.strftime("%H:%M:%S")
            _print_ios_device_snapshot(
                updated,
                header_prefix=f"[{ts}] {ui.Colors.YELLOW}⚡ Trạng thái thiết bị iOS thay đổi:{ui.Colors.RESET}",
            )
    except KeyboardInterrupt:
        print()
        ui.info("Dừng giám sát thiết bị iOS.")
    except Exception:
        # Lightweight fallback polling
        ui.warning("xcdevice observe không khả dụng, chuyển sang chế độ polling nhẹ (mỗi 2 giây)...")
        last_sig = [(d.udid, d.state) for d in devs]
        try:
            while True:
                time.sleep(2.0)
                updated = get_all_ios_devices(include_shutdown_sims=True)
                sig = [(d.udid, d.state) for d in updated]
                if sig != last_sig:
                    last_sig = sig
                    ts = time.strftime("%H:%M:%S")
                    _print_ios_device_snapshot(
                        updated,
                        header_prefix=f"[{ts}] {ui.Colors.YELLOW}⚡ Trạng thái thiết bị iOS thay đổi:{ui.Colors.RESET}",
                    )
        except KeyboardInterrupt:
            print()
            ui.info("Dừng giám sát thiết bị iOS.")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
