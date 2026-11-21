#!/usr/bin/env python3
"""
Unit tests for multi-platform project detection (Android, Native Xcode, KMP),
active platform resolution, and KMP Fastlane discovery.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import ConfigManager
from core.fastlane import find_fastlane_config
from core.project import ProjectType, detect_project, resolve_active_platform


class TestProjectDetection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="flash_test_proj_")).resolve()
        ConfigManager._instance = None

    def tearDown(self):
        ConfigManager._instance = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_kmp_project(self) -> Path:
        root = self.temp_dir / "MyKmpApp"
        root.mkdir(parents=True, exist_ok=True)
        (root / "settings.gradle.kts").write_text(
            'rootProject.name = "MyKmpApp"\ninclude(":androidApp", ":shared")\n',
            encoding="utf-8",
        )
        (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

        (root / "androidApp").mkdir()
        (root / "androidApp" / "build.gradle.kts").write_text(
            'plugins { id("com.android.application") }\n',
            encoding="utf-8",
        )

        (root / "shared").mkdir()
        (root / "shared" / "build.gradle.kts").write_text(
            "kotlin {\n    iosSimulatorArm64()\n    iosArm64()\n}\n",
            encoding="utf-8",
        )

        ios_app_dir = root / "iosApp"
        ios_app_dir.mkdir()
        (ios_app_dir / "iosApp.xcodeproj").mkdir()
        return root

    def test_detect_android_only_project(self):
        root = self.temp_dir / "AndroidOnly"
        root.mkdir()
        (root / "settings.gradle.kts").write_text('include(":app")\n', encoding="utf-8")
        (root / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")

        ctx = detect_project(root)
        self.assertEqual(ctx.project_type, ProjectType.ANDROID)
        self.assertEqual(ctx.root, root.resolve())
        self.assertTrue(ctx.has_android)
        self.assertFalse(ctx.has_ios)
        self.assertFalse(ctx.is_kmp)
        self.assertIsNone(ctx.active_xcode_path)
        self.assertEqual(ctx.kmp_shared_modules, [])

    def test_detect_native_xcode_xcodeproj(self):
        root = self.temp_dir / "NativeIOS"
        root.mkdir()
        proj = root / "MyApp.xcodeproj"
        proj.mkdir()

        ctx = detect_project(root)
        self.assertEqual(ctx.project_type, ProjectType.XCODE)
        self.assertEqual(ctx.root, root.resolve())
        self.assertFalse(ctx.has_android)
        self.assertTrue(ctx.has_ios)
        self.assertFalse(ctx.is_kmp)
        self.assertFalse(ctx.is_workspace)
        self.assertEqual(ctx.xcode_project, proj.resolve())
        self.assertEqual(ctx.active_xcode_path, proj.resolve())
        self.assertEqual(ctx.ios_dir, root.resolve())

    def test_detect_native_xcode_prefers_xcworkspace_and_ignores_pods(self):
        root = self.temp_dir / "CocoaPodsIOS"
        root.mkdir()
        ws = root / "MyApp.xcworkspace"
        proj = root / "MyApp.xcodeproj"
        pods_proj = root / "Pods.xcodeproj"
        internal_ws = root / "project.xcworkspace"
        for d in (ws, proj, pods_proj, internal_ws):
            d.mkdir()

        ctx = detect_project(root)
        self.assertEqual(ctx.project_type, ProjectType.XCODE)
        self.assertTrue(ctx.is_workspace)
        self.assertEqual(ctx.xcode_workspace, ws.resolve())
        self.assertEqual(ctx.xcode_project, proj.resolve())
        self.assertEqual(ctx.active_xcode_path, ws.resolve())

        entry_names = [e.name for e in ctx.all_xcode_entries]
        self.assertIn("MyApp.xcworkspace", entry_names)
        self.assertIn("MyApp.xcodeproj", entry_names)
        self.assertNotIn("Pods.xcodeproj", entry_names)
        self.assertNotIn("project.xcworkspace", entry_names)

    def test_detect_kmp_project_with_shared_module(self):
        root = self._create_kmp_project()

        ctx = detect_project(root)
        self.assertEqual(ctx.project_type, ProjectType.KMP)
        self.assertEqual(ctx.root, root.resolve())
        self.assertTrue(ctx.has_android)
        self.assertTrue(ctx.has_ios)
        self.assertTrue(ctx.is_kmp)
        self.assertEqual(ctx.kmp_shared_modules, [":shared"])
        self.assertEqual(ctx.xcode_project, (root / "iosApp" / "iosApp.xcodeproj").resolve())
        self.assertEqual(ctx.ios_dir, (root / "iosApp").resolve())

    def test_kmp_subdir_iosapp_auto_detects_kmp_root_and_ios_platform(self):
        root = self._create_kmp_project()
        ios_dir = root / "iosApp"

        ConfigManager._instance = ConfigManager(start_dir=ios_dir)
        ctx = ConfigManager.get_instance().project_context

        self.assertEqual(ctx.project_type, ProjectType.KMP)
        self.assertEqual(ctx.root, root.resolve())
        self.assertEqual(ctx.start_dir, ios_dir.resolve())

        platform = resolve_active_platform(interactive=False)
        self.assertEqual(platform, "ios")

    def test_kmp_subdir_androidapp_auto_detects_android_platform(self):
        root = self._create_kmp_project()
        android_dir = root / "androidApp"

        ConfigManager._instance = ConfigManager(start_dir=android_dir)
        ctx = ConfigManager.get_instance().project_context

        self.assertEqual(ctx.project_type, ProjectType.KMP)
        self.assertEqual(ctx.root, root.resolve())
        self.assertEqual(ctx.start_dir, android_dir.resolve())

        platform = resolve_active_platform(interactive=False)
        self.assertEqual(platform, "android")

    def test_cli_flags_override_and_saved_target_platform(self):
        root = self._create_kmp_project()
        cfg = ConfigManager(start_dir=root)
        ConfigManager._instance = cfg

        # Explicit CLI flags always win regardless of config
        self.assertEqual(resolve_active_platform(cli_platform="ios", interactive=False), "ios")
        self.assertEqual(resolve_active_platform(cli_platform="android", interactive=False), "android")

        # Saved target_platform in .flash/config.json is respected at KMP root
        cfg.set_target_platform("ios")
        self.assertEqual(cfg.get_target_platform(), "ios")
        self.assertEqual(resolve_active_platform(interactive=False), "ios")

        # CLI flag still overrides saved target_platform
        self.assertEqual(resolve_active_platform(cli_platform="android", interactive=False), "android")

        cfg.set_target_platform("android")
        self.assertEqual(resolve_active_platform(interactive=False), "android")

    def test_kmp_fastlane_discovery_in_iosapp(self):
        root = self._create_kmp_project()
        ios_fastlane_dir = root / "iosApp" / "fastlane"
        ios_fastlane_dir.mkdir(parents=True)

        fastfile = ios_fastlane_dir / "Fastfile"
        fastfile.write_text(
            'default_platform(:ios)\n'
            'platform :ios do\n'
            '  desc "Upload to TestFlight"\n'
            '  lane :beta do\n'
            '    build_app\n'
            '  end\n'
            'end\n',
            encoding="utf-8",
        )
        gemfile = root / "iosApp" / "Gemfile"
        gemfile.write_text('source "https://rubygems.org"\ngem "fastlane"\n', encoding="utf-8")

        ConfigManager._instance = ConfigManager(start_dir=root)
        with patch("core.fastlane.shutil.which", return_value="/usr/bin/bundle"):
            fl_cfg = find_fastlane_config(start_dir=root)

        self.assertIsNotNone(fl_cfg)
        self.assertEqual(fl_cfg.fastfile_path, fastfile.resolve())
        self.assertEqual(fl_cfg.gemfile_path, gemfile.resolve())
        self.assertEqual(fl_cfg.working_dir, (root / "iosApp").resolve())
        self.assertEqual(fl_cfg.default_platform, "ios")
        self.assertTrue(fl_cfg.has_bundler)
        self.assertEqual([l.name for l in fl_cfg.runnable_lanes], ["beta"])


if __name__ == "__main__":
    unittest.main()
