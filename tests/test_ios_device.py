#!/usr/bin/env python3
"""
Unit tests for iOS Simulator & Physical Device JSON parsing,
device priority sorting, and target device resolution.
"""

import json
import unittest
from unittest.mock import patch

from core.ios_device import (
    IOSDeviceInfo,
    get_all_ios_devices,
    parse_devicectl_devices_json,
    parse_simctl_devices_json,
    resolve_target_ios_devices,
)


class TestIOSDevice(unittest.TestCase):
    def test_parse_simctl_devices_json(self):
        raw = json.dumps({
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                    {
                        "udid": "SIM-BOOTED-1",
                        "name": "iPhone 16 Pro",
                        "state": "Booted",
                        "isAvailable": True,
                        "deviceTypeIdentifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro",
                    },
                    {
                        "udid": "SIM-UNAVAIL-1",
                        "name": "iPhone 14",
                        "state": "Shutdown",
                        "isAvailable": False,
                    },
                ],
                "com.apple.CoreSimulator.SimRuntime.tvOS-18-0": [
                    {
                        "udid": "TV-1",
                        "name": "Apple TV",
                        "state": "Shutdown",
                        "isAvailable": True,
                    }
                ],
            }
        })

        devices = parse_simctl_devices_json(raw)
        self.assertEqual(len(devices), 1)
        sim = devices[0]
        self.assertEqual(sim.udid, "SIM-BOOTED-1")
        self.assertEqual(sim.name, "iPhone 16 Pro")
        self.assertEqual(sim.state, "Booted")
        self.assertEqual(sim.os_version, "iOS 18.2")
        self.assertTrue(sim.is_simulator)
        self.assertTrue(sim.is_online)
        self.assertEqual(sim.xcodebuild_destination, "platform=iOS Simulator,id=SIM-BOOTED-1")
        self.assertIn("iPhone 16 Pro", sim.display_name)
        self.assertIn("iOS 18.2", sim.display_name)
        self.assertIn("SIM-BOOTED-1", sim.display_name)
        self.assertIn("Booted", sim.display_name)

    def test_parse_devicectl_devices_json_usb_and_wifi(self):
        raw = json.dumps({
            "result": {
                "devices": [
                    {
                        "identifier": "CORE-USB-1",
                        "hardwareProperties": {
                            "platform": "iOS",
                            "reality": "physical",
                            "udid": "00008130-USB111",
                            "marketingName": "iPhone 15 Pro",
                        },
                        "deviceProperties": {
                            "name": "Khoa's iPhone",
                            "osVersionNumber": "18.1",
                        },
                        "connectionProperties": {
                            "transportType": "wired",
                            "tunnelState": "connected",
                            "pairingState": "paired",
                        },
                    },
                    {
                        "identifier": "CORE-WIFI-2",
                        "hardwareProperties": {
                            "platform": "iPadOS",
                            "reality": "physical",
                            "udid": "00008130-WIFI222",
                            "marketingName": "iPad Pro",
                        },
                        "deviceProperties": {
                            "name": "Test iPad",
                            "osVersionNumber": "17.6",
                        },
                        "connectionProperties": {
                            "transportType": "localNetwork",
                            "tunnelState": "connected",
                            "pairingState": "paired",
                        },
                    },
                    {
                        "identifier": "CORE-OFFLINE-3",
                        "hardwareProperties": {
                            "platform": "iOS",
                            "reality": "physical",
                            "udid": "00008130-OFF333",
                            "marketingName": "iPhone 13",
                        },
                        "deviceProperties": {
                            "name": "Old iPhone",
                            "osVersionNumber": "16.5",
                        },
                        "connectionProperties": {
                            "transportType": "none",
                            "tunnelState": "unavailable",
                            "pairingState": "paired",
                        },
                    },
                    {
                        "identifier": "CORE-WATCH-4",
                        "hardwareProperties": {
                            "platform": "watchOS",
                            "reality": "physical",
                            "udid": "WATCH-UDID",
                        },
                        "deviceProperties": {"name": "Apple Watch"},
                        "connectionProperties": {"tunnelState": "connected"},
                    },
                ]
            }
        })

        devices = parse_devicectl_devices_json(raw)
        self.assertEqual(len(devices), 3)

        usb_dev, wifi_dev, offline_dev = devices
        self.assertEqual(usb_dev.core_device_id, "CORE-USB-1")
        self.assertEqual(usb_dev.udid, "00008130-USB111")
        self.assertEqual(usb_dev.connection_type, "usb")
        self.assertEqual(usb_dev.state, "Connected")
        self.assertTrue(usb_dev.is_physical)
        self.assertTrue(usb_dev.is_online)
        self.assertEqual(usb_dev.devicectl_identifier, "CORE-USB-1")
        self.assertEqual(usb_dev.xcodebuild_destination, "platform=iOS,id=00008130-USB111")

        self.assertEqual(wifi_dev.core_device_id, "CORE-WIFI-2")
        self.assertEqual(wifi_dev.udid, "00008130-WIFI222")
        self.assertEqual(wifi_dev.connection_type, "wifi")
        self.assertEqual(wifi_dev.state, "Connected")
        self.assertIn("📶", wifi_dev.display_name)

        self.assertEqual(offline_dev.state, "Unavailable")
        self.assertFalse(offline_dev.is_online)

    def test_get_all_ios_devices_ordering(self):
        sim_shutdown_old = IOSDeviceInfo(
            udid="SIM-OLD", name="iPhone 14", state="Shutdown", os_version="iOS 17.5", device_type="simulator"
        )
        sim_shutdown_new = IOSDeviceInfo(
            udid="SIM-NEW", name="iPhone 16", state="Shutdown", os_version="iOS 18.2", device_type="simulator"
        )
        sim_booted = IOSDeviceInfo(
            udid="SIM-BOOT", name="iPhone 15 Pro", state="Booted", os_version="iOS 18.0", device_type="simulator"
        )
        phys_connected = IOSDeviceInfo(
            udid="PHYS-1", name="My iPhone", state="Connected", os_version="iOS 18.1",
            device_type="physical", connection_type="usb", core_device_id="CORE-1"
        )
        phys_offline = IOSDeviceInfo(
            udid="PHYS-OFF", name="Offline iPhone", state="Unavailable", os_version="iOS 18.1",
            device_type="physical", connection_type="usb", core_device_id="CORE-2"
        )

        with patch("core.ios_device.get_ios_physical_devices", return_value=[phys_offline, phys_connected]), \
             patch("core.ios_device.get_ios_simulators", return_value=[sim_shutdown_old, sim_booted, sim_shutdown_new]):
            ordered = get_all_ios_devices(include_shutdown_sims=True)

        self.assertEqual(
            [d.udid for d in ordered],
            ["PHYS-1", "SIM-BOOT", "SIM-NEW", "SIM-OLD", "PHYS-OFF"],
        )

    def test_resolve_target_ios_devices_match_by_udid_and_name(self):
        dev1 = IOSDeviceInfo(udid="AAAA-1111", name="iPhone 16 Pro", state="Booted", os_version="iOS 18.2")
        dev2 = IOSDeviceInfo(udid="BBBB-2222", name="iPad Air", state="Booted", os_version="iOS 18.2")

        with patch("core.ios_device.get_all_ios_devices", return_value=[dev1, dev2]):
            by_udid = resolve_target_ios_devices(device_arg="BBBB-2222")
            self.assertEqual([d.udid for d in by_udid], ["BBBB-2222"])

            by_name = resolve_target_ios_devices(device_arg="iPhone 16")
            self.assertEqual([d.udid for d in by_name], ["AAAA-1111"])

    def test_resolve_target_ios_devices_multiselect(self):
        dev1 = IOSDeviceInfo(udid="AAAA-1111", name="iPhone 16 Pro", state="Booted", os_version="iOS 18.2")
        dev2 = IOSDeviceInfo(
            udid="PHYS-9999", name="Real iPhone", state="Connected", os_version="iOS 18.1",
            device_type="physical", connection_type="usb", core_device_id="CORE-9999"
        )

        with patch("core.ios_device.get_all_ios_devices", return_value=[dev2, dev1]), \
             patch("core.ios_device.ui.ask_multiselect", return_value=["PHYS-9999", "AAAA-1111"]) as mock_ms:
            selected = resolve_target_ios_devices(interactive=True)

        mock_ms.assert_called_once()
        self.assertEqual([d.udid for d in selected], ["PHYS-9999", "AAAA-1111"])


if __name__ == "__main__":
    unittest.main()
