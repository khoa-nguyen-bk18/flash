#!/usr/bin/env python3
"""
Xcode Build, Archive, Clean, and Dependency Sync execution engine.
Uses Flash-isolated DerivedData (<project_root>/.flash/DerivedData)
and preserves JAVA_HOME / PATH for Kotlin Multiplatform (KMP) Gradle phases.
Zero external dependencies.
"""

import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .config import ConfigManager
from . import ui
from .xcode_project import (
    get_active_xcode_path,
    get_build_settings,
    get_xcode_list_info,
    xcode_project_flag,
)

_ERROR_LINE_RE = re.compile(r"(?:^|\s)(?:fatal\s+)?error:", re.IGNORECASE)
_WARNING_LINE_RE = re.compile(r"(?:^|\s)warning:", re.IGNORECASE)
_SUCCEEDED_RE = re.compile(r"\*\*\s+[A-Z]+\s+SUCCEEDED\s+\*\*")
_FAILED_RE = re.compile(r"\*\*\s+[A-Z]+\s+FAILED\s+\*\*")


def _build_kmp_safe_env() -> dict:
    """
    Return environment dict preserving JAVA_HOME and PATH so KMP Xcode
    Run Script phases (e.g., embedAndSignAppleFrameworkForXcode) succeed.
    """
    env = os.environ.copy()

    # Ensure common macOS tool locations are present in PATH without losing existing PATH
    current_path = env.get("PATH", "")
    path_parts = [p for p in current_path.split(os.pathsep) if p]
    for extra in ("/opt/homebrew/bin", "/usr/local/bin"):
        if extra not in path_parts and os.path.isdir(extra):
            path_parts.append(extra)
    env["PATH"] = os.pathsep.join(path_parts)

    # Preserve JAVA_HOME explicitly if set
    java_home = os.getenv("JAVA_HOME")
    if java_home:
        env["JAVA_HOME"] = java_home

    return env


