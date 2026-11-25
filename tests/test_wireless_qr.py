#!/usr/bin/env python3
import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import main
from commands import cmd_wireless
from core.device import DeviceInfo
from core.qrcode_gen import generate_qr_matrix, render_qr_string, render_qr_terminal


class TestQrCodeGen(unittest.TestCase):
    def test_version_selection_and_dimensions(self):
        # Version 1 (21x21) for short payload at EC M (max 14 bytes in Byte mode)
        m1 = generate_qr_matrix("HELLO", ec_level="M")
        self.assertEqual(len(m1), 21)
        self.assertEqual(len(m1[0]), 21)

        # Typical Android ADB pairing payload (42 bytes -> Version 3: 29x29 at EC M; 43+ bytes -> Version 4: 33x33)
        adb_payload_v3 = "WIFI:T:ADB;S:studio-AbCd1234;P:PassWord9;;"
        m_adb_v3 = generate_qr_matrix(adb_payload_v3, ec_level="M")
        self.assertEqual(len(m_adb_v3), 29)

        adb_payload_v4 = "WIFI:T:ADB;S:studio-AbCd1234;P:PassWord99;;"
        m_adb_v4 = generate_qr_matrix(adb_payload_v4, ec_level="M")
        self.assertEqual(len(m_adb_v4), 33)

        # Version 7 (45x45) and Version 10 (57x57) boundary payloads at EC M
        m7 = generate_qr_matrix("A" * 110, ec_level="M")
        self.assertEqual(len(m7), 45)
        m10 = generate_qr_matrix("A" * 200, ec_level="M")
        self.assertEqual(len(m10), 57)

    def test_ec_levels_supported_and_validation(self):
        for ec in ("L", "M", "Q", "H", "m"):
            mat = generate_qr_matrix("WIFI:T:ADB;S:studio-1234;P:abcd;;", ec_level=ec)
            self.assertGreaterEqual(len(mat), 21)

        with self.assertRaises(ValueError):
            generate_qr_matrix("test", ec_level="Z")

        with self.assertRaises(ValueError):
            generate_qr_matrix("A" * 300, ec_level="M")

    def test_structural_finder_timing_and_dark_module(self):
        # Version 2 -> size 25, dark module at (4*2 + 9, 8) = (17, 8)
        mat = generate_qr_matrix("WIFI:T:ADB;S:studio-a1b2;P:123456;;", ec_level="M")
        size = len(mat)
        self.assertGreaterEqual(size, 25)
        version = (size - 17) // 4

        # Check all 3 finder pattern centers are dark surrounded by light ring
        for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
            for r in range(top + 2, top + 5):
                for c in range(left + 2, left + 5):
                    self.assertTrue(mat[r][c])
            for i in range(7):
                self.assertTrue(mat[top][left + i])
                self.assertTrue(mat[top + 6][left + i])
                self.assertTrue(mat[top + i][left])
                self.assertTrue(mat[top + i][left + 6])

        # Dark module
        self.assertTrue(mat[4 * version + 9][8])

        # Timing pattern alternates along row 6 / col 6 between 8..size-9
        for i in range(8, size - 8):
            self.assertEqual(mat[6][i], i % 2 == 0)
            self.assertEqual(mat[i][6], i % 2 == 0)

    def test_terminal_renderer_ansi_and_invert(self):
        mat = generate_qr_matrix("HI", ec_level="L")
        plain = render_qr_terminal(mat, quiet_zone=2, invert=False, use_ansi=False)
        self.assertNotIn("\033[", plain)
        lines = plain.splitlines()
        self.assertGreater(len(lines), 0)
        # Width should be len(mat) + 2*quiet_zone
        self.assertEqual(len(lines[0]), len(mat) + 4)

        inverted_plain = render_qr_terminal(mat, quiet_zone=2, invert=True, use_ansi=False)
        self.assertNotEqual(plain, inverted_plain)
        self.assertTrue(inverted_plain.splitlines()[0].startswith("█"))

        # Default ANSI mode: gapless full-cell 256-color background spaces (no half-blocks)
        ansi_full = render_qr_string("HI", ec_level="L", quiet_zone=3, invert=False, use_ansi=True)
        self.assertIn("\033[48;5;16m", ansi_full)
        self.assertIn("\033[48;5;231m", ansi_full)
        self.assertNotIn("█", ansi_full)
        self.assertNotIn("▀", ansi_full)
        self.assertNotIn("▄", ansi_full)
        self.assertEqual(len(ansi_full.splitlines()), len(mat) + 6)

        ansi_full_inv = render_qr_string("HI", ec_level="L", quiet_zone=3, invert=True, use_ansi=True)
        self.assertTrue(ansi_full_inv.splitlines()[0].startswith("\033[48;5;16m"))
        self.assertTrue(ansi_full.splitlines()[0].startswith("\033[48;5;231m"))

        # Compact ANSI mode: half-blocks with pure 256-color fg/bg
        ansi_compact = render_qr_string("HI", ec_level="L", quiet_zone=3, invert=False, use_ansi=True, compact=True)
        self.assertIn("\033[38;5;16;48;5;231m", ansi_compact)
        self.assertIn("\033[0m", ansi_compact)

        ansi_compact_inv = render_qr_string("HI", ec_level="L", quiet_zone=3, invert=True, use_ansi=True, compact=True)
        self.assertIn("\033[38;5;231;48;5;16m", ansi_compact_inv)


