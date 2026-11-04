#!/usr/bin/env python3
"""
Android Studio Flash CLI - Command Line Suite for Android Development without IDE.
"""

import sys
import os
import argparse
from pathlib import Path

# Add script directory to Python path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from core import ui
from core.config import ConfigManager
from core.device import resolve_target_device
from commands.cmd_doctor import run_doctor
from commands.cmd_devices import run_devices
from commands.cmd_build import run_build, run_clean, run_sync
from commands.cmd_run import run_app
from commands.cmd_wireless import (
    run_wireless_setup, run_wireless_pair, run_wireless_connect,
    run_wireless_disconnect, run_wireless_reconnect
)
from commands.cmd_logcat import run_logcat
from commands.cmd_keystore import run_keystore_create
from commands.cmd_module import run_module
from commands.cmd_flavor import run_flavor
from commands.cmd_quick import (
    run_quick_menu, resolve_app_context,
    action_restart, action_kill, action_clear_data, action_start,
    action_uninstall, action_install_apk, action_grant_permissions,
    action_revoke_permissions, action_wifi, action_mobile_data,
    action_airplane, action_screenshot, action_shell
)

def install_global_symlink():
    ui.header("Cài đặt Flash CLI vào Hệ Thống (Global)")
    target_dirs = [
        Path.home() / ".local" / "bin",
        Path("/usr/local/bin"),
    ]
    chosen_dir = None
    for d in target_dirs:
        if d.exists() and os.access(d, os.W_OK):
            chosen_dir = d
            break

    if not chosen_dir:
        chosen_dir = Path.home() / ".local" / "bin"
        chosen_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = chosen_dir / "flash"
    source_script = SCRIPT_DIR / "flash"

    try:
        if symlink_path.exists() or symlink_path.is_symlink():
            symlink_path.unlink()
        symlink_path.symlink_to(source_script)
        ui.success(f"Đã tạo symlink global tại: {ui.Colors.BOLD}{symlink_path}{ui.Colors.RESET}")
        
        path_env = os.getenv("PATH", "")
        if str(chosen_dir) not in path_env:
            ui.warning(f"Thư mục {chosen_dir} chưa có trong biến PATH.")
            ui.info(f"Hãy thêm vào ~/.zshrc:  export PATH=\"{chosen_dir}:$PATH\"")
        else:
            ui.success("Bây giờ bạn có thể gõ 'flash <command>' ở bất kỳ đâu trong terminal!")
    except Exception as e:
        ui.error(f"Không thể tạo symlink: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="flash",
        description="⚡ Android Studio Flash CLI - Bộ công cụ dòng lệnh đầy đủ cho lập trình Android không cần IDE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ví dụ sử dụng:
  flash run                      Biên dịch Debug, cài đặt và mở app lên thiết bị
  flash run -f vietnamese        Chạy app với flavor 'vietnamese'
  flash run --logcat             Chạy app và tự động stream Logcat lọc theo app
  flash run --no-build           Chỉ cài và mở file APK có sẵn, bỏ qua bước build
  flash build -f global          Biên dịch flavor 'global'
  flash build --all-flavors      Biên dịch tất cả product flavors
  flash flavor list              Xem danh sách productFlavors
  flash action                   Mở menu thao tác nhanh ADB & thiết bị
  flash restart                  Khởi động lại ứng dụng trên thiết bị
  flash kill                     Buộc dừng ứng dụng (Force Stop)
  flash clear -r                 Xóa dữ liệu và khởi động lại app
  flash perm grant               Cấp toàn bộ quyền runtime cho app
  flash wifi toggle              Bật/tắt Wi-Fi trên thiết bị
  flash screenshot               Chụp ảnh màn hình thiết bị và lưu về máy tính
  flash devices --watch          Giám sát cắm/rút thiết bị thời gian thực
  flash wireless setup           Tự động chuyển từ USB sang kết nối Wi-Fi
  flash logcat                   Xem logcat tô màu theo thời gian thực (lọc theo app)
  flash doctor                   Kiểm tra chẩn đoán môi trường SDK, ADB, JDK
  flash install-global           Cài đặt lệnh 'flash' global vào ~/.local/bin/
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Lệnh cần thực hiện")

    # doctor
    subparsers.add_parser("doctor", help="Kiểm tra chẩn đoán toàn diện môi trường (SDK, ADB, JDK, devices)")

    # devices
    p_dev = subparsers.add_parser("devices", help="Liệt kê, chọn thiết bị mặc định hoặc giám sát kết nối")
    p_dev.add_argument("-w", "--watch", action="store_true", help="Bật chế độ giám sát cắm/rút USB thời gian thực")
    p_dev.add_argument("-s", "--select", action="store_true", help="Chọn thiết bị làm mặc định cho các lệnh sau")

    # build
    p_build = subparsers.add_parser("build", help="Biên dịch APK (Debug hoặc Release)")
    p_build.add_argument("-v", "--variant", default="debug", choices=["debug", "release"], help="Loại build (mặc định: debug)")
    p_build.add_argument("-f", "--flavor", help="Product flavor cần build (ví dụ: vietnamese, global)")
    p_build.add_argument("--all-flavors", action="store_true", help="Build tất cả các product flavors")
    p_build.add_argument("-m", "--module", help="Module cần build (ví dụ: :app)")
    p_build.add_argument("-c", "--clean", action="store_true", help="Clean trước khi build")
    p_build.add_argument("--signed", action="store_true", help="Ký file APK khi build Release")

    # clean
    p_clean = subparsers.add_parser("clean", help="Xóa sạch các file build artifacts (Gradle clean)")
    p_clean.add_argument("-m", "--module", help="Module cần clean")

    # sync
    subparsers.add_parser("sync", help="Đồng bộ hóa Gradle dependencies")

    # run
    p_run = subparsers.add_parser("run", help="Build, cài đặt APK và khởi chạy ứng dụng trên thiết bị")
    p_run.add_argument("-v", "--variant", default="debug", choices=["debug", "release"], help="Loại build (mặc định: debug)")
    p_run.add_argument("-f", "--flavor", help="Product flavor cần chạy (ví dụ: vietnamese, global)")
    p_run.add_argument("-s", "--device", help="Serial hoặc IP của thiết bị chỉ định")
    p_run.add_argument("-m", "--module", help="Module mục tiêu (ví dụ: :app)")
    p_run.add_argument("--no-build", action="store_true", help="Bỏ qua bước build, dùng luôn APK mới nhất hiện có")
    p_run.add_argument("-l", "--logcat", action="store_true", help="Tự động mở Logcat ngay sau khi app khởi chạy")

    # flavor
    p_flav = subparsers.add_parser("flavor", help="Quản lý target productFlavor (dành cho project nhiều flavors)")
    p_flav.add_argument("action", nargs="?", default="list", choices=["list", "select", "clear"],
                        help="Hành động: list (danh sách), select (chọn mặc định), clear (xóa mặc định)")
    p_flav.add_argument("name", nargs="?", help="Tên flavor cụ thể khi chọn")

    # action / quick
    p_act = subparsers.add_parser("action", aliases=["quick"], help="Menu thao tác nhanh ADB & thiết bị (Popup)")
    p_act.add_argument("-s", "--device", help="Serial hoặc IP thiết bị")
    p_act.add_argument("-f", "--flavor", help="Product flavor mục tiêu")
    p_act.add_argument("-p", "--package", help="Package Name mục tiêu")

    # quick direct shortcuts:
    # restart
    p_rst = subparsers.add_parser("restart", help="Khởi động lại ứng dụng trên thiết bị")
    p_rst.add_argument("-s", "--device", help="Thiết bị")
    p_rst.add_argument("-f", "--flavor", help="Flavor")
    p_rst.add_argument("-p", "--package", help="Package Name")

    # kill
    p_kill = subparsers.add_parser("kill", help="Buộc dừng ứng dụng (Force Stop)")
    p_kill.add_argument("-s", "--device", help="Thiết bị")
    p_kill.add_argument("-f", "--flavor", help="Flavor")
    p_kill.add_argument("-p", "--package", help="Package Name")

    # clear
    p_clr = subparsers.add_parser("clear", help="Xóa dữ liệu ứng dụng (Clear App Data)")
    p_clr.add_argument("-r", "--restart", action="store_true", help="Khởi động lại app ngay sau khi xóa dữ liệu")
    p_clr.add_argument("-s", "--device", help="Thiết bị")
    p_clr.add_argument("-f", "--flavor", help="Flavor")
    p_clr.add_argument("-p", "--package", help="Package Name")

    # uninstall
    p_uninst = subparsers.add_parser("uninstall", help="Gỡ cài đặt ứng dụng")
    p_uninst.add_argument("-s", "--device", help="Thiết bị")
    p_uninst.add_argument("-f", "--flavor", help="Flavor")
    p_uninst.add_argument("-p", "--package", help="Package Name")

    # install
    p_inst = subparsers.add_parser("install", help="Cài đặt file APK lên thiết bị")
    p_inst.add_argument("apk", help="Đường dẫn file APK")
    p_inst.add_argument("-s", "--device", help="Thiết bị")

    # screenshot
    p_ss = subparsers.add_parser("screenshot", aliases=["screen"], help="Chụp ảnh màn hình thiết bị và lưu về máy tính")
    p_ss.add_argument("-o", "--output", help="Đường dẫn file ảnh đầu ra")
    p_ss.add_argument("--open", action="store_true", help="Tự động mở file ảnh sau khi chụp")
    p_ss.add_argument("-s", "--device", help="Thiết bị")

    # wifi
    p_wifi = subparsers.add_parser("wifi", help="Bật / tắt / toggle Wi-Fi trên thiết bị")
    p_wifi.add_argument("mode", nargs="?", default="toggle", choices=["toggle", "on", "off", "enable", "disable", "status"],
                        help="Hành động: toggle (mặc định), on, off, status")
    p_wifi.add_argument("-s", "--device", help="Thiết bị")

    # data
    p_data = subparsers.add_parser("data", help="Bật / tắt / toggle Mobile Data trên thiết bị")
    p_data.add_argument("mode", nargs="?", default="toggle", choices=["toggle", "on", "off", "enable", "disable", "status"],
                        help="Hành động: toggle (mặc định), on, off, status")
    p_data.add_argument("-s", "--device", help="Thiết bị")

    # airplane
    p_air = subparsers.add_parser("airplane", help="Bật / tắt / toggle Chế độ máy bay (Airplane Mode)")
    p_air.add_argument("mode", nargs="?", default="toggle", choices=["toggle", "on", "off", "enable", "disable", "status"],
                       help="Hành động: toggle (mặc định), on, off, status")
    p_air.add_argument("-s", "--device", help="Thiết bị")

    # perm
    p_perm = subparsers.add_parser("perm", aliases=["permission", "permissions"], help="Quản lý cấp / thu hồi quyền runtime")
    p_perm.add_argument("action", choices=["grant", "revoke"], help="Hành động: grant (cấp toàn bộ) hoặc revoke (thu hồi)")
    p_perm.add_argument("-r", "--restart", action="store_true", help="Khởi động lại app sau khi thay đổi quyền")
    p_perm.add_argument("-s", "--device", help="Thiết bị")
    p_perm.add_argument("-f", "--flavor", help="Flavor")
    p_perm.add_argument("-p", "--package", help="Package Name")

    # shell
    p_sh = subparsers.add_parser("shell", help="Mở terminal adb shell tương tác trên thiết bị")
    p_sh.add_argument("-s", "--device", help="Thiết bị")

    # wireless
    p_wire = subparsers.add_parser("wireless", help="Quản lý gỡ lỗi không dây (Wireless Debugging & TCP/IP)")
    wire_subs = p_wire.add_subparsers(dest="wire_action", help="Hành động wireless")
    
    p_wire_setup = wire_subs.add_parser("setup", help="Tự động lấy IP qua USB và kích hoạt kết nối Wi-Fi")
    p_wire_setup.add_argument("-s", "--device", help="Serial thiết bị USB cần cấu hình")
    p_wire_setup.add_argument("-p", "--port", type=int, default=5555, help="Port TCP/IP (mặc định: 5555)")

    p_wire_pair = wire_subs.add_parser("pair", help="Ghép đôi mã pairing (Android 11+)")
    p_wire_pair.add_argument("endpoint", help="Địa chỉ IP:PORT (ví dụ: 192.168.1.100:45678)")
    p_wire_pair.add_argument("code", help="Mã Pairing 6 chữ số")

    p_wire_conn = wire_subs.add_parser("connect", help="Kết nối tới IP thiết bị đã bật TCP/IP")
    p_wire_conn.add_argument("endpoint", help="Địa chỉ IP hoặc IP:PORT")

    wire_subs.add_parser("reconnect", help="Kết nối lại tất cả các thiết bị không dây đã nhớ")

    p_wire_disc = wire_subs.add_parser("disconnect", help="Ngắt kết nối thiết bị không dây")
    p_wire_disc.add_argument("endpoint", nargs="?", help="IP:PORT cụ thể cần ngắt (bỏ trống để ngắt tất cả)")

    # logcat
    p_log = subparsers.add_parser("logcat", help="Stream logcat thời gian thực có màu sắc và bộ lọc thông minh")
    p_log.add_argument("-a", "--app", nargs="?", const="", default=None,
                       help="Lọc log theo ứng dụng (mặc định tự động nhận diện từ project)")
    p_log.add_argument("-t", "--tag", help="Lọc log theo TAG (ví dụ: MainActivity)")
    p_log.add_argument("-l", "--level", choices=["V", "D", "I", "W", "E", "F"],
                       help="Mức log tối thiểu (V: Verbose, D: Debug, I: Info, W: Warn, E: Error, F: Fatal)")
    p_log.add_argument("-c", "--clear", action="store_true", help="Xóa sạch bộ đệm Logcat")
    p_log.add_argument("-s", "--device", help="Thiết bị cần xem log")

    # keystore
    p_key = subparsers.add_parser("keystore", help="Trình tạo khóa Keystore cho bản Release")
    key_subs = p_key.add_subparsers(dest="key_action", help="Hành động keystore")
    key_subs.add_parser("create", help="Chạy wizard tương tác tạo file .jks")

    # module
    p_mod = subparsers.add_parser("module", help="Quản lý target module cho project đa module")
    p_mod.add_argument("action", nargs="?", default="list", choices=["list", "select"],
                       help="Hành động: list (xem danh sách) hoặc select (chọn module)")

    # install-global
    subparsers.add_parser("install-global", help="Cài đặt lệnh 'flash' global vào hệ thống")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "doctor":
            run_doctor()
        elif args.command == "devices":
            run_devices(watch=args.watch, select=args.select)
        elif args.command == "build":
            run_build(variant=args.variant, module=args.module, flavor=args.flavor,
                      clean_first=args.clean, signed=args.signed, all_flavors=args.all_flavors)
        elif args.command == "clean":
            run_clean(module=args.module)
        elif args.command == "sync":
            run_sync()
        elif args.command == "run":
            run_app(variant=args.variant, device_id=args.device, module=args.module,
                    flavor=args.flavor, no_build=args.no_build, stream_logcat=args.logcat)
        elif args.command == "flavor":
            run_flavor(action=args.action, flavor_name=args.name)
        elif args.command in ("action", "quick"):
            run_quick_menu(device_id=args.device, flavor=args.flavor, package_name=args.package)
        elif args.command == "restart":
            dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
            action_restart(dev, pkg, launcher)
        elif args.command == "kill":
            dev, pkg, _ = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
            action_kill(dev, pkg)
        elif args.command == "clear":
            dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
            action_clear_data(dev, pkg, restart=args.restart, launcher=launcher)
        elif args.command == "uninstall":
            dev, pkg, _ = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
            action_uninstall(dev, pkg)
        elif args.command == "install":
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_install_apk(dev, apk_path_str=args.apk)
        elif args.command in ("screenshot", "screen"):
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_screenshot(dev, output_path=args.output, open_after=args.open)
        elif args.command == "wifi":
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_wifi(dev, mode=args.mode)
        elif args.command == "data":
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_mobile_data(dev, mode=args.mode)
        elif args.command == "airplane":
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_airplane(dev, mode=args.mode)
        elif args.command in ("perm", "permission", "permissions"):
            dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
            if args.action == "grant":
                action_grant_permissions(dev, pkg)
            else:
                action_revoke_permissions(dev, pkg, restart=args.restart, launcher=launcher)
        elif args.command == "shell":
            dev = resolve_target_device(device_arg=args.device)
            if dev:
                action_shell(dev)
        elif args.command == "wireless":
            action = args.wire_action or "setup"
            if action == "setup":
                dev_id = getattr(args, "device", None)
                port = getattr(args, "port", 5555)
                run_wireless_setup(device_id=dev_id, port=port)
            elif action == "pair":
                run_wireless_pair(args.endpoint, args.code)
            elif action == "connect":
                run_wireless_connect(args.endpoint)
            elif action == "reconnect":
                run_wireless_reconnect()
            elif action == "disconnect":
                run_wireless_disconnect(args.endpoint)
        elif args.command == "logcat":
            run_logcat(app_filter=args.app, tag_filter=args.tag, level=args.level,
                       clear=args.clear, device_id=args.device)
        elif args.command == "keystore":
            run_keystore_create()
        elif args.command == "module":
            run_module(action=args.action)
        elif args.command == "install-global":
            install_global_symlink()
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as e:
        ui.error(f"Đã xảy ra lỗi: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
