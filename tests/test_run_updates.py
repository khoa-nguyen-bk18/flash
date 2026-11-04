#!/usr/bin/env python3
import unittest
from unittest.mock import patch, MagicMock
from io import StringIO
from pathlib import Path

from core import ui
from core.device import DeviceInfo, resolve_target_devices
from core.gradle import FlavorInfo, resolve_target_flavors, resolve_target_flavor
from commands.cmd_run import run_app

class TestFlashRunUpdates(unittest.TestCase):
    def test_multiselect_input_default_all(self):
        options = [('d1', 'Device 1'), ('d2', 'Device 2')]
        with patch('builtins.input', return_value=''):
            res = ui.ask_multiselect('Select', options, 'Run all')
            self.assertEqual(res, ['d1', 'd2'])

    def test_multiselect_input_a_char(self):
        options = [('d1', 'Device 1'), ('d2', 'Device 2')]
        with patch('builtins.input', return_value='a'):
            res = ui.ask_multiselect('Select', options, 'Run all')
            self.assertEqual(res, ['d1', 'd2'])

    def test_multiselect_input_single_item(self):
        options = [('d1', 'Device 1'), ('d2', 'Device 2')]
        with patch('builtins.input', return_value='1'):
            res = ui.ask_multiselect('Select', options, 'Run all')
            self.assertEqual(res, ['d1'])

    def test_multiselect_input_comma_separated(self):
        options = [('d1', 'Device 1'), ('d2', 'Device 2'), ('d3', 'Device 3')]
        with patch('builtins.input', return_value='1, 3'):
            res = ui.ask_multiselect('Select', options, 'Run all')
            self.assertEqual(res, ['d1', 'd3'])

    def test_multiselect_input_invalid_then_valid(self):
        options = [('d1', 'Device 1'), ('d2', 'Device 2')]
        with patch('builtins.input', side_effect=['99', '2']):
            res = ui.ask_multiselect('Select', options, 'Run all')
            self.assertEqual(res, ['d2'])

    def test_resolve_target_devices_multi(self):
        dev1 = DeviceInfo('ser1', 'device', 'device', 'Pixel 7')
        dev2 = DeviceInfo('ser2', 'device', 'device', 'S23')
        with patch('core.device.get_connected_devices', return_value=[dev1, dev2]), \
             patch('core.ui.ask_multiselect', return_value=['ser1', 'ser2']):
            selected = resolve_target_devices()
            self.assertEqual(len(selected), 2)
            self.assertEqual([d.serial for d in selected], ['ser1', 'ser2'])

    def test_resolve_target_flavors_multi(self):
        f1 = FlavorInfo('free')
        f2 = FlavorInfo('paid')
        with patch('core.gradle.get_product_flavors', return_value=[f1, f2]), \
             patch('core.ui.ask_multiselect', return_value=['free', 'paid']):
            selected = resolve_target_flavors()
            self.assertEqual(len(selected), 2)
            self.assertEqual([f.name for f in selected], ['free', 'paid'])

    def test_resolve_target_flavor_no_save_prompt(self):
        f1 = FlavorInfo('free')
        f2 = FlavorInfo('paid')
        with patch('core.gradle.get_product_flavors', return_value=[f1, f2]), \
             patch('core.ui.ask_choice', return_value='paid'), \
             patch('core.ui.ask_confirm') as mock_confirm:
            res = resolve_target_flavor()
            self.assertEqual(res.name, 'paid')
            mock_confirm.assert_not_called()

    @patch('commands.cmd_run.ConfigManager')
    @patch('commands.cmd_run.resolve_target_devices')
    @patch('commands.cmd_run.resolve_target_flavors')
    @patch('commands.cmd_run.execute_gradle')
    @patch('commands.cmd_run.find_best_apk')
    @patch('commands.cmd_run.subprocess.run')
    @patch('commands.cmd_run.detect_package_name')
    @patch('commands.cmd_run.resolve_launcher_activity')
    def test_run_app_multiple_devices_single_flavor(self, mock_launcher, mock_pkg, mock_subp,
                                                     mock_find_apk, mock_gradle, mock_flavors,
                                                     mock_devs, mock_cfg_mgr):
        cfg = MagicMock()
        cfg.get_adb_path.return_value = 'adb'
        cfg.get_target_module.return_value = ':app'
        mock_cfg_mgr.get_instance.return_value = cfg

        dev1 = DeviceInfo('ser1', 'device', 'device', 'Pixel 7')
        dev2 = DeviceInfo('ser2', 'device', 'device', 'Galaxy S23')
        mock_devs.return_value = [dev1, dev2]

        flavor1 = FlavorInfo('staging')
        mock_flavors.return_value = [flavor1]

        mock_gradle.return_value = MagicMock(returncode=0)

        fake_apk = MagicMock(spec=Path)
        fake_apk.exists.return_value = True
        fake_apk.name = 'app-staging-debug.apk'
        fake_apk.stat.return_value = MagicMock(st_size=15 * 1024 * 1024)
        mock_find_apk.return_value = fake_apk

        mock_subp.return_value = MagicMock(returncode=0, stdout='Success', stderr='')
        mock_pkg.return_value = 'com.example.staging'
        mock_launcher.return_value = 'com.example.MainActivity'

        run_app(variant='debug', no_build=False, stream_logcat=False)

        mock_gradle.assert_called_once_with('assembleStagingDebug', module=':app')
        install_calls = [c for c in mock_subp.call_args_list if 'install' in c[0][0]]
        self.assertEqual(len(install_calls), 2)
        start_calls = [c for c in mock_subp.call_args_list if 'am' in c[0][0]]
        self.assertEqual(len(start_calls), 2)

if __name__ == '__main__':
    unittest.main()