class TestWirelessHelpers(unittest.TestCase):
    def test_parse_mdns_services(self):
        sample = """List of discovered mdns services
adb-RFARA3K4A5Y-2kp4nT\t_adb-tls-connect._tcp\t192.168.1.69:39675
studio-abcd1234\t_adb-tls-pairing._tcp.\t192.168.1.69:41234
adb-RFARA3K4A5Y-2kp4nT\t_adb-tls-connect._tcp.\t[fe80::1]:39675
"""
        parsed = cmd_wireless.parse_mdns_services(sample)
        self.assertEqual(len(parsed), 3)

        self.assertEqual(parsed[0].instance, "adb-RFARA3K4A5Y-2kp4nT")
        self.assertEqual(parsed[0].service_type, "_adb-tls-connect._tcp")
        self.assertEqual(parsed[0].host, "192.168.1.69")
        self.assertEqual(parsed[0].port, 39675)
        self.assertTrue(parsed[0].is_ipv4)

        self.assertEqual(parsed[1].service_type, "_adb-tls-pairing._tcp")
        self.assertEqual(parsed[2].host, "fe80::1")
        self.assertEqual(parsed[2].port, 39675)
        self.assertFalse(parsed[2].is_ipv4)

    def test_is_wireless_serial(self):
        self.assertTrue(cmd_wireless.is_wireless_serial("192.168.1.50:5555"))
        self.assertTrue(cmd_wireless.is_wireless_serial("adb-RFARA3K4A5Y._adb-tls-connect._tcp"))
        self.assertTrue(cmd_wireless.is_wireless_serial("adb-123._adb._tcp"))
        self.assertFalse(cmd_wireless.is_wireless_serial("RFARA3K4A5Y"))
        self.assertFalse(cmd_wireless.is_wireless_serial("emulator-5554"))

    def test_generate_pairing_credentials(self):
        svc, pwd, payload = cmd_wireless.generate_pairing_credentials()
        self.assertTrue(svc.startswith("studio-"))
        self.assertEqual(len(pwd), 8)
        self.assertEqual(payload, f"WIFI:T:ADB;S:{svc};P:{pwd};;")
        # Default payload (41 bytes) fits in QR Version 3 (29x29) at EC level M
        self.assertEqual(len(generate_qr_matrix(payload, ec_level="M")), 29)

        svc2, pwd2, payload2 = cmd_wireless.generate_pairing_credentials("custom-dev")
        self.assertEqual(svc2, "custom-dev")
        self.assertEqual(payload2, f"WIFI:T:ADB;S:custom-dev;P:{pwd2};;")

        with self.assertRaises(ValueError):
            cmd_wireless.generate_pairing_credentials("bad;name")


