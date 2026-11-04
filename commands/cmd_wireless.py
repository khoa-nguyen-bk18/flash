#!/usr/bin/env python3
"""
Wireless debugging manager: TCP/IP mode, Android 11+ pairing, and auto-reconnect.
"""

import sys
import time
import subprocess
from typing import Optional
from core.device import get_connected_devices, get_device_ip, resolve_target_device
from core.config import ConfigManager
from core import ui

def run_wireless_setup(device_id: Optional[str] = None, port: int = 5555):
    """
    Automated USB to TCP/IP wireless transition.
    Fetches device IP while USB is still plugged in, switches port, and connects wirelessly.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    devs = get_connected_devices()
    usb_devices = [d for d in devs if ":" not in d.serial and d.dev_type != "emulator" and d.is_online]

    if not usb_devices:
        ui.error("Không tìm thấy thiết bị Android nào đang cắm cáp USB!")
        ui.info("Vui lòng cắm cáp USB trước để cấu hình chế độ TCP/IP không dây.")
        return

    dev = usb_devices[0]
    if len(usb_devices) > 1 and not device_id:
        opts = [(d.serial, d.display_name) for d in usb_devices]
        chosen = ui.ask_choice("Chọn thiết bị USB để kích hoạt kết nối không dây:", opts)
        dev = next(d for d in usb_devices if d.serial == chosen)
    elif device_id:
        for d in usb_devices:
            if d.serial == device_id or device_id in d.serial:
                dev = d
                break

    ui.header(f"Cấu hình kết nối không dây cho {dev.display_name}")

    # Step 1: Detect IP
    ui.info("Đang dò tìm địa chỉ IP của thiết bị (Wi-Fi / Hotspot)...")
    ip = get_device_ip(dev.serial)
    if not ip:
        ui.warning("Không tự động lấy được IP của thiết bị từ wlan0/ap0.")
        ip = ui.ask_input("Vui lòng nhập địa chỉ IP Wi-Fi của điện thoại (xem trong Settings -> Wi-Fi)")
        if not ip:
            return

    ui.success(f"Phát hiện IP thiết bị: {ui.Colors.BOLD}{ip}{ui.Colors.RESET}")

    # Step 2: Switch to TCP/IP mode
    ui.info(f"Đang chuyển ADB sang chế độ TCP/IP trên port {port}...")
    res = subprocess.run([adb, "-s", dev.serial, "tcpip", str(port)], capture_output=True, text=True)
    if res.returncode != 0:
        ui.error(f"Lỗi khi chuyển sang TCP/IP: {res.stderr}")
        return

    ui.success(f"Đã bật chế độ TCP/IP trên port {port}!")
    time.sleep(1.5)

    # Step 3: Connect wirelessly
    endpoint = f"{ip}:{port}"
    ui.info(f"Đang kết nối không dây đến {endpoint}...")
    conn_res = subprocess.run([adb, "connect", endpoint], capture_output=True, text=True)
    out = conn_res.stdout.strip()
    if "connected" in out.lower() and "unable" not in out.lower():
        ui.success(f"Kết nối không dây thành công: {ui.Colors.BOLD}{endpoint}{ui.Colors.RESET}")
        cfg.remember_wireless_device(endpoint)
        ui.info("Bây giờ bạn có thể rút cáp USB và sử dụng hoàn toàn qua Wi-Fi!")
    else:
        ui.warning(f"Kết nối trả về: {out}")
        ui.info(f"Đảm bảo máy tính và điện thoại đang chung mạng Wi-Fi, sau đó chạy: flash wireless connect {endpoint}")


def run_wireless_pair(ip_port: str, pairing_code: str):
    """
    Android 11+ Pair with pairing code.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    ui.header("Ghép đôi thiết bị không dây (Android 11+ Pairing)")
    ui.info(f"Đang ghép đôi với {ip_port}...")
    res = subprocess.run([adb, "pair", ip_port, pairing_code], capture_output=True, text=True)
    out = f"{res.stdout}\n{res.stderr}".strip()
    if "success" in out.lower() or "successfully paired" in out.lower():
        ui.success("Ghép đôi thành công!")
        connect_host = ip_port.split(":")[0]
        connect_port = ui.ask_input(f"Nhập Port hiển thị ở màn hình Wireless Debugging chính (cho {connect_host})")
        if connect_port:
            endpoint = f"{connect_host}:{connect_port}"
            run_wireless_connect(endpoint)
    else:
        ui.error(f"Ghép đôi thất bại:\n{out}")


def run_wireless_connect(endpoint: str):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    if ":" not in endpoint:
        endpoint = f"{endpoint}:5555"

    ui.info(f"Đang kết nối tới {endpoint}...")
    res = subprocess.run([adb, "connect", endpoint], capture_output=True, text=True)
    out = res.stdout.strip()
    if "connected" in out.lower() and "unable" not in out.lower():
        ui.success(f"Đã kết nối thành công: {endpoint}")
        cfg.remember_wireless_device(endpoint)
    else:
        ui.error(f"Không thể kết nối đến {endpoint}: {out}")


def run_wireless_disconnect(endpoint: Optional[str] = None):
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    if endpoint:
        ui.info(f"Ngắt kết nối {endpoint}...")
        subprocess.run([adb, "disconnect", endpoint])
        cfg.forget_wireless_device(endpoint)
        ui.success(f"Đã ngắt kết nối {endpoint}.")
    else:
        ui.info("Ngắt kết nối tất cả các thiết bị không dây...")
        res = subprocess.run([adb, "devices"], capture_output=True, text=True)
        for line in res.stdout.splitlines():
            parts = line.split()
            if parts and ":" in parts[0]:
                ep = parts[0]
                subprocess.run([adb, "disconnect", ep])
                ui.info(f"Đã ngắt kết nối {ep}")
        ui.success("Hoàn tất.")


def run_wireless_reconnect():
    cfg = ConfigManager.get_instance()
    remembered = cfg.get_remembered_wireless_devices()
    ui.header("Kết nối lại các thiết bị không dây đã nhớ")
    if not remembered:
        ui.info("Chưa có thiết bị không dây nào được lưu.")
        ui.info("Dùng 'flash wireless setup' để cấu hình thiết bị đầu tiên.")
        return

    for ep in remembered:
        run_wireless_connect(ep)
