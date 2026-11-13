#!/usr/bin/env python3
"""
Fastlane command execution: parse Fastfile, display runnable lanes via bundle exec,
allow interactive index selection, and execute with live streaming output.
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List
from core.fastlane import find_fastlane_config, FastlaneConfig, FastlaneLane
from core.config import ConfigManager
from core import ui

def run_fastlane(
    target: Optional[str] = None,
    list_only: bool = False,
    no_bundle: bool = False,
    extra_args: Optional[List[str]] = None
):
    """
    Execute or list Fastlane lanes.
    - target: lane name or 1-based index (e.g. '1' or 'build_debug').
    - list_only: if True, only prints available lanes.
    - no_bundle: if True, disables 'bundle exec' and invokes 'fastlane' directly.
    - extra_args: extra arguments forwarded to fastlane (e.g. key:value).
    """
    config = find_fastlane_config()
    if not config:
        ui.error("Không tìm thấy cấu hình Fastlane (Fastfile) trong dự án.")
        ui.info("Đảm bảo thư mục 'fastlane/' chứa file 'Fastfile' nằm trong thư mục gốc của dự án.")
        sys.exit(1)

    lanes = config.runnable_lanes
    if not lanes:
        ui.warning(f"Tìm thấy file '{config.fastfile_path.name}' nhưng không có lane nào có thể thực thi.")
        sys.exit(0)

    try:
        rel_fastfile = config.fastfile_path.relative_to(config.project_root)
    except ValueError:
        rel_fastfile = config.fastfile_path

    # Determine whether bundle exec can/should be used
    use_bundler = False
    if not no_bundle:
        if config.has_bundler:
            use_bundler = True
        elif config.gemfile_path and not shutil.which("bundle"):
            if shutil.which("fastlane"):
                ui.warning("Phát hiện Gemfile nhưng không tìm thấy lệnh 'bundle' trong PATH. Dùng trực tiếp 'fastlane'.")
                use_bundler = False
            else:
                ui.error("Không tìm thấy lệnh 'bundle' (Bundler) hoặc 'fastlane' trong PATH.")
                ui.info("Vui lòng cài đặt Bundler ('gem install bundler') hoặc Fastlane ('brew install fastlane').")
                sys.exit(1)
        elif not config.gemfile_path:
            if shutil.which("fastlane"):
                ui.info("Không tìm thấy Gemfile trong dự án. Sử dụng trực tiếp lệnh 'fastlane'.")
                use_bundler = False
            elif shutil.which("bundle"):
                use_bundler = True
            else:
                ui.error("Không tìm thấy lệnh 'bundle' hoặc 'fastlane' trong PATH.")
                sys.exit(1)
    else:
        if not shutil.which("fastlane"):
            ui.error("Tùy chọn --no-bundle được bật nhưng không tìm thấy lệnh 'fastlane' trong PATH.")
            sys.exit(1)

    # Build options list for display and selection
    options = []
    for lane in lanes:
        cmd = lane.get_exec_command(use_bundler=use_bundler, default_platform=config.default_platform)
        cmd_str = " ".join(cmd)

        label_parts = [f"{ui.Colors.BOLD}{lane.name}{ui.Colors.RESET}"]
        if lane.platform and (config.default_platform != lane.platform):
            label_parts.append(f"[{lane.platform}]")
        if lane.description:
            label_parts.append(f"- {lane.description}")
        label_parts.append(f"{ui.Colors.DIM}({cmd_str}){ui.Colors.RESET}")

        label = " ".join(label_parts)
        options.append((lane.name, label))

    # If --list flag is provided, print options and exit
    if list_only:
        ui.header("Danh sách các Lane Fastlane có thể chạy")
        ui.detail("Fastfile", str(rel_fastfile))
        if config.gemfile_path:
            try:
                rel_gem = config.gemfile_path.relative_to(config.project_root)
            except ValueError:
                rel_gem = config.gemfile_path
            ui.detail("Gemfile", str(rel_gem))
        ui.detail("Chế độ chạy", "bundle exec fastlane" if use_bundler else "fastlane")
        print()
        for idx, (name, label) in enumerate(options):
            print(f"  [{idx + 1}] {label}")
        sys.exit(0)

    # Resolve target lanes
    selected_lanes: List[FastlaneLane] = []

    if target:
        # Check if target is a 1-based index number
        if target.isdigit():
            num = int(target)
            if 1 <= num <= len(lanes):
                selected_lanes = [lanes[num - 1]]
            else:
                ui.error(f"Index [{target}] không hợp lệ. Vui lòng chọn trong khoảng 1 đến {len(lanes)}.")
                sys.exit(1)
        else:
            # Match by lane name or qualified name (e.g. 'android build_debug')
            target_lower = target.lower()
            matched = [
                l for l in lanes
                if l.name.lower() == target_lower or l.qualified_name.lower() == target_lower
            ]
            if matched:
                selected_lanes = matched
            else:
                ui.error(f"Không tìm thấy Fastlane lane '{target}'.")
                avail = ", ".join(l.name for l in lanes)
                ui.info(f"Các lane có sẵn: {avail}")
                sys.exit(1)
    else:
        # Interactive selection (same UX as flash run)
        ui.header("Fastlane Automation")
        ui.detail("Fastfile", str(rel_fastfile))
        if config.gemfile_path:
            try:
                rel_gem = config.gemfile_path.relative_to(config.project_root)
            except ValueError:
                rel_gem = config.gemfile_path
            ui.detail("Gemfile", str(rel_gem))
        ui.detail("Chế độ chạy", "bundle exec fastlane" if use_bundler else "fastlane")

        chosen_names = ui.ask_multiselect(
            title="Các tùy chọn Fastlane (bundle exec) có thể chạy:",
            options=options,
            all_label="⚡ Run all (Chạy tất cả lanes theo thứ tự)",
            default="1"
        )

        chosen_set = set(chosen_names)
        selected_lanes = [l for l in lanes if l.name in chosen_set]

    if not selected_lanes:
        ui.warning("Không có lane nào được chọn để thực thi.")
        sys.exit(0)

    # Execute selected lane(s)
    total_runs = 0
    failed_runs = 0

    for idx, lane in enumerate(selected_lanes):
        cmd = lane.get_exec_command(use_bundler=use_bundler, default_platform=config.default_platform)
        if extra_args:
            cmd.extend(extra_args)

        if len(selected_lanes) > 1:
            print()
            ui.info(f"{ui.Colors.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{ui.Colors.RESET}")
            ui.info(f"▶ [{idx + 1}/{len(selected_lanes)}] Tiến hành chạy Lane: {ui.Colors.CYAN}{ui.Colors.BOLD}{lane.name}{ui.Colors.RESET}")
        else:
            ui.header(f"Chạy Fastlane Lane [{lane.name}]")

        ui.detail("Lệnh thực thi", " ".join(cmd))
        ui.detail("Thư mục làm việc", str(config.working_dir))
        if lane.description:
            ui.detail("Mô tả", lane.description)
        print()

        # Prepare environment with SDK if detected
        env = os.environ.copy()
        cfg = ConfigManager.get_instance()
        if cfg.sdk_path:
            env.setdefault("ANDROID_HOME", cfg.sdk_path)
            env.setdefault("ANDROID_SDK_ROOT", cfg.sdk_path)

        res = subprocess.run(cmd, cwd=str(config.working_dir), env=env)

        if res.returncode != 0:
            ui.error(f"Fastlane lane '{lane.name}' thất bại với mã lỗi {res.returncode}!")
            failed_runs += 1
            if len(selected_lanes) == 1:
                sys.exit(res.returncode)
        else:
            ui.success(f"Hoàn tất chạy Fastlane lane '{lane.name}' thành công!")

        total_runs += 1

    # Summary when multiple lanes are executed
    if len(selected_lanes) > 1:
        print()
        if failed_runs == 0:
            ui.success(f"Hoàn tất! Đã chạy thành công tất cả ({total_runs}/{total_runs}) lanes.")
        else:
            ui.warning(f"Hoàn tất với cảnh báo: {total_runs - failed_runs} thành công, {failed_runs} thất bại.")
        if failed_runs > 0:
            sys.exit(1)
