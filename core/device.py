#!/usr/bin/env python3
"""
Device detection, friendly property inspection, and track-devices event monitoring.
"""

import subprocess
import re
import time
from typing import List, Optional, Dict
from .config import ConfigManager
from . import ui

class DeviceInfo:
    def __init__(self, serial: str, state: str, dev_type: str = "device",
                 model: str = "", product: str = "", manufacturer: str = "", market_name: str = ""):
        self.serial = serial
        self.state = state # device, offline, unauthorized
        self.dev_type = dev_type # emulator, device
        self.model = model
        self.product = product
        self.manufacturer = manufacturer
        self.market_name = market_name

    @property
    def is_online(self) -> bool:
        return self.state in ("device", "online")

    @property
    def display_name(self) -> str:
        icon = "📱" if self.dev_type == "emulator" else "🔌"
        status_dot = f"{ui.Colors.GREEN}●{ui.Colors.RESET}" if self.is_online else f"{ui.Colors.RED}●{ui.Colors.RESET}"
        
        name_parts = []
        if self.manufacturer and self.manufacturer.lower() not in self.model.lower():
            name_parts.append(self.manufacturer)
        if self.market_name:
            name_parts.append(self.market_name)
        elif self.model:
            name_parts.append(self.model)
        elif self.product:
            name_parts.append(self.product)

        friendly_title = " ".join(name_parts) if name_parts else self.serial
        state_label = "" if self.is_online else f" ({self.state})"
        return f"{status_dot} {icon} {ui.Colors.BOLD}{friendly_title}{ui.Colors.RESET} [{ui.Colors.CYAN}{self.serial}{ui.Colors.RESET}]{state_label}"


def get_connected_devices() -> List[DeviceInfo]:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    try:
        res = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, check=True)
    except Exception as e:
        ui.error(f"Failed to run adb devices: {e}")
        return []

    devices: List[DeviceInfo] = []
    lines = res.stdout.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            serial = parts[0]
            state = parts[1]
            dev_type = "emulator" if serial.startswith("emulator-") else "device"
            
            model = ""
            product = ""
            m = re.search(r"model:([^\s]+)", line)
            if m:
                model = m.group(1).replace("_", " ")
            p = re.search(r"product:([^\s]+)", line)
            if p:
                product = p.group(1)

            dev = DeviceInfo(serial=serial, state=state, dev_type=dev_type, model=model, product=product)
            devices.append(dev)

    # Fetch friendly props for active devices
    for dev in devices:
        if dev.is_online and dev.dev_type != "emulator":
            try:
                cmd = [adb, "-s", dev.serial, "shell", "getprop ro.product.manufacturer; getprop ro.product.model; getprop ro.product.marketname"]
                prop_res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if prop_res.returncode == 0:
                    out_lines = [l.strip() for l in prop_res.stdout.splitlines() if l.strip()]
                    if len(out_lines) >= 1 and out_lines[0]:
                        dev.manufacturer = out_lines[0]
                    if len(out_lines) >= 2 and out_lines[1]:
                        dev.model = out_lines[1]
                    if len(out_lines) >= 3 and out_lines[2]:
                        dev.market_name = out_lines[2]
            except Exception:
                pass

    return devices


def resolve_target_device(device_arg: Optional[str] = None, interactive: bool = True) -> Optional[DeviceInfo]:
    devices = get_connected_devices()
    if not devices:
        ui.error("No Android devices or emulators connected!")
        ui.info("Check: 1) Cable is plugged in  2) USB Debugging enabled  3) Prompt approved on phone.")
        return None

    if device_arg:
        # Match by serial or model prefix
        for d in devices:
            if d.serial == device_arg or device_arg in d.serial or device_arg.lower() in d.model.lower():
                return d
        ui.error(f"Device '{device_arg}' not found among connected devices.")
        return None

    # Check saved default device
    cfg = ConfigManager.get_instance()
    saved = cfg.get_selected_device()
    if saved:
        for d in devices:
            if d.serial == saved:
                return d

    # If only 1 online device, use it automatically
    online_devices = [d for d in devices if d.is_online]
    if len(online_devices) == 1:
        return online_devices[0]

    if not interactive:
        return online_devices[0] if online_devices else devices[0]

    # Multiple devices: prompt user
    options = [(d.serial, f"{d.display_name}") for d in devices]
    chosen = ui.ask_choice("Có nhiều thiết bị đang kết nối. Vui lòng chọn thiết bị:", options)
    for d in devices:
        if d.serial == chosen:
            cfg.set_selected_device(d.serial)
            return d

    return devices[0]


