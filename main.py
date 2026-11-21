#!/usr/bin/env python3
"""
Flash CLI - Command Line Suite for Android, Xcode (iOS), and Kotlin Multiplatform (KMP) Development without IDE.
"""

import sys
import os
import argparse
from pathlib import Path
from typing import Optional

# Add script directory to Python path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from core import ui
from core.config import ConfigManager
from core.project import resolve_active_platform
from core.device import resolve_target_device
from core.ios_device import resolve_target_ios_device
from core.ios_actions import (
    ios_restart_app, ios_terminate_app, ios_clear_data, ios_clear_restart,
    ios_uninstall_app, ios_install_app, ios_grant_permissions,
    ios_revoke_permissions, ios_screenshot
)
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
from commands.cmd_fastlane import run_fastlane
from commands.cmd_platform import run_platform
from commands.cmd_scheme import run_scheme
from commands.cmd_ios_devices import run_ios_devices
from commands.cmd_ios_build import run_ios_build, run_ios_clean, run_ios_sync
from commands.cmd_ios_run import run_ios_app
from commands.cmd_ios_quick import run_ios_quick_menu, resolve_ios_app_context
from commands.cmd_ios_logs import run_ios_logs
from commands.cmd_quick import (
    run_quick_menu, resolve_app_context,
    action_restart, action_kill, action_clear_data, action_clear_restart, action_start,
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


def _extract_cli_platform(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "ios", False):
        return "ios"
    if getattr(args, "android", False):
        return "android"
    plat = getattr(args, "platform", None)
    if plat in ("android", "ios"):
        return plat
    return None


def main():
    # Shared platform flags so users can pass --ios / --android / -P before OR after subcommand
    platform_parent = argparse.ArgumentParser(add_help=False)
    platform_parent.add_argument(
        "-P", "--platform",
        choices=["auto", "android", "ios"],
        default=argparse.SUPPRESS,
        help="Chọn nền tảng mục tiêu (auto, android, ios) - hữu ích cho KMP project"
    )
    platform_parent.add_argument(
        "--ios",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Chạy lệnh ở chế độ iOS / Xcode"
    )
    platform_parent.add_argument(
        "--android",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Chạy lệnh ở chế độ Android / Gradle"
    )

    parser = argparse.ArgumentParser(
        prog="flash",
        parents=[platform_parent],
        description="⚡ Flash CLI - Bộ công cụ dòng lệnh cho Android, Xcode (iOS) và Kotlin Multiplatform (KMP) không cần IDE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Ví dụ sử dụng:
  flash run                      Biên dịch, cài đặt và mở app (tự nhận diện Android / Xcode / KMP)
  flash run --ios                Chạy ứng dụng iOS trên Simulator hoặc iPhone (KMP / Xcode)
  flash run --android            Chạy ứng dụng Android trên thiết bị / Emulator (KMP / Android)
  flash run -f vietnamese        Chạy app với flavor (Android) hoặc scheme (iOS)
  flash run --logcat             Chạy app và tự động stream Logcat / iOS Logs
  flash run --no-build           Chỉ cài và mở APK / .app có sẵn, bỏ qua bước build
  flash build -f global          Biên dịch flavor (Android) hoặc scheme (iOS)
  flash scheme list              Xem danh sách Xcode Schemes & Configurations (iOS)
  flash flavor list              Xem danh sách productFlavors (Android) hoặc Schemes (iOS)
  flash platform select ios      Ghim nền tảng mặc định cho KMP project
  flash fastlane                 Đọc Fastfile và chọn lane theo index để chạy qua bundle exec
  flash action                   Mở menu thao tác nhanh thiết bị (ADB / Simulator & Device)
  flash clear-restart            Xóa dữ liệu và khởi động lại app ngay lập tức (alias: reset, cr)
  flash screenshot --open        Chụp ảnh màn hình thiết bị / Simulator và mở xem
  flash devices --watch          Giám sát cắm/rút thiết bị thời gian thực
  flash logs                     Xem log thời gian thực có màu sắc (alias của logcat)
  flash doctor                   Kiểm tra chẩn đoán môi trường Android SDK, Xcode, Simulators, Devices
  flash install-global           Cài đặt lệnh 'flash' global vào ~/.local/bin/
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Lệnh cần thực hiện")

    # doctor
    subparsers.add_parser("doctor", parents=[platform_parent],
                          help="Kiểm tra chẩn đoán môi trường (Android SDK, ADB, Xcode, Simulators, Devices)")

    # platform (KMP)
    p_plat = subparsers.add_parser("platform", help="Quản lý nền tảng mục tiêu (android / ios) cho KMP project")
    p_plat.add_argument("action", nargs="?", default="list", choices=["list", "select", "clear"],
                        help="Hành động: list, select, clear")
    p_plat.add_argument("name", nargs="?", help="Tên nền tảng (android hoặc ios)")

    # devices
    p_dev = subparsers.add_parser("devices", parents=[platform_parent],
                                  help="Liệt kê, chọn thiết bị mặc định hoặc giám sát kết nối")
    p_dev.add_argument("-w", "--watch", action="store_true", help="Bật chế độ giám sát thiết bị thời gian thực")
    p_dev.add_argument("-s", "--select", action="store_true", help="Chọn thiết bị làm mặc định cho các lệnh sau")

    # build
    p_build = subparsers.add_parser("build", parents=[platform_parent],
                                    help="Biên dịch APK (Android) hoặc .app/.ipa (Xcode / iOS)")
    p_build.add_argument("-v", "--variant", default=None,
                         help="Build Type (Android: debug/release) hoặc Configuration (iOS: Debug/Release)")
    p_build.add_argument("-f", "--flavor", "--scheme", dest="flavor",
                         help="Product flavor (Android) hoặc Xcode Scheme (iOS)")
    p_build.add_argument("--all-flavors", "--all-schemes", dest="all_flavors", action="store_true",
                         help="Build tất cả flavors (Android) hoặc tất cả schemes (iOS)")
    p_build.add_argument("-m", "--module", help="Module cần build (Android: ví dụ :app)")
    p_build.add_argument("-c", "--clean", action="store_true", help="Clean trước khi build")
    p_build.add_argument("--signed", action="store_true", help="Ký Release APK (Android) hoặc Archive/IPA (iOS)")
    p_build.add_argument("-d", "--destination", help="Xcode build destination (iOS, ví dụ: 'generic/platform=iOS')")

    # clean
    p_clean = subparsers.add_parser("clean", parents=[platform_parent],
                                    help="Xóa sạch các file build artifacts (Gradle clean / Xcode clean + DerivedData)")
    p_clean.add_argument("-m", "--module", help="Module cần clean (Android)")
    p_clean.add_argument("--all", dest="clean_all", action="store_true",
                         help="Clean cả Gradle lẫn Xcode (dành cho KMP)")

    # sync
    subparsers.add_parser("sync", parents=[platform_parent],
                          help="Đồng bộ hóa dependencies (Gradle / CocoaPods / SwiftPM / KMP)")

    # run
    p_run = subparsers.add_parser("run", parents=[platform_parent],
                                  help="Build, cài đặt và khởi chạy ứng dụng trên thiết bị / Simulator")
    p_run.add_argument("-v", "--variant", default=None,
                       help="Build Type (Android) hoặc Configuration (iOS: Debug/Release)")
    p_run.add_argument("-f", "--flavor", "--scheme", dest="flavor",
                       help="Product flavor (Android) hoặc Xcode Scheme (iOS)")
    p_run.add_argument("-s", "--device", help="Serial/IP (Android) hoặc UDID/Tên (iOS)")
    p_run.add_argument("-m", "--module", help="Module mục tiêu (Android: ví dụ :app)")
    p_run.add_argument("--no-build", action="store_true", help="Bỏ qua bước build, dùng bản build có sẵn")
    p_run.add_argument("-l", "--logcat", "--logs", dest="logcat", action="store_true",
                       help="Tự động mở Logcat / iOS Logs ngay sau khi app khởi chạy")

    # flavor
    p_flav = subparsers.add_parser("flavor", parents=[platform_parent],
                                   help="Quản lý productFlavor (Android) hoặc Xcode Scheme (iOS)")
    p_flav.add_argument("action", nargs="?", default="list", choices=["list", "select", "clear"],
                        help="Hành động: list, select, clear")
    p_flav.add_argument("name", nargs="?", help="Tên flavor hoặc scheme cụ thể khi chọn")

    # scheme (iOS explicit command)
    p_scheme = subparsers.add_parser("scheme", parents=[platform_parent],
                                     help="Quản lý Xcode Scheme mặc định cho dự án iOS / KMP")
    p_scheme.add_argument("action", nargs="?", default="list", choices=["list", "select", "clear"],
                          help="Hành động: list, select, clear")
    p_scheme.add_argument("name", nargs="?", help="Tên scheme cụ thể khi chọn")

    # action / quick
    p_act = subparsers.add_parser("action", aliases=["quick"], parents=[platform_parent],
                                  help="Menu thao tác nhanh thiết bị (Popup ADB / iOS)")
    p_act.add_argument("-s", "--device", help="Serial/IP (Android) hoặc UDID/Tên (iOS)")
    p_act.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor (Android) hoặc Scheme (iOS)")
    p_act.add_argument("-p", "--package", help="Package Name (Android) hoặc Bundle ID (iOS)")

    # restart
    p_rst = subparsers.add_parser("restart", parents=[platform_parent], help="Khởi động lại ứng dụng trên thiết bị")
    p_rst.add_argument("-c", "--clear", action="store_true", help="Xóa sạch dữ liệu trước khi khởi động lại")
    p_rst.add_argument("-s", "--device", help="Thiết bị")
    p_rst.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_rst.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # clear-restart
    p_cr = subparsers.add_parser("clear-restart", aliases=["reset", "cr", "clear-and-restart"],
                                 parents=[platform_parent],
                                 help="Xóa dữ liệu và khởi động lại ứng dụng ngay lập tức")
    p_cr.add_argument("-s", "--device", help="Thiết bị")
    p_cr.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_cr.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # kill
    p_kill = subparsers.add_parser("kill", parents=[platform_parent], help="Buộc dừng ứng dụng (Force Stop / Terminate)")
    p_kill.add_argument("-s", "--device", help="Thiết bị")
    p_kill.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_kill.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # clear
    p_clr = subparsers.add_parser("clear", parents=[platform_parent], help="Xóa dữ liệu ứng dụng (Clear App Data)")
    p_clr.add_argument("-r", "--restart", action="store_true", help="Khởi động lại app ngay sau khi xóa dữ liệu")
    p_clr.add_argument("-s", "--device", help="Thiết bị")
    p_clr.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_clr.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # uninstall
    p_uninst = subparsers.add_parser("uninstall", parents=[platform_parent], help="Gỡ cài đặt ứng dụng")
    p_uninst.add_argument("-s", "--device", help="Thiết bị")
    p_uninst.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_uninst.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # install
    p_inst = subparsers.add_parser("install", parents=[platform_parent],
                                   help="Cài đặt file APK (Android) hoặc .app/.ipa (iOS) lên thiết bị")
    p_inst.add_argument("apk", help="Đường dẫn file APK / .app / .ipa")
    p_inst.add_argument("-s", "--device", help="Thiết bị")

    # screenshot
    p_ss = subparsers.add_parser("screenshot", aliases=["screen"], parents=[platform_parent],
                                 help="Chụp ảnh màn hình thiết bị / Simulator và lưu về máy tính")
    p_ss.add_argument("-o", "--output", help="Đường dẫn file ảnh đầu ra")
    p_ss.add_argument("--open", action="store_true", help="Tự động mở file ảnh sau khi chụp")
    p_ss.add_argument("-s", "--device", help="Thiết bị")

    # wifi
    p_wifi = subparsers.add_parser("wifi", parents=[platform_parent], help="Bật / tắt / toggle Wi-Fi (Android)")
    p_wifi.add_argument("mode", nargs="?", default="toggle",
                        choices=["toggle", "on", "off", "enable", "disable", "status"],
                        help="Hành động: toggle (mặc định), on, off, status")
    p_wifi.add_argument("-s", "--device", help="Thiết bị")

    # data
    p_data = subparsers.add_parser("data", parents=[platform_parent], help="Bật / tắt / toggle Mobile Data (Android)")
    p_data.add_argument("mode", nargs="?", default="toggle",
                        choices=["toggle", "on", "off", "enable", "disable", "status"],
                        help="Hành động: toggle (mặc định), on, off, status")
    p_data.add_argument("-s", "--device", help="Thiết bị")

    # airplane
    p_air = subparsers.add_parser("airplane", parents=[platform_parent], help="Bật / tắt / toggle Airplane Mode (Android)")
    p_air.add_argument("mode", nargs="?", default="toggle",
                       choices=["toggle", "on", "off", "enable", "disable", "status"],
                       help="Hành động: toggle (mặc định), on, off, status")
    p_air.add_argument("-s", "--device", help="Thiết bị")

    # perm
    p_perm = subparsers.add_parser("perm", aliases=["permission", "permissions"], parents=[platform_parent],
                                   help="Quản lý cấp / thu hồi quyền runtime")
    p_perm.add_argument("action", choices=["grant", "revoke"], help="Hành động: grant hoặc revoke")
    p_perm.add_argument("-r", "--restart", action="store_true", help="Khởi động lại app sau khi thay đổi quyền")
    p_perm.add_argument("-s", "--device", help="Thiết bị")
    p_perm.add_argument("-f", "--flavor", "--scheme", dest="flavor", help="Flavor / Scheme")
    p_perm.add_argument("-p", "--package", help="Package Name / Bundle ID")

    # shell
    p_sh = subparsers.add_parser("shell", parents=[platform_parent], help="Mở terminal adb shell tương tác (Android)")
    p_sh.add_argument("-s", "--device", help="Thiết bị")

    # wireless
    p_wire = subparsers.add_parser("wireless", parents=[platform_parent],
                                   help="Quản lý gỡ lỗi không dây (Android TCP/IP & thông tin iOS Wi-Fi)")
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

    # logcat / logs
    p_log = subparsers.add_parser("logcat", aliases=["logs"], parents=[platform_parent],
                                  help="Stream log thời gian thực có màu sắc (Android Logcat / iOS Unified Log)")
    p_log.add_argument("-a", "--app", nargs="?", const="", default=None,
                       help="Lọc log theo ứng dụng (Package Name / Bundle ID)")
    p_log.add_argument("-t", "--tag", help="Lọc log theo TAG (Android) hoặc Subsystem (iOS)")
    p_log.add_argument("-l", "--level", choices=["V", "D", "I", "W", "E", "F"],
                       help="Mức log tối thiểu (V, D, I, W, E, F)")
    p_log.add_argument("-c", "--clear", action="store_true", help="Xóa sạch bộ đệm Logcat (Android)")
    p_log.add_argument("-s", "--device", help="Thiết bị cần xem log")

    # keystore
    p_key = subparsers.add_parser("keystore", help="Trình tạo khóa Keystore cho bản Release (Android)")
    key_subs = p_key.add_subparsers(dest="key_action", help="Hành động keystore")
    key_subs.add_parser("create", help="Chạy wizard tương tác tạo file .jks")

    # module
    p_mod = subparsers.add_parser("module", parents=[platform_parent],
                                  help="Quản lý target module (Android) hoặc Xcode Project/Workspace (iOS)")
    p_mod.add_argument("action", nargs="?", default="list", choices=["list", "select"],
                       help="Hành động: list hoặc select")

    # fastlane / lane / fl
    p_fl = subparsers.add_parser(
        "fastlane",
        aliases=["lane", "fl"],
        parents=[platform_parent],
        help="Đọc cấu hình Fastlane và thực thi lane (hỗ trợ bundle exec và chọn theo index)"
    )
    p_fl.add_argument(
        "target",
        nargs="?",
        help="Tên lane hoặc index cần chạy (ví dụ: 1 hoặc build_debug). Bỏ trống để chọn tương tác."
    )
    p_fl.add_argument(
        "-l", "--list",
        action="store_true",
        help="Chỉ hiển thị danh sách các lanes có sẵn mà không thực thi"
    )
    p_fl.add_argument(
        "--no-bundle",
        action="store_true",
        help="Không sử dụng 'bundle exec', chạy trực tiếp lệnh 'fastlane'"
    )
    p_fl.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Các tham số bổ sung truyền trực tiếp cho Fastlane (ví dụ: key:value)"
    )

    # install-global
    subparsers.add_parser("install-global", help="Cài đặt lệnh 'flash' global vào hệ thống")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    cli_platform = _extract_cli_platform(args)

    try:
        if args.command == "install-global":
            install_global_symlink()
            return

        if args.command == "platform":
            run_platform(action=args.action, platform_name=args.name)
            return

        if args.command == "doctor":
            run_doctor(platform=cli_platform)
            return

        if args.command == "scheme":
            run_scheme(action=args.action, scheme_name=args.name)
            return

        if args.command in ("fastlane", "lane", "fl"):
            run_fastlane(
                target=args.target,
                list_only=args.list,
                no_bundle=args.no_bundle,
                extra_args=args.extra_args
            )
            return

        if args.command == "keystore":
            run_keystore_create()
            return

        # Resolve active platform ('android' or 'ios') for platform-aware commands
        active_platform = resolve_active_platform(cli_platform=cli_platform, interactive=True)

        if args.command == "devices":
            if active_platform == "ios":
                run_ios_devices(watch=args.watch, select=args.select)
            else:
                run_devices(watch=args.watch, select=args.select)

        elif args.command == "build":
            if active_platform == "ios":
                run_ios_build(
                    variant=args.variant,
                    scheme=args.flavor,
                    clean_first=args.clean,
                    signed=args.signed,
                    all_schemes=args.all_flavors,
                    device_destination=args.destination,
                )
            else:
                run_build(variant=args.variant, module=args.module, flavor=args.flavor,
                          clean_first=args.clean, signed=args.signed, all_flavors=args.all_flavors)

        elif args.command == "clean":
            if active_platform == "ios":
                run_ios_clean(clean_all_kmp=args.clean_all)
            else:
                run_clean(module=args.module)

        elif args.command == "sync":
            if active_platform == "ios":
                run_ios_sync()
            else:
                run_sync()

        elif args.command == "run":
            if active_platform == "ios":
                run_ios_app(
                    variant=args.variant,
                    device_id=args.device,
                    scheme=args.flavor,
                    no_build=args.no_build,
                    stream_logs=args.logcat,
                )
            else:
                run_app(variant=args.variant, device_id=args.device, module=args.module,
                        flavor=args.flavor, no_build=args.no_build, stream_logcat=args.logcat)

        elif args.command == "flavor":
            if active_platform == "ios":
                run_scheme(action=args.action, scheme_name=args.name)
            else:
                run_flavor(action=args.action, flavor_name=args.name)

        elif args.command in ("action", "quick"):
            if active_platform == "ios":
                run_ios_quick_menu(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
            else:
                run_quick_menu(device_id=args.device, flavor=args.flavor, package_name=args.package)

        elif args.command == "restart":
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                if args.clear:
                    ios_clear_restart(dev, bid)
                else:
                    ios_restart_app(dev, bid)
            else:
                dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                if args.clear:
                    action_clear_restart(dev, pkg, launcher)
                else:
                    action_restart(dev, pkg, launcher)

        elif args.command in ("clear-restart", "reset", "cr", "clear-and-restart"):
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                ios_clear_restart(dev, bid)
            else:
                dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                action_clear_restart(dev, pkg, launcher)

        elif args.command == "kill":
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                ios_terminate_app(dev, bid)
            else:
                dev, pkg, _ = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                action_kill(dev, pkg)

        elif args.command == "clear":
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                ios_clear_data(dev, bid, restart=args.restart)
            else:
                dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                action_clear_data(dev, pkg, restart=args.restart, launcher=launcher)

        elif args.command == "uninstall":
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                ios_uninstall_app(dev, bid, confirm=True)
            else:
                dev, pkg, _ = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                action_uninstall(dev, pkg)

        elif args.command == "install":
            if active_platform == "ios":
                dev = resolve_target_ios_device(device_arg=args.device)
                if dev:
                    ios_install_app(dev, Path(args.apk).expanduser().resolve())
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_install_apk(dev, apk_path_str=args.apk)

        elif args.command in ("screenshot", "screen"):
            if active_platform == "ios":
                dev = resolve_target_ios_device(device_arg=args.device)
                if dev:
                    ios_screenshot(dev, output_path=args.output, open_after=args.open)
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_screenshot(dev, output_path=args.output, open_after=args.open)

        elif args.command == "wifi":
            if active_platform == "ios":
                ui.warning("iOS không hỗ trợ bật/tắt Wi-Fi qua CLI trên thiết bị/Simulator tiêu chuẩn.")
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_wifi(dev, mode=args.mode)

        elif args.command == "data":
            if active_platform == "ios":
                ui.warning("iOS không hỗ trợ bật/tắt Mobile Data qua CLI trên thiết bị/Simulator tiêu chuẩn.")
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_mobile_data(dev, mode=args.mode)

        elif args.command == "airplane":
            if active_platform == "ios":
                ui.warning("iOS không hỗ trợ bật/tắt Airplane Mode qua CLI trên thiết bị/Simulator tiêu chuẩn.")
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_airplane(dev, mode=args.mode)

        elif args.command in ("perm", "permission", "permissions"):
            if active_platform == "ios":
                dev, bid = resolve_ios_app_context(device_id=args.device, scheme=args.flavor, bundle_id=args.package)
                if args.action == "grant":
                    ios_grant_permissions(dev, bid)
                else:
                    ios_revoke_permissions(dev, bid, restart=args.restart)
            else:
                dev, pkg, launcher = resolve_app_context(device_id=args.device, flavor=args.flavor, package_name=args.package)
                if args.action == "grant":
                    action_grant_permissions(dev, pkg)
                else:
                    action_revoke_permissions(dev, pkg, restart=args.restart, launcher=launcher)

        elif args.command == "shell":
            if active_platform == "ios":
                ui.warning("iOS không hỗ trợ interactive shell như 'adb shell'. Bạn có thể dùng 'flash logs' để xem log ứng dụng.")
            else:
                dev = resolve_target_device(device_arg=args.device)
                if dev:
                    action_shell(dev)

        elif args.command == "wireless":
            if active_platform == "ios":
                ui.header("iOS Wireless Debugging (Xcode 15+ / devicectl)")
                ui.info("Trên Xcode 15+ và iOS 17+, thiết bị đã pair trong Xcode sẽ tự động hiển thị qua Wi-Fi trong 'flash devices --ios'.")
                ui.info("Để bật kết nối Wi-Fi lần đầu: cắm cáp USB -> mở Xcode -> Window -> Devices and Simulators -> chọn thiết bị -> bật 'Connect via network'.")
                run_ios_devices(watch=False, select=False)
            else:
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

        elif args.command in ("logcat", "logs"):
            if active_platform == "ios":
                run_ios_logs(app_filter=args.app, tag_filter=args.tag, level=args.level,
                             clear=args.clear, device_id=args.device)
            else:
                run_logcat(app_filter=args.app, tag_filter=args.tag, level=args.level,
                           clear=args.clear, device_id=args.device)

        elif args.command == "module":
            run_module(action=args.action, platform=active_platform)

    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except Exception as e:
        ui.error(f"Đã xảy ra lỗi: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
