#!/usr/bin/env python3
"""
Unit tests for Xcode project/workspace JSON parsing, build settings parsing,
Info.plist reading, variant resolution, xcodebuild command generation, and .app discovery.
"""

import json
import os
import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import ConfigManager
from core.xcode_build import build_xcode_command, find_built_app
from core.xcode_project import (
    XcodeListInfo,
    XcodeVariantInfo,
    clear_build_settings_cache,
    parse_build_settings_output,
    parse_xcodebuild_list_json,
    read_app_plist_info,
    resolve_target_xcode_variants,
)


class TestXcodeProject(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="flash_test_xcode_")).resolve()
        ConfigManager._instance = None
        clear_build_settings_cache()

    def tearDown(self):
        ConfigManager._instance = None
        clear_build_settings_cache()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_xcodebuild_list_json_xcodeproj(self):
        proj_path = self.temp_dir / "SampleApp.xcodeproj"
        raw = json.dumps({
            "project": {
                "name": "SampleApp",
                "schemes": ["SampleApp", "SampleAppStaging"],
                "configurations": ["Debug", "Staging", "Release"],
                "targets": ["SampleApp", "SampleAppTests"],
            }
        })

        info = parse_xcodebuild_list_json(raw, proj_path)
        self.assertEqual(info.name, "SampleApp")
        self.assertFalse(info.is_workspace)
        self.assertEqual(info.schemes, ["SampleApp", "SampleAppStaging"])
        self.assertEqual(info.configurations, ["Debug", "Staging", "Release"])
        self.assertEqual(info.targets, ["SampleApp", "SampleAppTests"])
        self.assertEqual(info.path, proj_path)

    def test_parse_xcodebuild_list_json_xcworkspace_defaults_configurations(self):
        ws_path = self.temp_dir / "SampleApp.xcworkspace"
        ws_path.mkdir()
        raw = json.dumps({
            "workspace": {
                "name": "SampleApp",
                "schemes": ["SampleApp", "Pods-SampleApp"],
            }
        })

        info = parse_xcodebuild_list_json(raw, ws_path)
        self.assertEqual(info.name, "SampleApp")
        self.assertTrue(info.is_workspace)
        self.assertEqual(info.schemes, ["SampleApp", "Pods-SampleApp"])
        # Default fallback when workspace JSON omits configurations and no sibling xcodeproj exists
        self.assertEqual(info.configurations, ["Debug", "Release"])

    def test_parse_build_settings_output(self):
        raw_settings = """
User defaults from command line:
    IDEPackageSupportUseBuiltinSCM = YES

Build settings for action build and target SampleApp:
    ACTION = build
    PRODUCT_BUNDLE_IDENTIFIER = com.example.sampleapp
    WRAPPER_NAME = SampleApp.app
    TARGET_BUILD_DIR = /Users/dev/project/.flash/DerivedData/Build/Products/Debug-iphonesimulator
    PRODUCT_NAME = SampleApp
"""
        parsed = parse_build_settings_output(raw_settings)
        self.assertEqual(parsed["PRODUCT_BUNDLE_IDENTIFIER"], "com.example.sampleapp")
        self.assertEqual(parsed["WRAPPER_NAME"], "SampleApp.app")
        self.assertEqual(
            parsed["TARGET_BUILD_DIR"],
            "/Users/dev/project/.flash/DerivedData/Build/Products/Debug-iphonesimulator",
        )
        self.assertEqual(parsed["PRODUCT_NAME"], "SampleApp")

    def test_read_app_plist_info_from_real_temp_plist(self):
        app_dir = self.temp_dir / "SampleApp.app"
        app_dir.mkdir()
        plist_data = {
            "CFBundleIdentifier": "com.example.sampleapp.dev",
            "CFBundleDisplayName": "Sample Dev",
            "CFBundleName": "SampleApp",
            "CFBundleExecutable": "SampleApp",
            "CFBundleShortVersionString": "2.4.1",
        }
        with open(app_dir / "Info.plist", "wb") as fp:
            plistlib.dump(plist_data, fp)

        info = read_app_plist_info(app_dir)
        self.assertEqual(info["bundle_id"], "com.example.sampleapp.dev")
        self.assertEqual(info["display_name"], "Sample Dev")
        self.assertEqual(info["executable"], "SampleApp")
        self.assertEqual(info["version"], "2.4.1")

    def test_resolve_target_xcode_variants_single_scheme_fast_debug(self):
        proj_path = self.temp_dir / "MyApp.xcodeproj"
        proj_path.mkdir()
        ConfigManager._instance = ConfigManager(start_dir=self.temp_dir)

        list_info = XcodeListInfo(
            name="MyApp",
            schemes=["MyApp"],
            configurations=["Debug", "Release"],
            path=proj_path,
            is_workspace=False,
        )

        with patch("core.xcode_project.get_xcode_list_info", return_value=list_info), \
             patch("core.xcode_project.ui.ask_multiselect") as mock_prompt:
            variants = resolve_target_xcode_variants(interactive=True)

        self.assertEqual(variants, [XcodeVariantInfo(scheme="MyApp", configuration="Debug")])
        mock_prompt.assert_not_called()

    def test_resolve_target_xcode_variants_explicit_cli_flags(self):
        proj_path = self.temp_dir / "MyApp.xcodeproj"
        proj_path.mkdir()
        ConfigManager._instance = ConfigManager(start_dir=self.temp_dir)

        list_info = XcodeListInfo(
            name="MyApp",
            schemes=["MyAppDev", "MyAppProd"],
            configurations=["Debug", "Release"],
            path=proj_path,
            is_workspace=False,
        )

        with patch("core.xcode_project.get_xcode_list_info", return_value=list_info), \
             patch("core.xcode_project.ui.ask_multiselect") as mock_prompt:
            variants = resolve_target_xcode_variants(
                scheme_arg="myappprod",
                config_arg="release",
                interactive=True,
            )

        self.assertEqual(variants, [XcodeVariantInfo(scheme="MyAppProd", configuration="Release")])
        mock_prompt.assert_not_called()

    def test_resolve_target_xcode_variants_multi_scheme_interactive(self):
        proj_path = self.temp_dir / "MyApp.xcodeproj"
        proj_path.mkdir()
        ConfigManager._instance = ConfigManager(start_dir=self.temp_dir)

        list_info = XcodeListInfo(
            name="MyApp",
            schemes=["MyAppDev", "MyAppStaging"],
            configurations=["Debug", "Release"],
            path=proj_path,
            is_workspace=False,
        )

        with patch("core.xcode_project.get_xcode_list_info", return_value=list_info), \
             patch(
                 "core.xcode_project.ui.ask_multiselect",
                 return_value=["MyAppDev (Debug)", "MyAppStaging (Debug)"],
             ) as mock_prompt:
            variants = resolve_target_xcode_variants(interactive=True)

        mock_prompt.assert_called_once()
        self.assertEqual(
            variants,
            [
                XcodeVariantInfo(scheme="MyAppDev", configuration="Debug"),
                XcodeVariantInfo(scheme="MyAppStaging", configuration="Debug"),
            ],
        )

    def test_build_xcode_command_derived_data_and_workspace_vs_project(self):
        proj_root = self.temp_dir / "Proj"
        proj_root.mkdir()
        proj_path = proj_root / "App.xcodeproj"
        ws_path = proj_root / "App.xcworkspace"
        proj_path.mkdir()
        ws_path.mkdir()

        ConfigManager._instance = ConfigManager(start_dir=proj_root)
        expected_dd = str((proj_root / ".flash" / "DerivedData").resolve())

        with patch("core.xcode_build.shutil.which", return_value="/usr/bin/xcodebuild"):
            cmd_ws = build_xcode_command(
                xcode_path=ws_path,
                scheme="App",
                configuration="Debug",
                destination="platform=iOS Simulator,id=SIM-1",
                action="build",
            )
            cmd_proj = build_xcode_command(
                xcode_path=proj_path,
                scheme="App",
                configuration="Release",
                destination="generic/platform=iOS",
                action="archive",
            )

        self.assertIn("-workspace", cmd_ws)
        self.assertNotIn("-project", cmd_ws)
        self.assertEqual(cmd_ws[cmd_ws.index("-workspace") + 1], str(ws_path))
        self.assertEqual(cmd_ws[cmd_ws.index("-derivedDataPath") + 1], expected_dd)
        self.assertEqual(cmd_ws[-1], "build")

        self.assertIn("-project", cmd_proj)
        self.assertNotIn("-workspace", cmd_proj)
        self.assertEqual(cmd_proj[cmd_proj.index("-project") + 1], str(proj_path))
        self.assertEqual(cmd_proj[cmd_proj.index("-derivedDataPath") + 1], expected_dd)
        self.assertEqual(cmd_proj[-1], "archive")

    def test_find_built_app_locates_app_and_skips_dsym_and_tests(self):
        dd_path = self.temp_dir / ".flash" / "DerivedData"
        products_dir = dd_path / "Build" / "Products" / "Debug-iphonesimulator"
        products_dir.mkdir(parents=True)

        dsym = products_dir / "MyApp.app.dSYM"
        unit_tests = products_dir / "MyAppTests.app"
        ui_tests = products_dir / "MyAppUITests-Runner.app"
        real_app = products_dir / "MyApp.app"

        for d in (dsym, unit_tests, ui_tests, real_app):
            d.mkdir()

        # Make test apps newer to ensure they are still skipped
        now = real_app.stat().st_mtime
        os.utime(unit_tests, (now + 10, now + 10))
        os.utime(ui_tests, (now + 20, now + 20))

        found = find_built_app(
            derived_data_path=dd_path,
            configuration="Debug",
            is_simulator=True,
            scheme="MyApp",
        )
        self.assertEqual(found, real_app)

    def test_kmp_fallback_to_pbxproj_targets_when_no_xcscheme(self):
        from core.xcode_project import get_xcode_list_info

        proj = self.temp_dir / "iosApp" / "iosApp.xcodeproj"
        proj.mkdir(parents=True)
        (proj / "project.pbxproj").write_text(
            """
/* Begin PBXNativeTarget section */
        AA11 /* iosApp */ = {
            isa = PBXNativeTarget;
            name = iosApp;
        };
        AA22 /* iosAppTests */ = {
            isa = PBXNativeTarget;
            name = iosAppTests;
        };
/* End PBXNativeTarget section */
/* Begin XCBuildConfiguration section */
        BB11 /* Debug */ = {
            isa = XCBuildConfiguration;
            name = Debug;
        };
        BB22 /* Release */ = {
            isa = XCBuildConfiguration;
            name = Release;
        };
/* End XCBuildConfiguration section */
""",
            encoding="utf-8",
        )

        # Simulate xcodebuild -list -json returning empty schemes (fresh KMP project)
        mock_res = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "project": {
                    "name": "iosApp",
                    "schemes": [],
                    "targets": ["iosApp", "iosAppTests"],
                    "configurations": ["Debug", "Release"],
                }
            }),
            stderr="",
        )
        with patch("core.xcode_project.subprocess.run", return_value=mock_res), \
             patch.object(ConfigManager, "get_xcodebuild_path", return_value="/usr/bin/xcodebuild"):
            info = get_xcode_list_info(xcode_path=proj)

        self.assertIsNotNone(info)
        self.assertTrue(info.uses_targets_as_schemes)
        self.assertEqual(info.schemes, ["iosApp"])
        self.assertEqual(info.configurations, ["Debug", "Release"])

    def test_kmp_fallback_scans_disk_xcscheme_when_xcodebuild_list_fails(self):
        from core.xcode_project import get_xcode_list_info

        proj = self.temp_dir / "iosApp" / "iosApp.xcodeproj"
        schemes_dir = proj / "xcshareddata" / "xcschemes"
        schemes_dir.mkdir(parents=True)
        (schemes_dir / "iosApp.xcscheme").write_text("<Scheme/>", encoding="utf-8")

        mock_fail = MagicMock(returncode=1, stdout="", stderr="xcodebuild failed")
        with patch("core.xcode_project.subprocess.run", return_value=mock_fail), \
             patch.object(ConfigManager, "get_xcodebuild_path", return_value="/usr/bin/xcodebuild"):
            info = get_xcode_list_info(xcode_path=proj)

        self.assertIsNotNone(info)
        self.assertFalse(info.uses_targets_as_schemes)
        self.assertEqual(info.schemes, ["iosApp"])

    def test_build_xcode_command_uses_target_flag_when_use_target_true(self):
        proj_path = self.temp_dir / "iosApp.xcodeproj"
        proj_path.mkdir()
        with patch("core.xcode_build.shutil.which", return_value="/usr/bin/xcodebuild"):
            cmd = build_xcode_command(
                xcode_path=proj_path,
                scheme="iosApp",
                configuration="Debug",
                destination="generic/platform=iOS Simulator",
                use_target=True,
            )
        self.assertIn("-target", cmd)
        self.assertNotIn("-scheme", cmd)
        self.assertEqual(cmd[cmd.index("-target") + 1], "iosApp")

    def test_filter_main_app_schemes_excludes_extensions_and_switches_empty_workspace(self):
        from core.xcode_project import get_xcode_list_info

        ios_dir = self.temp_dir / "iosApp"
        ws = ios_dir / "iosApp.xcworkspace"
        proj = ios_dir / "iosApp.xcodeproj"
        schemes_dir = proj / "xcshareddata" / "xcschemes"
        ws.mkdir(parents=True)
        schemes_dir.mkdir(parents=True)

        (schemes_dir / "iosApp (Debug).xcscheme").write_text(
            '<Scheme><LaunchAction buildConfiguration="Debug">'
            '<BuildableProductRunnable><BuildableReference BuildableName="iosApp.app"/></BuildableProductRunnable>'
            '</LaunchAction></Scheme>',
            encoding="utf-8",
        )
        (schemes_dir / "iosApp (prod).xcscheme").write_text(
            '<Scheme><LaunchAction buildConfiguration="Release">'
            '<BuildableProductRunnable><BuildableReference BuildableName="iosApp.app"/></BuildableProductRunnable>'
            '</LaunchAction></Scheme>',
            encoding="utf-8",
        )
        (schemes_dir / "CapsidianWidgets.xcscheme").write_text(
            '<Scheme wasCreatedForAppExtension="YES"><LaunchAction buildConfiguration="Debug"/></Scheme>',
            encoding="utf-8",
        )

        def fake_run(cmd, **kwargs):
            if "-workspace" in cmd:
                return MagicMock(returncode=0, stdout=json.dumps({"workspace": {"name": "iosApp", "schemes": []}}), stderr="")
            return MagicMock(
                returncode=0,
                stdout=json.dumps({
                    "project": {
                        "name": "iosApp",
                        "schemes": ["CapsidianWidgets", "iosApp (Debug)", "iosApp (prod)"],
                        "configurations": ["Debug", "Release"],
                        "targets": ["iosApp", "CapsidianWidgets"],
                    }
                }),
                stderr="",
            )

        with patch("core.xcode_project.subprocess.run", side_effect=fake_run), \
             patch.object(ConfigManager, "get_xcodebuild_path", return_value="/usr/bin/xcodebuild"):
            info = get_xcode_list_info(xcode_path=ws)

        self.assertIsNotNone(info)
        self.assertEqual(info.path, proj)
        self.assertFalse(info.is_workspace)
        self.assertEqual(info.schemes, ["iosApp (Debug)", "iosApp (prod)"])
        self.assertEqual(info.scheme_launch_configs.get("iosApp (Debug)"), "Debug")
        self.assertEqual(info.scheme_launch_configs.get("iosApp (prod)"), "Release")


if __name__ == "__main__":
    unittest.main()
