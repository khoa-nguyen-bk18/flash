#!/usr/bin/env python3
"""
Wireless debugging manager: TCP/IP mode, Android 11+ QR & code pairing, mDNS discovery, and auto-reconnect.
"""

import ipaddress
import secrets
import string
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from core import ui
from core.config import ConfigManager
from core.device import get_connected_devices, get_device_ip
from core.qrcode_gen import render_qr_string


@dataclass
class MdnsService:
    instance: str
    service_type: str
    endpoint: str

    @property
    def host(self) -> str:
        ep = self.endpoint.strip()
        if ep.startswith("["):
            end_bracket = ep.find("]")
            if end_bracket != -1:
                return ep[1:end_bracket]
        if ":" in ep:
            return ep.rsplit(":", 1)[0]
        return ep

    @property
    def port(self) -> Optional[int]:
        ep = self.endpoint.strip()
        if ep.startswith("["):
            idx = ep.rfind("]:")
            if idx != -1:
                port_str = ep[idx + 2 :]
                return int(port_str) if port_str.isdigit() else None
            return None
        if ":" in ep:
            port_str = ep.rsplit(":", 1)[1]
            return int(port_str) if port_str.isdigit() else None
        return None

    @property
    def is_ipv4(self) -> bool:
        try:
            return ipaddress.ip_address(self.host).version == 4
        except ValueError:
            return False


def is_wireless_serial(serial: str) -> bool:
    return (
        ":" in serial
        or "._adb-tls-connect._tcp" in serial
        or "._adb._tcp" in serial
    )


def generate_pairing_credentials(service_name: Optional[str] = None) -> tuple[str, str, str]:
    """
    Generate Android 11+ ADB QR pairing credentials and payload string:
    WIFI:T:ADB;S:<service_name>;P:<password>;;
    """
    alphabet = string.ascii_letters + string.digits
    if service_name is None:
        svc = "studio-" + "".join(secrets.choice(alphabet) for _ in range(8))
    else:
        svc = service_name.strip()
        if not svc or ";" in svc or ":" in svc or any(ch.isspace() for ch in svc):
            raise ValueError(
                "Tên service QR không hợp lệ (không được rỗng hoặc chứa ';', ':', khoảng trắng)."
            )

    password = "".join(secrets.choice(alphabet) for _ in range(8))
    payload = f"WIFI:T:ADB;S:{svc};P:{password};;"
    return svc, password, payload


def parse_mdns_services(output: str) -> list[MdnsService]:
    """Parse output of `adb mdns services` into a list of MdnsService."""
    services: list[MdnsService] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("list of discovered") or lower.startswith("mdns"):
            continue
        parts = line.split()
        if len(parts) >= 3:
            instance = parts[0]
            service_type = parts[1].rstrip(".")
            endpoint = parts[2]
            services.append(MdnsService(instance=instance, service_type=service_type, endpoint=endpoint))
    return services


def list_mdns_services(adb: str) -> list[MdnsService]:
    """Query `adb mdns services` and return parsed services."""
    try:
        res = subprocess.run([adb, "mdns", "services"], capture_output=True, text=True, timeout=5)
        if res.returncode != 0:
            return []
        return parse_mdns_services(res.stdout)
    except Exception:
        return []


def check_mdns_available(adb: str) -> tuple[bool, str]:
    """Ensure ADB server is started and verify mDNS discovery is supported/active."""
    try:
        subprocess.run([adb, "start-server"], capture_output=True, text=True, timeout=5)
    except Exception:
        pass

    try:
        res = subprocess.run([adb, "mdns", "check"], capture_output=True, text=True, timeout=5)
        out = f"{res.stdout}\n{res.stderr}".strip()
        lower = out.lower()
        ok = (
            res.returncode == 0
            and "error" not in lower
            and "disabled" not in lower
            and "not available" not in lower
        )
        return ok, out
    except Exception as e:
        return False, str(e)


def _pick_preferred_service(services: list[MdnsService]) -> Optional[MdnsService]:
    """Prefer IPv4 endpoint over IPv6 when multiple records exist for the same service."""
    if not services:
        return None
    for svc in services:
        if svc.is_ipv4:
            return svc
    return services[0]


