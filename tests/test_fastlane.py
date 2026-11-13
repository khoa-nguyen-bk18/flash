#!/usr/bin/env python3
"""
Unit tests for Fastlane discovery, Fastfile parser, and execution workflow.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil

from core.fastlane import (
    FastlaneLane,
    FastlaneConfig,
    parse_fastfile,
    find_fastlane_config
)
from commands.cmd_fastlane import run_fastlane


class TestFastlaneParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_standard_fastfile(self):
        fastfile_content = """
        default_platform(:android)

        platform :android do
          desc "Build debug APK"
          lane :build_debug do
            gradle(task: "clean assembleDebug")
          end

          desc "Build release APK"
          lane :build_release do
            gradle(task: "clean assembleRelease")
          end

          private_lane :helper_task do
            puts "Internal task"
          end
        end
        """
        ff_path = self.temp_dir / "Fastfile"
        ff_path.write_text(fastfile_content, encoding="utf-8")

        default_platform, lanes = parse_fastfile(ff_path)
        self.assertEqual(default_platform, "android")
        self.assertEqual(len(lanes), 3)

        runnable = [l for l in lanes if not l.is_private]
        self.assertEqual(len(runnable), 2)

        self.assertEqual(runnable[0].name, "build_debug")
        self.assertEqual(runnable[0].platform, "android")
        self.assertEqual(runnable[0].description, "Build debug APK")

        self.assertEqual(runnable[1].name, "build_release")
        self.assertEqual(runnable[1].platform, "android")

        private_lanes = [l for l in lanes if l.is_private]
        self.assertEqual(len(private_lanes), 1)
        self.assertEqual(private_lanes[0].name, "helper_task")

    def test_parse_multi_line_descriptions(self):
        fastfile_content = """
        platform :android do
          desc "First line of desc"
          desc "Second line of desc"
          lane :distribute do |options|
            puts "Deploying"
          end
        end
        """
        ff_path = self.temp_dir / "Fastfile"
        ff_path.write_text(fastfile_content, encoding="utf-8")

        _, lanes = parse_fastfile(ff_path)
        self.assertEqual(len(lanes), 1)
        self.assertEqual(lanes[0].name, "distribute")
        self.assertEqual(lanes[0].description, "First line of desc Second line of desc")

    def test_parse_multiple_platforms(self):
        fastfile_content = """
        platform :android do
          desc "Android lane"
          lane :build do
          end
        end

        platform :ios do
          desc "iOS lane"
          lane :build do
          end
        end
        """
        ff_path = self.temp_dir / "Fastfile"
        ff_path.write_text(fastfile_content, encoding="utf-8")

        _, lanes = parse_fastfile(ff_path)
        self.assertEqual(len(lanes), 2)
        self.assertEqual(lanes[0].platform, "android")
        self.assertEqual(lanes[0].name, "build")
        self.assertEqual(lanes[1].platform, "ios")
        self.assertEqual(lanes[1].name, "build")

    def test_command_generation(self):
        lane_android = FastlaneLane(name="build_debug", platform="android", description="Build APK")

        # When default platform is android, platform can be omitted
        cmd_bundle = lane_android.get_exec_command(use_bundler=True, default_platform="android")
        self.assertEqual(cmd_bundle, ["bundle", "exec", "fastlane", "build_debug"])

        # When default platform is None or different, platform is included
        cmd_bundle_diff = lane_android.get_exec_command(use_bundler=True, default_platform="ios")
        self.assertEqual(cmd_bundle_diff, ["bundle", "exec", "fastlane", "android", "build_debug"])

        # Without bundler
        cmd_no_bundle = lane_android.get_exec_command(use_bundler=False, default_platform="android")
        self.assertEqual(cmd_no_bundle, ["fastlane", "build_debug"])


class TestFastlaneCommands(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.fastlane_dir = self.temp_dir / "fastlane"
        self.fastlane_dir.mkdir(parents=True)
        self.fastfile = self.fastlane_dir / "Fastfile"
        self.fastfile.write_text("""
        default_platform(:android)
        platform :android do
          desc "Build debug APK"
          lane :build_debug do
          end

          desc "Build release APK"
          lane :build_release do
          end

          desc "Distribute APK"
          lane :distribute do
          end
        end
        """, encoding="utf-8")
        self.gemfile = self.temp_dir / "Gemfile"
        self.gemfile.write_text('gem "fastlane"', encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("core.fastlane.ConfigManager")
    def test_find_fastlane_config(self, mock_cfg_mgr):
        mock_cfg = MagicMock()
        mock_cfg.project_root = self.temp_dir
        mock_cfg_mgr.get_instance.return_value = mock_cfg

        config = find_fastlane_config(start_dir=self.temp_dir)
        self.assertIsNotNone(config)
        self.assertEqual(config.fastfile_path, self.fastfile.resolve())
        self.assertEqual(config.gemfile_path, self.gemfile.resolve())
        self.assertEqual(len(config.runnable_lanes), 3)

    @patch("commands.cmd_fastlane.subprocess.run")
    @patch("commands.cmd_fastlane.find_fastlane_config")
    @patch("commands.cmd_fastlane.shutil.which")
    def test_run_fastlane_by_index_cli(self, mock_which, mock_find_config, mock_subp):
        mock_which.return_value = "/usr/bin/bundle"
        lane1 = FastlaneLane(name="build_debug", platform="android", description="Build debug APK")
        lane2 = FastlaneLane(name="build_release", platform="android", description="Build release APK")
        config = FastlaneConfig(
            fastfile_path=self.fastfile,
            gemfile_path=self.gemfile,
            working_dir=self.temp_dir,
            project_root=self.temp_dir,
            default_platform="android",
            lanes=[lane1, lane2],
            has_bundler=True
        )
        mock_find_config.return_value = config
        mock_subp.return_value = MagicMock(returncode=0)

        # Target = '1'
        run_fastlane(target="1")

        mock_subp.assert_called_once()
        args, kwargs = mock_subp.call_args
        self.assertEqual(args[0], ["bundle", "exec", "fastlane", "build_debug"])
        self.assertEqual(kwargs["cwd"], str(self.temp_dir))

    @patch("commands.cmd_fastlane.subprocess.run")
    @patch("commands.cmd_fastlane.find_fastlane_config")
    @patch("commands.cmd_fastlane.shutil.which")
    def test_run_fastlane_by_name_cli(self, mock_which, mock_find_config, mock_subp):
        mock_which.return_value = "/usr/bin/bundle"
        lane1 = FastlaneLane(name="build_debug", platform="android", description="Build debug APK")
        lane2 = FastlaneLane(name="build_release", platform="android", description="Build release APK")
        config = FastlaneConfig(
            fastfile_path=self.fastfile,
            gemfile_path=self.gemfile,
            working_dir=self.temp_dir,
            project_root=self.temp_dir,
            default_platform="android",
            lanes=[lane1, lane2],
            has_bundler=True
        )
        mock_find_config.return_value = config
        mock_subp.return_value = MagicMock(returncode=0)

        # Target = 'build_release' with extra_args
        run_fastlane(target="build_release", extra_args=["key:value"])

        mock_subp.assert_called_once()
        args, kwargs = mock_subp.call_args
        self.assertEqual(args[0], ["bundle", "exec", "fastlane", "build_release", "key:value"])

    @patch("commands.cmd_fastlane.ui.ask_multiselect")
    @patch("commands.cmd_fastlane.subprocess.run")
    @patch("commands.cmd_fastlane.find_fastlane_config")
    @patch("commands.cmd_fastlane.shutil.which")
    def test_run_fastlane_interactive_index(self, mock_which, mock_find_config, mock_subp, mock_ask):
        mock_which.return_value = "/usr/bin/bundle"
        lane1 = FastlaneLane(name="build_debug", platform="android", description="Build debug APK")
        lane2 = FastlaneLane(name="build_release", platform="android", description="Build release APK")
        config = FastlaneConfig(
            fastfile_path=self.fastfile,
            gemfile_path=self.gemfile,
            working_dir=self.temp_dir,
            project_root=self.temp_dir,
            default_platform="android",
            lanes=[lane1, lane2],
            has_bundler=True
        )
        mock_find_config.return_value = config
        mock_subp.return_value = MagicMock(returncode=0)
        # User selects lane2 in interactive mode
        mock_ask.return_value = ["build_release"]

        run_fastlane()

        mock_ask.assert_called_once()
        mock_subp.assert_called_once()
        args, kwargs = mock_subp.call_args
        self.assertEqual(args[0], ["bundle", "exec", "fastlane", "build_release"])

    @patch("commands.cmd_fastlane.find_fastlane_config")
    def test_run_fastlane_no_fastfile(self, mock_find_config):
        mock_find_config.return_value = None
        with self.assertRaises(SystemExit) as cm:
            run_fastlane()
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
