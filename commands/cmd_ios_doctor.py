#!/usr/bin/env python3
"""
iOS / Xcode Diagnostic Doctor.
Checks macOS environment, Xcode toolchain, iOS Simulator runtimes, devicectl devices,
code signing identities, CocoaPods/Bundler, and detected Xcode projects/schemes.
Zero external dependencies.
"""

import json
import re
import shutil
import subprocess
import sys
from typing import List

from core.config import ConfigManager
from core.ios_device import get_ios_physical_devices, get_ios_simulators
from core import ui


def _get_available_ios_runtimes(xcrun: str) -> List[str]:
    """Return human-readable list of available iOS Simulator runtimes."""
    try:
        res = subprocess.run(
            [xcrun, "simctl", "list", "runtimes", "available", "-j"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
        runtimes = data.get("runtimes", [])
        ios_rts: List[str] = []
        for rt in runtimes:
            if not isinstance(rt, dict):
                continue
            name = str(rt.get("name", ""))
            identifier = str(rt.get("identifier", ""))
            if rt.get("isAvailable", True) and (
                name.lower().startswith("ios") or "SimRuntime.iOS-" in identifier
            ):
                ver = rt.get("version", "")
                build = rt.get("buildversion", "")
                label = f"{name} ({build})" if build else (name or f"iOS {ver}")
                ios_rts.append(label)
        return ios_rts
    except Exception:
        return []


def _get_xcode_schemes(xcodebuild: str, target_path, is_workspace: bool) -> List[str]:
    """Query schemes via `xcodebuild -list -json`."""
    flag = "-workspace" if is_workspace else "-project"
    try:
        res = subprocess.run(
            [xcodebuild, flag, str(target_path), "-list", "-json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
        container = data.get("workspace") if is_workspace else data.get("project")
        if isinstance(container, dict):
            schemes = container.get("schemes", [])
            if isinstance(schemes, list):
                return [str(s) for s in schemes]
    except Exception:
        pass
    return []


def run_ios_doctor(standalone: bool = True) -> bool:
    """
    Run iOS / Xcode diagnostic checks.
    Returns `has_issues: bool` (True if critical problems were detected).
    """
    if standalone:
        ui.header("iOS Flash Doctor - Kiểm tra chẩn đoán môi trường Xcode / iOS")
    else:
        print(f"\n{ui.Colors.CYAN}{ui.Colors.BOLD}🍎 Kiểm tra môi trường iOS / Xcode:{ui.Colors.RESET}")

    cfg = ConfigManager.get_instance()
    ctx = cfg.project_context
    has_issues = False

    # 1. macOS Platform Check
    print(f"\n{ui.Colors.BOLD}1. Nền tảng hệ điều hành (macOS):{ui.Colors.RESET}")
    if sys.platform == "darwin":
        ui.success("Đang chạy trên macOS (hỗ trợ build & chạy iOS).")
    else:
        ui.error(f"Hệ điều hành hiện tại là '{sys.platform}'. Build và chạy iOS yêu cầu macOS + Xcode.")
        has_issues = True
        if standalone:
            print()
            ui.error("Không thể tiếp tục kiểm tra toolchain Xcode trên hệ điều hành không phải macOS.")
        return has_issues

    # 2. Xcode & xcode-select & xcodebuild
    print(f"\n{ui.Colors.BOLD}2. Xcode & Command Line Tools:{ui.Colors.RESET}")
    try:
        sel = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, timeout=5)
        if sel.returncode == 0 and sel.stdout.strip():
            dev_dir = sel.stdout.strip()
            ui.success(f"xcode-select -p: {dev_dir}")
            if "CommandLineTools" in dev_dir:
                ui.warning("Đang trỏ tới CommandLineTools thay vì Xcode.app. Chạy: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer")
                has_issues = True
        else:
            ui.error("Chưa cấu hình xcode-select. Hãy cài đặt Xcode và chạy 'xcode-select --install'.")
            has_issues = True
    except Exception as e:
        ui.error(f"Lỗi khi chạy xcode-select: {e}")
        has_issues = True

    xcodebuild = shutil.which("xcodebuild")
    if xcodebuild:
        try:
            ver = subprocess.run([xcodebuild, "-version"], capture_output=True, text=True, timeout=10)
            if ver.returncode == 0:
                lines = [l.strip() for l in ver.stdout.splitlines() if l.strip()]
                ui.success(f"xcodebuild: {' | '.join(lines)}")
            else:
                ui.error(f"xcodebuild lỗi: {(ver.stderr or ver.stdout).strip()}")
                has_issues = True
        except Exception as e:
            ui.error(f"Không thể chạy xcodebuild: {e}")
            has_issues = True
    else:
        ui.error("Không tìm thấy 'xcodebuild' trong PATH.")
        has_issues = True

    # 3. xcrun simctl & iOS Runtimes
    print(f"\n{ui.Colors.BOLD}3. iOS Simulator (xcrun simctl & Runtimes):{ui.Colors.RESET}")
    xcrun = shutil.which("xcrun")
    if xcrun:
        runtimes = _get_available_ios_runtimes(xcrun)
        if runtimes:
            ui.success(f"Tìm thấy {len(runtimes)} iOS Simulator Runtime khả dụng:")
            for rt in runtimes:
                print(f"    • {rt}")
        else:
            ui.warning("Không tìm thấy iOS Simulator Runtime nào.")
            ui.info("Khắc phục: Mở Xcode > Settings > Platforms và tải iOS Simulator Runtime.")
            has_issues = True
    else:
        ui.error("Không tìm thấy 'xcrun'.")
        has_issues = True

    # 4. xcrun devicectl & Connected Devices / Booted Simulators
    print(f"\n{ui.Colors.BOLD}4. Thiết bị iOS & Simulator (devicectl / simctl):{ui.Colors.RESET}")
    if xcrun:
        dc_check = subprocess.run([xcrun, "devicectl", "--version"], capture_output=True, text=True, timeout=5)
        if dc_check.returncode == 0:
            dc_ver = (dc_check.stdout or "").strip().splitlines()[0] if dc_check.stdout else "OK"
            ui.success(f"xcrun devicectl: {dc_ver}")
        else:
            ui.warning("xcrun devicectl không khả dụng (yêu cầu Xcode 15+ để quản lý thiết bị iOS 17+).")

        phys = get_ios_physical_devices()
        sims = get_ios_simulators()
        booted_sims = [s for s in sims if s.is_online]

        if phys:
            ui.success(f"Thiết bị vật lý ({len(phys)}):")
            for d in phys:
                print(f"    {d.display_name}")
        else:
            ui.info("Chưa có thiết bị iOS vật lý nào được kết nối.")

        if booted_sims:
            ui.success(f"Simulator đang chạy ({len(booted_sims)}):")
            for s in booted_sims:
                print(f"    {s.display_name}")
        else:
            ui.info(f"Chưa có Simulator nào đang chạy ({len(sims)} Simulator khả dụng ở trạng thái Shutdown).")

    # 5. Code Signing Identities
    print(f"\n{ui.Colors.BOLD}5. Chứng chỉ ký ứng dụng (Code Signing Identities):{ui.Colors.RESET}")
    security = shutil.which("security")
    if security:
        try:
            sec = subprocess.run(
                [security, "find-identity", "-v", "-p", "codesigning"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            identities = re.findall(r'"([^"]+)"', sec.stdout or "")
            if identities:
                ui.success(f"Tìm thấy {len(identities)} Code Signing Identity hợp lệ:")
                for ident in identities[:5]:
                    print(f"    • {ident}")
                if len(identities) > 5:
                    print(f"    ... và {len(identities) - 5} chứng chỉ khác")
            else:
                ui.warning("Không tìm thấy Code Signing Identity nào (cần thiết khi chạy trên iPhone thật; Simulator không yêu cầu).")
        except Exception as e:
            ui.warning(f"Không thể kiểm tra Code Signing Identities: {e}")
    else:
        ui.warning("Không tìm thấy công cụ 'security'.")

    # 6. CocoaPods / Bundler (if Podfile exists)
    if ctx.podfile:
        print(f"\n{ui.Colors.BOLD}6. CocoaPods & Bundler:{ui.Colors.RESET}")
        ui.info(f"Phát hiện Podfile: {ctx.podfile}")
        pod = cfg.get_pod_path()
        if pod:
            try:
                pv = subprocess.run([pod, "--version"], capture_output=True, text=True, timeout=5)
                ui.success(f"CocoaPods: v{pv.stdout.strip()} ({pod})")
            except Exception:
                ui.success(f"CocoaPods: {pod}")
        else:
            ui.error("Dự án có Podfile nhưng không tìm thấy 'pod' trong PATH! Cài đặt: sudo gem install cocoapods hoặc brew install cocoapods.")
            has_issues = True

        bundle = shutil.which("bundle")
        if bundle:
            try:
                bv = subprocess.run([bundle, "--version"], capture_output=True, text=True, timeout=5)
                ui.success(f"Bundler: {bv.stdout.strip()}")
            except Exception:
                ui.success(f"Bundler: {bundle}")
        elif (ctx.podfile.parent / "Gemfile").is_file() or (ctx.root / "Gemfile").is_file():
            ui.warning("Phát hiện Gemfile nhưng chưa cài Bundler.")

    # 7. Detected Xcode Workspace / Project & Schemes (+ KMP info)
    step_num = 7 if ctx.podfile else 6
    print(f"\n{ui.Colors.BOLD}{step_num}. Dự án Xcode & Schemes:{ui.Colors.RESET}")
    active_xcode = ctx.active_xcode_path
    if active_xcode:
        kind = "Workspace" if ctx.is_workspace else "Project"
        ui.success(f"Xcode {kind}: {active_xcode}")
        if xcodebuild:
            schemes = _get_xcode_schemes(xcodebuild, active_xcode, ctx.is_workspace)
            if schemes:
                ui.success(f"Schemes khả dụng ({len(schemes)}): {', '.join(schemes)}")
            else:
                ui.warning("Không lấy được danh sách Schemes từ xcodebuild -list.")
    else:
        ui.warning("Không phát hiện .xcworkspace hoặc .xcodeproj trong thư mục dự án hiện tại.")

    if ctx.is_kmp:
        mods_str = ", ".join(ctx.kmp_shared_modules) if ctx.kmp_shared_modules else "(không có module shared rõ ràng)"
        ui.info(f"Dự án KMP (Kotlin Multiplatform) — Shared modules: {mods_str}")

    if standalone:
        print()
        if has_issues:
            ui.error("Phát hiện một số vấn đề môi trường iOS/Xcode cần xử lý trước khi build/run.")
        else:
            ui.success("Môi trường iOS / Xcode đã sẵn sàng! Bạn có thể chạy: flash run --ios, flash build --ios, flash devices --ios, v.v.")

    return has_issues