def _auto_connect_after_pair(
    adb: str,
    cfg: ConfigManager,
    paired_host: str,
    before_serials: set[str],
    timeout: float = 12.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    After pairing succeeds, wait for either ADB auto-connect or `_adb-tls-connect._tcp`
    advertisement on the paired host and run `adb connect`.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # 1. Check if ADB already auto-connected the newly paired device
        devs = get_connected_devices()
        for d in devs:
            if not is_wireless_serial(d.serial) or not d.is_online:
                continue
            if d.serial not in before_serials or (paired_host and d.serial.startswith(f"{paired_host}:")):
                if ":" in d.serial:
                    cfg.remember_wireless_device(d.serial)
                ui.success(f"Thiết bị đã tự động kết nối qua Wi-Fi: {d.display_name}")
                return True

        # 2. Look up `_adb-tls-connect._tcp` via mDNS for paired_host
        services = list_mdns_services(adb)
        connect_candidates = [
            s for s in services
            if s.service_type == "_adb-tls-connect._tcp" and (not paired_host or s.host == paired_host)
        ]
        target_svc = _pick_preferred_service(connect_candidates)
        if target_svc:
            conn_res = subprocess.run(
                [adb, "connect", target_svc.endpoint],
                capture_output=True,
                text=True,
                timeout=10,
            )
            out = f"{conn_res.stdout}\n{conn_res.stderr}".strip()
            if "connected" in out.lower() and "unable" not in out.lower():
                cfg.remember_wireless_device(target_svc.endpoint)
                matched = [
                    d for d in get_connected_devices()
                    if d.serial == target_svc.endpoint or (d.is_online and is_wireless_serial(d.serial) and d.serial not in before_serials)
                ]
                if matched:
                    ui.success(f"Kết nối Wi-Fi thành công: {matched[0].display_name}")
                else:
                    ui.success(f"Kết nối Wi-Fi thành công: {ui.Colors.BOLD}{target_svc.endpoint}{ui.Colors.RESET}")
                return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    return False


def run_wireless_qr(
    timeout: int = 120,
    auto_connect: bool = True,
    invert: bool = False,
    service_name: Optional[str] = None,
    compact: bool = False,
) -> bool:
    """
    Android 11+ Wireless Debugging QR Code pairing & auto-connect.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    ui.header("Kết nối Wi-Fi Debugging bằng mã QR (Android 11+)")

    mdns_ok, mdns_msg = check_mdns_available(adb)
    if not mdns_ok:
        ui.error("ADB mDNS chưa sẵn sàng trên máy tính này, không thể tự động phát hiện thiết bị sau khi quét QR.")
        if mdns_msg:
            ui.detail("Chi tiết adb mdns check", mdns_msg)
        ui.info("Gợi ý: cập nhật Android Platform-Tools hoặc thử set biến môi trường ADB_MDNS_OPENSCREEN=1.")
        ui.info("Bạn vẫn có thể ghép đôi thủ công bằng mã 6 số: flash wireless pair <IP:PORT> <CODE>")
        return False

    svc_name, password, payload = generate_pairing_credentials(service_name)
    qr_text = render_qr_string(payload, ec_level="M", quiet_zone=3, invert=invert, compact=compact)

    ui.info("1. Đảm bảo máy tính và điện thoại đang kết nối cùng mạng Wi-Fi.")
    ui.info("2. Trên điện thoại: Settings -> Developer options -> Wireless debugging -> Pair device with QR code.")
    ui.info("3. Đưa camera quét mã QR bên dưới:\n")

    print(qr_text)
    print()
    ui.detail("Service", svc_name)
    ui.detail("Timeout", f"{timeout}s")
    print()

    before_serials = {d.serial for d in get_connected_devices()}
    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    start_time = time.monotonic()
    deadline = start_time + max(1, timeout)
    pairing_svc: Optional[MdnsService] = None
    is_tty = sys.stdout.isatty()
    step = 0

    try:
        while time.monotonic() < deadline:
            services = list_mdns_services(adb)
            matches = [
                s for s in services
                if s.service_type == "_adb-tls-pairing._tcp" and s.instance == svc_name
            ]
            pairing_svc = _pick_preferred_service(matches)
            if pairing_svc:
                break

            remaining = max(0, int(deadline - time.monotonic()))
            if is_tty:
                frame = spinner_frames[step % len(spinner_frames)]
                sys.stdout.write(f"\r{ui.Colors.CYAN}{frame}{ui.Colors.RESET} Đang chờ điện thoại quét mã QR... (còn {remaining}s) ")
                sys.stdout.flush()
            step += 1

            sleep_for = min(0.5, max(0.0, deadline - time.monotonic()))
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        if is_tty:
            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()
        print()
        ui.warning("Đã hủy chờ quét mã QR.")
        return False

    if is_tty:
        sys.stdout.write("\r" + " " * 70 + "\r")
        sys.stdout.flush()

    if not pairing_svc:
        ui.warning(f"Hết thời gian chờ ({timeout}s) mà chưa phát hiện điện thoại quét mã QR.")
        ui.info("Kiểm tra: 1) Chung mạng Wi-Fi  2) Không bật VPN / AP isolation  3) Thử chạy 'flash wireless pair <IP:PORT> <CODE>'.")
        return False

    ui.info(f"Phát hiện yêu cầu ghép đôi từ {ui.Colors.BOLD}{pairing_svc.endpoint}{ui.Colors.RESET}. Đang thực hiện adb pair...")
    pair_res = subprocess.run(
        [adb, "pair", pairing_svc.endpoint, password],
        capture_output=True,
        text=True,
        timeout=15,
    )
    pair_out = f"{pair_res.stdout}\n{pair_res.stderr}".strip()
    if pair_res.returncode != 0 or ("success" not in pair_out.lower() and "successfully paired" not in pair_out.lower()):
        ui.error(f"Ghép đôi thất bại:\n{pair_out}")
        return False

    ui.success("Ghép đôi (Pairing) thành công!")
    if not auto_connect:
        ui.info("Chế độ --no-connect đang bật. Để kết nối sau, chạy: flash wireless connect")
        return True

    ui.info("Đang tự động kết nối ADB qua Wi-Fi (_adb-tls-connect._tcp)...")
    if _auto_connect_after_pair(adb, cfg, paired_host=pairing_svc.host, before_serials=before_serials, timeout=12.0):
        ui.info("Bây giờ bạn có thể dùng 'flash run', 'flash logcat', 'flash devices' hoàn toàn qua Wi-Fi!")
        return True

    ui.warning("Đã ghép đôi thành công nhưng chưa tự động kết nối được qua mDNS.")
    if sys.stdin.isatty():
        connect_port = ui.ask_input(
            f"Nhập Port hiển thị ở màn hình Wireless debugging (cho {pairing_svc.host}) hoặc Enter để bỏ qua"
        )
        if connect_port:
            endpoint = f"{pairing_svc.host}:{connect_port}"
            return run_wireless_connect(endpoint)
    else:
        ui.info(f"Chạy: flash wireless connect {pairing_svc.host}:<PORT> hoặc flash wireless connect")
    return False


def run_wireless_discover() -> list[MdnsService]:
    """Discover nearby Android devices advertising ADB wireless mDNS services."""
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    ui.header("Dò tìm thiết bị Android Wi-Fi qua mDNS")
    mdns_ok, mdns_msg = check_mdns_available(adb)
    if not mdns_ok:
        ui.error("ADB mDNS chưa sẵn sàng trên máy tính này.")
        if mdns_msg:
            ui.detail("Chi tiết", mdns_msg)
        return []

    services = list_mdns_services(adb)
    if not services:
        ui.warning("Không tìm thấy thiết bị nào đang bật Wireless Debugging trong mạng Wi-Fi hiện tại.")
        ui.info("Dùng 'flash wireless qr' để ghép đôi thiết bị mới qua mã QR (Android 11+).")
        return []

    ui.success(f"Phát hiện {len(services)} dịch vụ mDNS:")
    for idx, svc in enumerate(services, start=1):
        print(f"  [{idx}] {ui.Colors.BOLD}{svc.endpoint}{ui.Colors.RESET}  ({svc.service_type}) [{ui.Colors.CYAN}{svc.instance}{ui.Colors.RESET}]")

    print()
    ui.info("Dùng 'flash wireless connect' để chọn kết nối hoặc 'flash wireless qr' để ghép đôi thiết bị mới.")
    return services


def run_wireless_setup(device_id: Optional[str] = None, port: int = 5555):
    """
    Automated USB to TCP/IP wireless transition.
    Fetches device IP while USB is still plugged in, switches port, and connects wirelessly.
    """
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    devs = get_connected_devices()
    usb_devices = [d for d in devs if not is_wireless_serial(d.serial) and d.dev_type != "emulator" and d.is_online]

    if not usb_devices:
        ui.error("Không tìm thấy thiết bị Android nào đang cắm cáp USB!")
        ui.info("Vui lòng cắm cáp USB trước để cấu hình chế độ TCP/IP không dây.")
        ui.info("Hoặc dùng 'flash wireless qr' để kết nối không cần cáp USB bằng mã QR (Android 11+).")
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


def run_wireless_pair(
    ip_port: Optional[str] = None,
    pairing_code: Optional[str] = None,
    use_qr: bool = False,
    timeout: int = 120,
    invert: bool = False,
    compact: bool = False,
) -> bool:
    """
    Android 11+ Pair with QR code or 6-digit pairing code.
    """
    if use_qr:
        return run_wireless_qr(timeout=timeout, invert=invert, compact=compact)

    if not ip_port and not pairing_code:
        mode = ui.ask_choice(
            "Chọn phương thức ghép đôi Wireless Debugging (Android 11+):",
            [
                ("qr", "Quét mã QR trên terminal (Khuyên dùng)"),
                ("code", "Nhập IP:PORT và mã ghép đôi 6 chữ số"),
            ],
        )
        if mode == "qr":
            return run_wireless_qr(timeout=timeout, invert=invert, compact=compact)

    if not ip_port:
        ip_port = ui.ask_input("Nhập địa chỉ IP:PORT ghép đôi (ví dụ: 192.168.1.100:45678)")
        if not ip_port:
            return False

    if not pairing_code:
        pairing_code = ui.ask_input("Nhập mã Pairing 6 chữ số")
        if not pairing_code:
            return False

    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()
    before_serials = {d.serial for d in get_connected_devices()}

    ui.header("Ghép đôi thiết bị không dây (Android 11+ Pairing)")
    ui.info(f"Đang ghép đôi với {ip_port}...")
    res = subprocess.run([adb, "pair", ip_port, pairing_code], capture_output=True, text=True)
    out = f"{res.stdout}\n{res.stderr}".strip()
    if "success" in out.lower() or "successfully paired" in out.lower():
        ui.success("Ghép đôi thành công!")
        connect_host = ip_port.rsplit(":", 1)[0].strip("[]")
        if _auto_connect_after_pair(adb, cfg, paired_host=connect_host, before_serials=before_serials, timeout=6.0):
            return True
        connect_port = ui.ask_input(f"Nhập Port hiển thị ở màn hình Wireless Debugging chính (cho {connect_host})")
        if connect_port:
            endpoint = f"{connect_host}:{connect_port}"
            return run_wireless_connect(endpoint)
        return True
    else:
        ui.error(f"Ghép đôi thất bại:\n{out}")
        return False


def run_wireless_connect(endpoint: Optional[str] = None) -> bool:
    cfg = ConfigManager.get_instance()
    adb = cfg.get_adb_path()

    if not endpoint:
        check_mdns_available(adb)
        services = list_mdns_services(adb)
        connectable = [
            s for s in services
            if s.service_type in ("_adb-tls-connect._tcp", "_adb._tcp")
        ]
        # Deduplicate by endpoint, keeping IPv4 first
        ordered = sorted(connectable, key=lambda s: (0 if s.is_ipv4 else 1, s.endpoint))
        seen_endpoints: set[str] = set()
        unique_services: list[MdnsService] = []
        for s in ordered:
            if s.endpoint not in seen_endpoints:
                seen_endpoints.add(s.endpoint)
                unique_services.append(s)

        if not unique_services:
            ui.warning("Không tìm thấy thiết bị nào qua mDNS để tự động kết nối.")
            ui.info("Dùng 'flash wireless qr' để ghép đôi bằng mã QR hoặc 'flash wireless connect <IP:PORT>'.")
            return False

        if len(unique_services) == 1:
            endpoint = unique_services[0].endpoint
        else:
            opts = [(s.endpoint, f"{s.endpoint} ({s.instance})") for s in unique_services]
            endpoint = ui.ask_choice("Chọn thiết bị Wi-Fi phát hiện qua mDNS để kết nối:", opts)

    if ":" not in endpoint:
        endpoint = f"{endpoint}:5555"

    ui.info(f"Đang kết nối tới {endpoint}...")
    res = subprocess.run([adb, "connect", endpoint], capture_output=True, text=True)
    out = f"{res.stdout}\n{res.stderr}".strip()
    if "connected" in out.lower() and "unable" not in out.lower():
        ui.success(f"Đã kết nối thành công: {endpoint}")
        cfg.remember_wireless_device(endpoint)
        return True
    else:
        ui.error(f"Không thể kết nối đến {endpoint}: {out}")
        return False


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
            if parts and is_wireless_serial(parts[0]):
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
        ui.info("Dùng 'flash wireless qr' hoặc 'flash wireless setup' để cấu hình thiết bị đầu tiên.")
        return

    for ep in remembered:
        run_wireless_connect(ep)