class TestWirelessQrFlows(unittest.TestCase):
    def _mock_cfg(self):
        cfg = MagicMock()
        cfg.get_adb_path.return_value = "/usr/bin/adb"
        return cfg

    @patch("commands.cmd_wireless.time.sleep")
    @patch("commands.cmd_wireless.subprocess.run")
    @patch("commands.cmd_wireless.get_connected_devices")
    @patch("commands.cmd_wireless.list_mdns_services")
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "mdns daemon version"))
    @patch("commands.cmd_wireless.generate_pairing_credentials")
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_qr_full_pair_and_connect(
        self,
        mock_cfg_inst,
        mock_creds,
        _mock_mdns_chk,
        mock_list_mdns,
        mock_get_devs,
        mock_run,
        _mock_sleep,
    ):
        cfg = self._mock_cfg()
        mock_cfg_inst.return_value = cfg
        mock_creds.return_value = ("studio-test1234", "SecretPass", "WIFI:T:ADB;S:studio-test1234;P:SecretPass;;")

        pairing_svc = cmd_wireless.MdnsService("studio-test1234", "_adb-tls-pairing._tcp", "192.168.1.50:41111")
        connect_svc = cmd_wireless.MdnsService("adb-xyz", "_adb-tls-connect._tcp", "192.168.1.50:39999")

        # 1st poll: empty; 2nd poll: pairing svc; 3rd poll (auto_connect): connect svc
        mock_list_mdns.side_effect = [
            [],
            [pairing_svc],
            [connect_svc],
        ]
        wireless_dev = DeviceInfo("192.168.1.50:39999", "device", "device", "Pixel 8")
        mock_get_devs.side_effect = [
            [],  # initial before_serials
            [],  # auto_connect check before adb connect
            [wireless_dev],  # after adb connect
        ]

        pair_proc = MagicMock(returncode=0, stdout="Successfully paired to 192.168.1.50:41111", stderr="")
        conn_proc = MagicMock(returncode=0, stdout="connected to 192.168.1.50:39999", stderr="")
        mock_run.side_effect = [pair_proc, conn_proc]

        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = cmd_wireless.run_wireless_qr(timeout=10, auto_connect=True)

        self.assertTrue(ok)
        mock_run.assert_any_call(
            ["/usr/bin/adb", "pair", "192.168.1.50:41111", "SecretPass"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        mock_run.assert_any_call(
            ["/usr/bin/adb", "connect", "192.168.1.50:39999"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        cfg.remember_wireless_device.assert_called_once_with("192.168.1.50:39999")

    @patch("commands.cmd_wireless.subprocess.run")
    @patch("commands.cmd_wireless.get_connected_devices")
    @patch("commands.cmd_wireless.list_mdns_services")
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "ok"))
    @patch("commands.cmd_wireless.generate_pairing_credentials")
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_qr_no_connect(
        self,
        mock_cfg_inst,
        mock_creds,
        _mock_mdns_chk,
        mock_list_mdns,
        mock_get_devs,
        mock_run,
    ):
        mock_cfg_inst.return_value = self._mock_cfg()
        mock_creds.return_value = ("studio-nc1", "Pass123456", "WIFI:T:ADB;S:studio-nc1;P:Pass123456;;")
        mock_get_devs.return_value = []
        mock_list_mdns.return_value = [
            cmd_wireless.MdnsService("studio-nc1", "_adb-tls-pairing._tcp", "192.168.1.70:42222")
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout="Successfully paired", stderr="")

        with redirect_stdout(io.StringIO()):
            ok = cmd_wireless.run_wireless_qr(timeout=5, auto_connect=False)

        self.assertTrue(ok)
        mock_run.assert_called_once()

    @patch("commands.cmd_wireless.check_mdns_available", return_value=(False, "mdns disabled"))
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_qr_mdns_unavailable(self, mock_cfg_inst, _mock_mdns_chk):
        mock_cfg_inst.return_value = self._mock_cfg()
        with redirect_stdout(io.StringIO()):
            ok = cmd_wireless.run_wireless_qr(timeout=5)
        self.assertFalse(ok)

    @patch("commands.cmd_wireless.time.sleep")
    @patch("commands.cmd_wireless.time.monotonic")
    @patch("commands.cmd_wireless.get_connected_devices", return_value=[])
    @patch("commands.cmd_wireless.list_mdns_services", return_value=[])
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "ok"))
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_qr_timeout(
        self,
        mock_cfg_inst,
        _mock_mdns_chk,
        _mock_list_mdns,
        _mock_get_devs,
        mock_mono,
        _mock_sleep,
    ):
        mock_cfg_inst.return_value = self._mock_cfg()
        ticks = iter([0.0, 0.0, 0.0, 0.0, 5.1, 5.1, 5.1])
        mock_mono.side_effect = lambda: next(ticks, 5.1)
        with redirect_stdout(io.StringIO()):
            ok = cmd_wireless.run_wireless_qr(timeout=5)
        self.assertFalse(ok)

    @patch("commands.cmd_wireless.subprocess.run")
    @patch("commands.cmd_wireless.get_connected_devices", return_value=[])
    @patch("commands.cmd_wireless.list_mdns_services")
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "ok"))
    @patch("commands.cmd_wireless.generate_pairing_credentials")
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_qr_pair_failure(
        self,
        mock_cfg_inst,
        mock_creds,
        _mock_mdns_chk,
        mock_list_mdns,
        _mock_get_devs,
        mock_run,
    ):
        mock_cfg_inst.return_value = self._mock_cfg()
        mock_creds.return_value = ("studio-fail", "BadPass123", "WIFI:T:ADB;S:studio-fail;P:BadPass123;;")
        mock_list_mdns.return_value = [
            cmd_wireless.MdnsService("studio-fail", "_adb-tls-pairing._tcp", "192.168.1.77:43333")
        ]
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error: protocol fault")
        with redirect_stdout(io.StringIO()):
            ok = cmd_wireless.run_wireless_qr(timeout=5)
        self.assertFalse(ok)

    @patch("commands.cmd_wireless.subprocess.run")
    @patch("commands.cmd_wireless.list_mdns_services")
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "ok"))
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_connect_auto_mdns(self, mock_cfg_inst, _mock_chk, mock_list_mdns, mock_run):
        cfg = self._mock_cfg()
        mock_cfg_inst.return_value = cfg
        mock_list_mdns.return_value = [
            cmd_wireless.MdnsService("adb-1", "_adb-tls-connect._tcp", "192.168.1.88:39000"),
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout="connected to 192.168.1.88:39000", stderr="")
        with redirect_stdout(io.StringIO()):
            ok = cmd_wireless.run_wireless_connect(None)
        self.assertTrue(ok)
        cfg.remember_wireless_device.assert_called_once_with("192.168.1.88:39000")

    @patch("commands.cmd_wireless.list_mdns_services")
    @patch("commands.cmd_wireless.check_mdns_available", return_value=(True, "ok"))
    @patch("commands.cmd_wireless.ConfigManager.get_instance")
    def test_run_wireless_discover(self, mock_cfg_inst, _mock_chk, mock_list_mdns):
        mock_cfg_inst.return_value = self._mock_cfg()
        mock_list_mdns.return_value = [
            cmd_wireless.MdnsService("adb-dev1", "_adb-tls-connect._tcp", "192.168.1.69:39675"),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            found = cmd_wireless.run_wireless_discover()
        self.assertEqual(len(found), 1)
        self.assertIn("192.168.1.69:39675", buf.getvalue())


class TestWirelessCliRouting(unittest.TestCase):
    @patch("main.resolve_active_platform", return_value="android")
    @patch("main.run_wireless_qr", return_value=True)
    def test_cli_wireless_qr_and_aliases(self, mock_qr, _mock_plat):
        for sub in ("qr", "scan", "qrcode"):
            with patch.object(sys, "argv", ["flash", "wireless", sub, "-t", "90", "--no-connect", "--invert", "--compact", "--name", "studio-my1"]):
                main.main()
            mock_qr.assert_called_with(timeout=90, auto_connect=False, invert=True, service_name="studio-my1", compact=True)
            mock_qr.reset_mock()

    @patch("main.resolve_active_platform", return_value="android")
    @patch("main.run_wireless_pair", return_value=True)
    def test_cli_wireless_pair_qr(self, mock_pair, _mock_plat):
        with patch.object(sys, "argv", ["flash", "wireless", "pair", "--qr", "-t", "45"]):
            main.main()
        mock_pair.assert_called_once_with(None, None, use_qr=True, timeout=45, invert=False, compact=False)

    @patch("main.resolve_active_platform", return_value="android")
    @patch("main.run_wireless_discover", return_value=[])
    def test_cli_wireless_discover(self, mock_disc, _mock_plat):
        with patch.object(sys, "argv", ["flash", "wireless", "discover"]):
            main.main()
        mock_disc.assert_called_once()

    @patch("main.resolve_active_platform", return_value="android")
    @patch("main.run_wireless_connect", return_value=True)
    def test_cli_wireless_connect_optional_endpoint(self, mock_conn, _mock_plat):
        with patch.object(sys, "argv", ["flash", "wireless", "connect"]):
            main.main()
        mock_conn.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