def resolve_target_devices(device_arg: Optional[str] = None, interactive: bool = True) -> List[DeviceInfo]:
    """
    Resolve target device(s) for execution.
    - If device_arg is specified, returns [matched_device].
    - If no devices connected, returns [].
    - If only 1 device connected (or online), returns that device.
    - If multiple devices:
        If interactive: prompts user with multiselect (Up/Down + Space + "Run all" option).
        If not interactive: returns all online devices (or all devices).
    """
    devices = get_connected_devices()
    if not devices:
        ui.error("No Android devices or emulators connected!")
        ui.info("Check: 1) Cable is plugged in  2) USB Debugging enabled  3) Prompt approved on phone.")
        return []

    if device_arg:
        # Match by serial or model prefix
        for d in devices:
            if d.serial == device_arg or device_arg in d.serial or device_arg.lower() in d.model.lower():
                return [d]
        ui.error(f"Device '{device_arg}' not found among connected devices.")
        return []

    # If only 1 device connected, use it automatically
    if len(devices) == 1:
        return devices

    online_devices = [d for d in devices if d.is_online]
    if len(online_devices) == 1:
        return online_devices

    if not interactive:
        return online_devices if online_devices else devices

    # Multiple devices: prompt user with multiselect
    options = [(d.serial, d.display_name) for d in devices]
    chosen_serials = ui.ask_multiselect(
        title="Có nhiều thiết bị đang kết nối. Vui lòng chọn thiết bị:",
        options=options,
        all_label="⚡ Run all (Tất cả thiết bị đang attached)"
    )

    selected_devs = [d for d in devices if d.serial in chosen_serials]
    return selected_devs if selected_devs else devices


def get_device_ip(serial: str) -> Optional[str]:
    """
    Get device private IP address while connected via USB.
    Searches wlan0, ap0, swlan0, rndis0 to support Wi-Fi, hotspot, and tethering.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    try:
        res = subprocess.run([adb, "-s", serial, "shell", "ip addr"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return None
        
        stdout = res.stdout
        # Priority search: 192.168.x.x, 10.x.x.x, 172.16-31.x.x
        patterns = [
            r"inet\s+(192\.168\.\d{1,3}\.\d{1,3})/\d+",
            r"inet\s+(10\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d+",
            r"inet\s+(172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})/\d+",
        ]
        for pat in patterns:
            m = re.search(pat, stdout)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def watch_devices():
    """
    Real-time zero-resource device monitoring using 'adb track-devices'.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    ui.header("Giám sát thiết bị theo thời gian thực (adb track-devices)")
    ui.info("Cắm hoặc rút thiết bị Android để thấy trạng thái thay đổi tức thì. Bấm Ctrl+C để thoát.\n")

    # Initial print
    devs = get_connected_devices()
    print(f"{ui.Colors.BOLD}Thiết bị hiện tại ({len(devs)}):{ui.Colors.RESET}")
    for d in devs:
        print(f"  {d.display_name}")
    print()

    proc = subprocess.Popen([adb, "track-devices"], stdout=subprocess.PIPE, text=True)
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            time.sleep(0.5) # Debounce
            # Drain any further pending lines in buffer
            devs = get_connected_devices()
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {ui.Colors.YELLOW}⚡ Trạng thái thiết bị thay đổi:{ui.Colors.RESET} ({len(devs)} thiết bị kết nối)")
            for d in devs:
                print(f"  {d.display_name}")
            print()
    except KeyboardInterrupt:
        print()
        ui.info("Dừng giám sát.")
    finally:
        proc.terminate()
