#!/usr/bin/env python3
"""
Unit tests for iOS run workflow (auto-boot, multi-SDK build, --no-build),
iOS simulator/device actions (clear data, permissions, screenshot), and log colorization.
"""

import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from commands.cmd_ios_logs import colorize_ios_log_line
from commands.cmd_ios_run import run_ios_app
from core.config import ConfigManager
from core.ios_actions import (
    ios_clear_data,
    ios_grant_permissions,
    ios_revoke_permissions,
    ios_screenshot,
)
from core.ios_device import IOSDeviceInfo
from core.xcode_project import XcodeVariantInfo


class TestIOSRunAndActions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="flash_test_ios_run_")).resolve()
        ConfigManager._instance = None

    def tearDown(self):
        ConfigManager._instance = None
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_fake_app_bundle(self, name: str, bundle_id: str) -> Path:
        app_path = self.temp_dir / name
        app_path.mkdir(parents=True, exist_ok=True)
        with open(app_path / "Info.plist", "wb") as fp:
            plistlib.dump(
                {
                    "CFBundleIdentifier": bundle_id,
                    "CFBundleDisplayName": name.replace(".app", ""),
                    "CFBundleExecutable": name.replace(".app", ""),
                    "CFBundleShortVersionString": "1.0.0",
                },
                fp,
            )
        return app_path

    def test_run_ios_app_autoboot_build_install_launch_simulator(self):
        app_path = self._create_fake_app_bundle("MyApp.app", "com.example.myapp")
        sim = IOSDeviceInfo(
            udid="SIM-SHUTDOWN-1",
            name="iPhone 16 Pro",
            state="Shutdown",
            os_version="iOS 18.2",
            device_type="simulator",
        )

        def fake_boot(device, open_simulator_app=True):
            device.state = "Booted"
            return True

        mock_cfg = MagicMock()
        mock_cfg.get_derived_data_path.return_value = self.temp_dir / ".flash" / "DerivedData"

        with patch("commands.cmd_ios_run.ConfigManager.get_instance", return_value=mock_cfg), \
             patch("commands.cmd_ios_run.get_active_xcode_path", return_value=self.temp_dir / "MyApp.xcodeproj"), \
             patch("commands.cmd_ios_run.resolve_target_ios_devices", return_value=[sim]), \
             patch(
                 "commands.cmd_ios_run.resolve_target_xcode_variants",
                 return_value=[XcodeVariantInfo(scheme="MyApp", configuration="Debug")],
             ), \
             patch("commands.cmd_ios_run.boot_simulator", side_effect=fake_boot) as mock_boot, \
             patch("commands.cmd_ios_run.build_ios_app", return_value=app_path) as mock_build, \
             patch("core.ios_actions.sys.platform", "darwin"), \
             patch("core.ios_actions.shutil.which", return_value="/usr/bin/xcrun"), \
             patch(
                 "core.ios_actions.subprocess.run",
                 return_value=MagicMock(returncode=0, stdout="", stderr=""),
             ) as mock_subp:
            run_ios_app(no_build=False, stream_logs=False)

        mock_boot.assert_called_once_with(sim, open_simulator_app=True)
        mock_build.assert_called_once()
        self.assertTrue(mock_build.call_args.kwargs["is_simulator"])

        cmds = [c[0][0] for c in mock_subp.call_args_list]
        self.assertIn(["/usr/bin/xcrun", "simctl", "install", "SIM-SHUTDOWN-1", str(app_path)], cmds)
        self.assertIn(["/usr/bin/xcrun", "simctl", "launch", "SIM-SHUTDOWN-1", "com.example.myapp"], cmds)

    def test_run_ios_app_mixed_simulator_and_physical_builds_once_per_sdk(self):
        sim_app = self._create_fake_app_bundle("SimMyApp.app", "com.example.myapp")
        phys_app = self._create_fake_app_bundle("PhysMyApp.app", "com.example.myapp")

        sim = IOSDeviceInfo(
            udid="SIM-1", name="iPhone 16", state="Booted", os_version="iOS 18.2", device_type="simulator"
        )
        phys = IOSDeviceInfo(
            udid="PHYS-1",
            name="Real iPhone",
            state="Connected",
            os_version="iOS 18.1",
            device_type="physical",
            connection_type="usb",
            core_device_id="CORE-1",
        )

        def fake_build(**kwargs):
            return sim_app if kwargs.get("is_simulator") else phys_app

        mock_cfg = MagicMock()
        mock_cfg.get_derived_data_path.return_value = self.temp_dir / ".flash" / "DerivedData"

        with patch("commands.cmd_ios_run.ConfigManager.get_instance", return_value=mock_cfg), \
             patch("commands.cmd_ios_run.get_active_xcode_path", return_value=self.temp_dir / "MyApp.xcodeproj"), \
             patch("commands.cmd_ios_run.resolve_target_ios_devices", return_value=[sim, phys]), \
             patch(
                 "commands.cmd_ios_run.resolve_target_xcode_variants",
                 return_value=[XcodeVariantInfo(scheme="MyApp", configuration="Debug")],
             ), \
             patch("commands.cmd_ios_run.build_ios_app", side_effect=fake_build) as mock_build, \
             patch("commands.cmd_ios_run.ios_install_app", return_value=True) as mock_install, \
             patch("commands.cmd_ios_run.ios_launch_app", return_value=True) as mock_launch:
            run_ios_app(no_build=False, stream_logs=False)

        self.assertEqual(mock_build.call_count, 2)
        sdk_flags = [call.kwargs["is_simulator"] for call in mock_build.call_args_list]
        self.assertEqual(sdk_flags, [True, False])

        self.assertEqual(mock_install.call_count, 2)
        self.assertEqual(mock_launch.call_count, 2)
        mock_install.assert_any_call(sim, sim_app)
        mock_install.assert_any_call(phys, phys_app)
        mock_launch.assert_any_call(sim, "com.example.myapp")
        mock_launch.assert_any_call(phys, "com.example.myapp")

    def test_run_ios_app_no_build_skips_build_and_uses_cached_app(self):
        cached_app = self._create_fake_app_bundle("CachedApp.app", "com.example.cached")
        sim = IOSDeviceInfo(
            udid="SIM-1", name="iPhone 16", state="Booted", os_version="iOS 18.2", device_type="simulator"
        )
        mock_cfg = MagicMock()
        mock_cfg.get_derived_data_path.return_value = self.temp_dir / ".flash" / "DerivedData"

        with patch("commands.cmd_ios_run.ConfigManager.get_instance", return_value=mock_cfg), \
             patch("commands.cmd_ios_run.get_active_xcode_path", return_value=self.temp_dir / "MyApp.xcodeproj"), \
             patch("commands.cmd_ios_run.resolve_target_ios_devices", return_value=[sim]), \
             patch(
                 "commands.cmd_ios_run.resolve_target_xcode_variants",
                 return_value=[XcodeVariantInfo(scheme="CachedApp", configuration="Debug")],
             ), \
             patch("commands.cmd_ios_run.build_ios_app") as mock_build, \
             patch("commands.cmd_ios_run.find_built_app", return_value=cached_app) as mock_find, \
             patch("commands.cmd_ios_run.ios_install_app", return_value=True) as mock_install, \
             patch("commands.cmd_ios_run.ios_launch_app", return_value=True) as mock_launch:
            run_ios_app(no_build=True, stream_logs=False)

        mock_build.assert_not_called()
        mock_find.assert_called_once()
        mock_install.assert_called_once_with(sim, cached_app)
        mock_launch.assert_called_once_with(sim, "com.example.cached")

    def test_ios_clear_data_simulator_clears_sandbox_and_preserves_root(self):
        container = self.temp_dir / "AppDataContainer"
        docs = container / "Documents"
        caches = container / "Library" / "Caches"
        tmp = container / "tmp"
        for d in (docs, caches, tmp):
            d.mkdir(parents=True)

        (docs / "user.db").write_text("secret", encoding="utf-8")
        (caches / "img_cache").mkdir()
        (caches / "img_cache" / "pic.png").write_bytes(b"png")
        (tmp / "temp.log").write_text("temp", encoding="utf-8")

        sim = IOSDeviceInfo(
            udid="SIM-1", name="iPhone 16", state="Booted", os_version="iOS 18.2", device_type="simulator"
        )

        def fake_subp(cmd, **kwargs):
            if "get_app_container" in cmd:
                return MagicMock(returncode=0, stdout=str(container) + "\n", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("core.ios_actions.sys.platform", "darwin"), \
             patch("core.ios_actions.shutil.which", return_value="/usr/bin/xcrun"), \
             patch("core.ios_actions.subprocess.run", side_effect=fake_subp):
            ok = ios_clear_data(sim, "com.example.myapp", restart=False)

        self.assertTrue(ok)
        self.assertTrue(container.is_dir())
        self.assertTrue(docs.is_dir())
        self.assertTrue(caches.is_dir())
        self.assertTrue(tmp.is_dir())
        self.assertEqual(list(docs.iterdir()), [])
        self.assertEqual(list(caches.iterdir()), [])
        self.assertEqual(list(tmp.iterdir()), [])

    def test_ios_clear_data_physical_device_returns_false_cleanly(self):
        phys = IOSDeviceInfo(
            udid="PHYS-1",
            name="Real iPhone",
            state="Connected",
            os_version="iOS 18.1",
            device_type="physical",
            connection_type="usb",
            core_device_id="CORE-1",
        )

        with patch("core.ios_actions.sys.platform", "darwin"), \
             patch("core.ios_actions.shutil.which", return_value="/usr/bin/xcrun"), \
             patch("core.ios_actions.subprocess.run") as mock_subp:
            ok = ios_clear_data(phys, "com.example.myapp")

        self.assertFalse(ok)
        mock_subp.assert_not_called()

    def test_ios_grant_revoke_permissions_and_screenshot_commands(self):
        sim = IOSDeviceInfo(
            udid="SIM-99", name="iPhone 16", state="Booted", os_version="iOS 18.2", device_type="simulator"
        )
        ss_path = self.temp_dir / "shots" / "screen.png"

        with patch("core.ios_actions.sys.platform", "darwin"), \
             patch("core.ios_actions.shutil.which", return_value="/usr/bin/xcrun"), \
             patch(
                 "core.ios_actions.subprocess.run",
                 return_value=MagicMock(returncode=0, stdout="", stderr=""),
             ) as mock_subp:
            self.assertTrue(ios_grant_permissions(sim, "com.example.app"))
            self.assertTrue(ios_revoke_permissions(sim, "com.example.app", restart=False))
            self.assertTrue(ios_screenshot(sim, output_path=str(ss_path), open_after=False))

        cmds = [c[0][0] for c in mock_subp.call_args_list]
        self.assertEqual(
            cmds[0],
            ["/usr/bin/xcrun", "simctl", "privacy", "SIM-99", "grant", "all", "com.example.app"],
        )
        self.assertEqual(
            cmds[1],
            ["/usr/bin/xcrun", "simctl", "privacy", "SIM-99", "reset", "all", "com.example.app"],
        )
        self.assertEqual(
            cmds[2],
            ["/usr/bin/xcrun", "simctl", "io", "SIM-99", "screenshot", str(ss_path)],
        )

    def test_colorize_ios_log_line(self):
        samples = [
            "2026-11-21 08:10:12.123 Db MyApp[1234:5678] [com.example:net] Debug msg",
            "2026-11-21 08:10:12.124 In MyApp[1234:5678] [com.example:ui] Info msg",
            "2026-11-21 08:10:12.125 Df MyApp[1234:5678] [com.example:ui] Default msg",
            "2026-11-21 08:10:12.126 Er MyApp[1234:5678] [com.example:ui] Error msg",
            "2026-11-21 08:10:12.127 Ft MyApp[1234:5678] [com.example:ui] Fault msg",
            "Nov 21 08:10:13 iPhone MyApp[99] <Error>: Something went wrong",
            "Nov 21 08:10:14 iPhone MyApp[99] <Warning>: Low memory",
            "Plain unstructured syslog message",
        ]
        for line in samples:
            colored = colorize_ios_log_line(line)
            self.assertIsInstance(colored, str)
            self.assertTrue(len(colored) >= len(line))

        self.assertEqual(colorize_ios_log_line("Plain unstructured syslog message"), "Plain unstructured syslog message")


if __name__ == "__main__":
    unittest.main()