def build_xcode_command(
    xcode_path: Path,
    scheme: str,
    configuration: str,
    destination: str,
    action: str = "build",
    derived_data_path: Optional[Path] = None,
    extra_args: Optional[List[str]] = None,
    use_target: bool = False,
) -> List[str]:
    """Construct an `xcodebuild` command with Flash-isolated `-derivedDataPath`."""
    xcodebuild_bin = shutil.which("xcodebuild") or "xcodebuild"
    dd_path = derived_data_path or ConfigManager.get_instance().get_derived_data_path()

    selector_flag = "-target" if (use_target and xcode_path.suffix == ".xcodeproj") else "-scheme"
    cmd: List[str] = [
        xcodebuild_bin,
        *xcode_project_flag(xcode_path),
        selector_flag,
        scheme,
        "-configuration",
        configuration,
        "-destination",
        destination,
        "-derivedDataPath",
        str(dd_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    if action:
        cmd.append(action)
    return cmd


def _format_xcodebuild_line(line: str) -> str:
    """Apply ANSI coloring to xcodebuild output lines."""
    if _SUCCEEDED_RE.search(line):
        return f"{ui.Colors.GREEN}{ui.Colors.BOLD}{line}{ui.Colors.RESET}"
    if _FAILED_RE.search(line):
        return f"{ui.Colors.RED}{ui.Colors.BOLD}{line}{ui.Colors.RESET}"
    if _ERROR_LINE_RE.search(line):
        return f"{ui.Colors.RED}{line}{ui.Colors.RESET}"
    if _WARNING_LINE_RE.search(line):
        return f"{ui.Colors.YELLOW}{line}{ui.Colors.RESET}"
    return line


def execute_xcodebuild(cmd: List[str], cwd: Optional[Path] = None) -> int:
    """
    Execute an `xcodebuild` command streaming stdout/stderr live with ANSI coloring.
    Preserves JAVA_HOME and PATH for KMP Gradle build phases.
    """
    env = _build_kmp_safe_env()
    ui.info(f"Đang chạy: {ui.Colors.DIM}{' '.join(cmd)}{ui.Colors.RESET}")

    proc: Optional[subprocess.Popen] = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd and cwd.is_dir() else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            print(_format_xcodebuild_line(line), flush=True)
        proc.wait()
        return proc.returncode
    except FileNotFoundError:
        ui.error(f"Không tìm thấy lệnh '{cmd[0]}'. Hãy đảm bảo Xcode Command Line Tools đã được cài đặt.")
        return 127
    except KeyboardInterrupt:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print()
        ui.warning("Đã hủy tiến trình xcodebuild.")
        return 130
    except OSError as exc:
        ui.error(f"Lỗi thực thi xcodebuild: {exc}")
        return 1


def _is_test_runner_app(app_path: Path, expected_names: List[str]) -> bool:
    """Return True if app_path looks like an XCTest runner not explicitly requested."""
    name = app_path.name
    stem_lower = app_path.stem.lower()
    if stem_lower in expected_names:
        return False
    lower_name = name.lower()
    return (
        lower_name.endswith("-runner.app")
        or lower_name.endswith("tests.app")
        or lower_name.endswith("uitests.app")
    )


def find_built_app(
    derived_data_path: Path,
    configuration: str,
    is_simulator: bool,
    scheme: Optional[str] = None,
    product_name: Optional[str] = None,
) -> Optional[Path]:
    """
    Locate built `.app` inside `DerivedData/Build/Products/<Configuration>-<sdk>`.
    Excludes `.dSYM` bundles and test runners unless explicitly matched.
    Prefers `product_name`, then `scheme`, then newest mtime.
    """
    sdk_suffix = "iphonesimulator" if is_simulator else "iphoneos"
    products_root = derived_data_path / "Build" / "Products"
    if not products_root.is_dir():
        return None

    target_dir = products_root / f"{configuration}-{sdk_suffix}"
    if not target_dir.is_dir():
        # Case-insensitive fallback inside Build/Products
        expected_lower = f"{configuration}-{sdk_suffix}".lower()
        found_dir: Optional[Path] = None
        try:
            for entry in products_root.iterdir():
                if entry.is_dir() and entry.name.lower() == expected_lower:
                    found_dir = entry
                    break
        except OSError:
            pass
        if found_dir is None:
            return None
        target_dir = found_dir

    expected_names: List[str] = []
    if product_name:
        clean_prod = product_name[:-4] if product_name.lower().endswith(".app") else product_name
        expected_names.append(clean_prod.lower())
    if scheme:
        expected_names.append(scheme.lower())

    candidates: List[Path] = []
    try:
        for entry in target_dir.iterdir():
            if not entry.is_dir():
                continue
            name_lower = entry.name.lower()
            if name_lower.endswith(".dsym") or ".dsym" in name_lower:
                continue
            if not name_lower.endswith(".app"):
                continue
            if _is_test_runner_app(entry, expected_names):
                continue
            candidates.append(entry)
    except OSError:
        return None

    if not candidates:
        return None

    def _score(p: Path):
        stem_lower = p.stem.lower()
        prod_match = 0
        scheme_match = 0
        if product_name:
            clean_prod = product_name[:-4] if product_name.lower().endswith(".app") else product_name
            if stem_lower == clean_prod.lower():
                prod_match = 2
            elif clean_prod.lower() in stem_lower:
                prod_match = 1
        if scheme:
            if stem_lower == scheme.lower():
                scheme_match = 2
            elif scheme.lower() in stem_lower:
                scheme_match = 1
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (prod_match, scheme_match, mtime)

    candidates.sort(key=_score, reverse=True)
    return candidates[0]


def build_ios_app(
    scheme: str,
    configuration: str = "Debug",
    destination: str = "generic/platform=iOS Simulator",
    is_simulator: bool = True,
    clean_first: bool = False,
    xcode_path: Optional[Path] = None,
    extra_args: Optional[List[str]] = None,
    use_target: bool = False,
) -> Optional[Path]:
    """
    Build an iOS `.app` bundle using `xcodebuild`.
    Runs `clean` first if requested, then `build`, and returns the located `.app` path.
    """
    target_xcode = xcode_path or get_active_xcode_path()
    if target_xcode is None:
        ui.error("Không tìm thấy .xcworkspace hoặc .xcodeproj trong dự án hiện tại.")
        return None

    cfg = ConfigManager.get_instance()
    dd_path = cfg.get_derived_data_path()
    cwd = target_xcode.parent

    if clean_first:
        ui.info(f"Đang clean '{scheme}' trước khi build...")
        clean_cmd = build_xcode_command(
            xcode_path=target_xcode,
            scheme=scheme,
            configuration=configuration,
            destination=destination,
            action="clean",
            derived_data_path=dd_path,
            use_target=use_target,
        )
        rc_clean = execute_xcodebuild(clean_cmd, cwd=cwd)
        if rc_clean != 0:
            ui.error("Xcode clean thất bại. Dừng quá trình build.")
            return None

    build_cmd = build_xcode_command(
        xcode_path=target_xcode,
        scheme=scheme,
        configuration=configuration,
        destination=destination,
        action="build",
        derived_data_path=dd_path,
        extra_args=extra_args,
        use_target=use_target,
    )
    rc = execute_xcodebuild(build_cmd, cwd=cwd)
    if rc != 0:
        return None

    product_name: Optional[str] = None
    try:
        sdk = "iphonesimulator" if is_simulator else "iphoneos"
        settings = get_build_settings(
            scheme=scheme,
            configuration=configuration,
            sdk=sdk,
            xcode_path=target_xcode,
        )
        product_name = settings.get("PRODUCT_NAME") or settings.get("FULL_PRODUCT_NAME")
    except Exception:
        product_name = None

    return find_built_app(
        derived_data_path=dd_path,
        configuration=configuration,
        is_simulator=is_simulator,
        scheme=scheme,
        product_name=product_name,
    )


def _find_export_options_plist(cfg: ConfigManager, explicit_plist: Optional[Path]) -> Optional[Path]:
    if explicit_plist:
        return explicit_plist if explicit_plist.is_file() else None

    ctx = cfg.project_context
    candidates: List[Path] = []
    if ctx.ios_dir:
        candidates.append(ctx.ios_dir / "ExportOptions.plist")
    if cfg.project_root:
        candidates.append(cfg.project_root / "ExportOptions.plist")

    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def archive_ios_app(
    scheme: str,
    configuration: str = "Release",
    xcode_path: Optional[Path] = None,
    export_options_plist: Optional[Path] = None,
) -> Optional[Path]:
    """
    Archive iOS app to `.flash/archives/<scheme>-<timestamp>.xcarchive`.
    If `ExportOptions.plist` is provided or discovered in `ios_dir` / `project_root`,
    exports an `.ipa` and returns its path; otherwise returns the `.xcarchive` path.
    """
    target_xcode = xcode_path or get_active_xcode_path()
    if target_xcode is None:
        ui.error("Không tìm thấy .xcworkspace hoặc .xcodeproj trong dự án hiện tại.")
        return None

    cfg = ConfigManager.get_instance()
    dd_path = cfg.get_derived_data_path()
    archives_dir = cfg.config_dir / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_scheme = re.sub(r"[^A-Za-z0-9._-]+", "_", scheme)
    archive_path = archives_dir / f"{safe_scheme}-{timestamp}.xcarchive"

    archive_cmd = build_xcode_command(
        xcode_path=target_xcode,
        scheme=scheme,
        configuration=configuration,
        destination="generic/platform=iOS",
        action="archive",
        derived_data_path=dd_path,
        extra_args=["-archivePath", str(archive_path)],
    )

    rc = execute_xcodebuild(archive_cmd, cwd=target_xcode.parent)
    if rc != 0 or not archive_path.exists():
        return None

    plist_path = _find_export_options_plist(cfg, export_options_plist)
    if not plist_path:
        ui.info(
            "Không tìm thấy ExportOptions.plist — giữ nguyên file .xcarchive. "
            "Thêm ExportOptions.plist vào thư mục iOS để tự động export .ipa."
        )
        return archive_path

    export_dir = archives_dir / f"{safe_scheme}-{timestamp}-ipa"
    export_dir.mkdir(parents=True, exist_ok=True)
    xcodebuild_bin = shutil.which("xcodebuild") or "xcodebuild"
    export_cmd = [
        xcodebuild_bin,
        "-exportArchive",
        "-archivePath",
        str(archive_path),
        "-exportPath",
        str(export_dir),
        "-exportOptionsPlist",
        str(plist_path),
    ]
    ui.info(f"Đang export .ipa bằng {plist_path.name}...")
    rc_export = execute_xcodebuild(export_cmd, cwd=target_xcode.parent)
    if rc_export == 0:
        ipa_files = sorted(export_dir.glob("*.ipa"), key=lambda p: p.stat().st_mtime, reverse=True)
        if ipa_files:
            return ipa_files[0]
        ui.warning("Export hoàn tất nhưng không tìm thấy file .ipa trong thư mục xuất.")
    else:
        ui.warning("Export .ipa thất bại — trả về đường dẫn .xcarchive đã tạo.")

    return archive_path


def clean_xcode_project(
    scheme: Optional[str] = None,
    clean_derived_data: bool = True,
    clean_gradle_kmp: bool = False,
    xcode_path: Optional[Path] = None,
) -> bool:
    """
    Clean Xcode project build artifacts, Flash DerivedData, and optionally KMP Gradle build.
    """
    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    target_xcode = xcode_path or ctx.active_xcode_path
    dd_path = cfg.get_derived_data_path()
    overall_ok = True

    if target_xcode is not None:
        xcodebuild_bin = shutil.which("xcodebuild")
        if xcodebuild_bin:
            resolved_scheme = scheme or cfg.get_selected_xcode_scheme()
            if not resolved_scheme and target_xcode.suffix == ".xcworkspace":
                info = get_xcode_list_info(target_xcode)
                if info and info.schemes:
                    resolved_scheme = info.schemes[0]

            cmd: List[str] = [xcodebuild_bin, *xcode_project_flag(target_xcode)]
            if resolved_scheme:
                cmd.extend(["-scheme", resolved_scheme])
            cmd.extend(["-derivedDataPath", str(dd_path), "clean"])

            rc = execute_xcodebuild(cmd, cwd=target_xcode.parent)
            if rc != 0:
                ui.warning("xcodebuild clean kết thúc với mã lỗi khác 0.")
                overall_ok = False
        else:
            ui.warning("Không tìm thấy 'xcodebuild' trong PATH, bỏ qua bước xcodebuild clean.")

    if clean_derived_data:
        if dd_path.exists():
            ui.info(f"Đang xóa Flash DerivedData: {dd_path}")
            try:
                shutil.rmtree(dd_path)
                ui.success("Đã xóa thư mục DerivedData của Flash.")
            except OSError as exc:
                ui.error(f"Không thể xóa DerivedData: {exc}")
                overall_ok = False
        else:
            ui.info("Thư mục DerivedData của Flash đã trống.")

    if clean_gradle_kmp and ctx.is_kmp:
        ui.info("Đang dọn dẹp Gradle build cho dự án KMP...")
        try:
            from .gradle import execute_gradle

            res = execute_gradle("clean")
            if res.returncode != 0:
                ui.warning("Gradle clean cho KMP thất bại.")
                overall_ok = False
        except Exception as exc:
            ui.warning(f"Không thể chạy Gradle clean cho KMP: {exc}")
            overall_ok = False

    return overall_ok


def _run_streaming_cmd(cmd: List[str], cwd: Path) -> int:
    """Run a helper CLI command (pod, bundle, gradlew) streaming output live."""
    env = _build_kmp_safe_env()
    ui.info(f"Đang chạy: {ui.Colors.DIM}{' '.join(cmd)}{ui.Colors.RESET}")
    try:
        res = subprocess.run(cmd, cwd=str(cwd), env=env)
        return res.returncode
    except FileNotFoundError:
        ui.error(f"Không tìm thấy lệnh '{cmd[0]}'.")
        return 127
    except KeyboardInterrupt:
        print()
        ui.warning("Đã hủy tiến trình.")
        return 130
    except OSError as exc:
        ui.error(f"Lỗi khi chạy '{cmd[0]}': {exc}")
        return 1


def sync_ios_dependencies(xcode_path: Optional[Path] = None) -> bool:
    """
    Sync iOS dependencies:
      1. KMP + Podfile -> best-effort `./gradlew generateDummyFramework`
      2. CocoaPods (`bundle exec pod install` or `pod install`) if `Podfile` exists
      3. Swift Package Manager (`xcodebuild -resolvePackageDependencies`)
    """
    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    target_xcode = xcode_path or ctx.active_xcode_path
    overall_ok = True

    # 1. KMP CocoaPods dummy framework (best-effort, non-fatal if task doesn't exist)
    if ctx.is_kmp and ctx.podfile:
        wrapper_name = "gradlew.bat" if sys.platform == "win32" else "gradlew"
        gradlew = ctx.root / wrapper_name
        if gradlew.is_file():
            ui.info("Phát hiện dự án KMP + Podfile. Thử chạy Gradle 'generateDummyFramework' (best-effort)...")
            rc_dummy = _run_streaming_cmd([str(gradlew), "generateDummyFramework"], cwd=ctx.root)
            if rc_dummy != 0:
                ui.warning(
                    "Task 'generateDummyFramework' không tồn tại hoặc không cần thiết — tiếp tục sync CocoaPods."
                )

    # 2. CocoaPods
    if ctx.podfile and ctx.podfile.is_file():
        pod_dir = ctx.podfile.parent
        has_gemfile = (pod_dir / "Gemfile").is_file() or (ctx.root / "Gemfile").is_file()
        bundle_bin = shutil.which("bundle")
        pod_bin = cfg.get_pod_path()

        if has_gemfile and bundle_bin:
            ui.info(f"Đang cài đặt CocoaPods (bundle exec pod install) tại {pod_dir}...")
            rc_pod = _run_streaming_cmd([bundle_bin, "exec", "pod", "install"], cwd=pod_dir)
            if rc_pod != 0:
                ui.error("bundle exec pod install thất bại.")
                overall_ok = False
        elif pod_bin:
            ui.info(f"Đang cài đặt CocoaPods (pod install) tại {pod_dir}...")
            rc_pod = _run_streaming_cmd([pod_bin, "install"], cwd=pod_dir)
            if rc_pod != 0:
                ui.error("pod install thất bại.")
                overall_ok = False
        else:
            ui.warning("Phát hiện Podfile nhưng chưa cài đặt CocoaPods ('pod' không có trong PATH).")
            overall_ok = False

    # 3. Swift Package Manager
    if target_xcode is not None:
        xcodebuild_bin = shutil.which("xcodebuild")
        if xcodebuild_bin:
            ui.info("Đang đồng bộ Swift Package Manager (resolvePackageDependencies)...")
            spm_cmd = [
                xcodebuild_bin,
                "-resolvePackageDependencies",
                *xcode_project_flag(target_xcode),
                "-derivedDataPath",
                str(cfg.get_derived_data_path()),
            ]
            rc_spm = execute_xcodebuild(spm_cmd, cwd=target_xcode.parent)
            if rc_spm != 0:
                ui.error("resolvePackageDependencies thất bại.")
                overall_ok = False
        else:
            ui.warning("Không tìm thấy 'xcodebuild', bỏ qua bước Swift Package Manager.")
            overall_ok = False
    elif not ctx.podfile:
        ui.warning("Không tìm thấy Xcode project/workspace hoặc Podfile để đồng bộ.")
        overall_ok = False

    return overall_ok
