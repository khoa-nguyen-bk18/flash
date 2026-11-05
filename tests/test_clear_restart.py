#!/usr/bin/env python3
import sys
import unittest
from unittest.mock import patch, MagicMock

from core.device import DeviceInfo
from commands.cmd_quick import action_clear_restart
import main


class TestClearRestart(unittest.TestCase):
    @patch('commands.cmd_quick.action_clear_data')
    def test_action_clear_restart_calls_clear_data(self, mock_clear_data):
        dev = DeviceInfo('serial123', 'device', 'device', 'Pixel 7')
        action_clear_restart(dev, 'com.example.app', 'com.example.app/.MainActivity')
        mock_clear_data.assert_called_once_with(
            dev, 'com.example.app', restart=True, launcher='com.example.app/.MainActivity'
        )

    @patch('main.action_clear_restart')
    @patch('main.resolve_app_context')
    def test_main_clear_restart_command(self, mock_resolve, mock_clear_restart):
        dev = DeviceInfo('serial123', 'device', 'device', 'Pixel 7')
        mock_resolve.return_value = (dev, 'com.example.app', 'com.example.app/.MainActivity')

        for cmd in ['clear-restart', 'reset', 'cr', 'clear-and-restart']:
            with patch.object(sys, 'argv', ['flash', cmd]):
                main.main()
                mock_resolve.assert_called_with(device_id=None, flavor=None, package_name=None)
                mock_clear_restart.assert_called_with(dev, 'com.example.app', 'com.example.app/.MainActivity')
                mock_clear_restart.reset_mock()
                mock_resolve.reset_mock()

    @patch('main.action_clear_restart')
    @patch('main.action_restart')
    @patch('main.resolve_app_context')
    def test_main_restart_with_clear_flag(self, mock_resolve, mock_restart, mock_clear_restart):
        dev = DeviceInfo('serial123', 'device', 'device', 'Pixel 7')
        mock_resolve.return_value = (dev, 'com.example.app', 'com.example.app/.MainActivity')

        # flash restart -c should trigger action_clear_restart
        with patch.object(sys, 'argv', ['flash', 'restart', '-c']):
            main.main()
            mock_clear_restart.assert_called_once_with(dev, 'com.example.app', 'com.example.app/.MainActivity')
            mock_restart.assert_not_called()

        mock_clear_restart.reset_mock()
        mock_restart.reset_mock()

        # flash restart without -c should trigger regular action_restart
        with patch.object(sys, 'argv', ['flash', 'restart']):
            main.main()
            mock_restart.assert_called_once_with(dev, 'com.example.app', 'com.example.app/.MainActivity')
            mock_clear_restart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
