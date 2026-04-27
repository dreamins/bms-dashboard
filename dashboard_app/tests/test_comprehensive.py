import asyncio
import os
import re
import struct
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from eg4_bms import crc16_modbus, parse_eg4_frame
from litime_bms import parse_litime_payload
from models import BatteryData
from dashboard import (
    state, BatteryState, ClientState,
    bms_callback, get_soc_color, get_cell_logic, get_status_info,
    provision_node_task, save_config, load_config,
)


# ---------------------------------------------------------------------------
# Original comprehensive tests
# ---------------------------------------------------------------------------

class TestComprehensive(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_config = os.path.join(os.path.dirname(__file__), 'test_batteries.json')
        os.environ['LITHIUM_CONFIG_PATH'] = self.test_config
        state.batteries.clear()
        state.clients.clear()
        if os.path.exists(self.test_config):
            os.remove(self.test_config)

    async def asyncTearDown(self):
        if os.path.exists(self.test_config):
            os.remove(self.test_config)
        os.environ.pop('LITHIUM_CONFIG_PATH', None)

    def test_eg4_cycle_count_offset(self):
        frame = bytearray(83)
        frame[0:3] = bytes.fromhex("01034E")
        struct.pack_into(">H", frame, 73, 567)
        struct.pack_into(">H", frame, 3, 5400)
        struct.pack_into(">h", frame, 5, -500)
        crc = crc16_modbus(frame[:81])
        struct.pack_into("<H", frame, 81, crc)
        self.assertEqual(parse_eg4_frame(frame).cycles, 567)

    def test_litime_dual_temps(self):
        frame = bytearray(105)
        frame[5:7] = b'\x55\xAA'
        frame[12:14] = b'\x00\x34'
        frame[52] = 25
        frame[54] = 30
        parsed = parse_litime_payload(bytes(frame))
        self.assertEqual(parsed.temp_env, 25)
        self.assertEqual(parsed.temp_mos, 30)

    def test_status_logic(self):
        txt, _, _ = get_status_info(5.0);   self.assertEqual(txt, "CHARGING")
        txt, _, _ = get_status_info(-5.0);  self.assertEqual(txt, "DISCHARGING")
        txt, _, _ = get_status_info(0.0);   self.assertEqual(txt, "IDLE")

    async def test_persistence_logic(self):
        mac = "AA:BB:CC:DD:EE:FF"
        state.batteries[mac] = BatteryState("Persist Test", mac, "EG4")
        save_config()
        await asyncio.sleep(0.1)
        self.assertTrue(os.path.exists(load_config.__module__ and self.test_config))
        state.batteries.clear()
        configs = load_config()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]['mac'], mac)

    def test_multi_user_isolation(self):
        state.clients.clear()
        with patch('dashboard.context.get_client') as mock_get:
            mock_get.return_value.id = "desktop"
            from dashboard import select_battery
            select_battery("MAC_1")
            mock_get.return_value.id = "mobile"
            select_battery("MAC_2")
            self.assertEqual(state.clients["desktop"].selected_mac, "MAC_1")
            self.assertEqual(state.clients["mobile"].selected_mac, "MAC_2")

    @patch('dashboard.layout.refresh')
    @patch('dashboard.EG4BMS', autospec=True)
    async def test_immediate_provision_feedback(self, mock_bms, mock_layout_refresh):
        state.clients["test_client"] = ClientState()
        instance = mock_bms.return_value
        instance.connect = AsyncMock()
        mac = "00:11:22:33:44:55"
        task = asyncio.create_task(provision_node_task(mac, 'EG4', "Test Battery"))
        await asyncio.sleep(0.1)
        self.assertIn(mac, state.batteries)
        mock_layout_refresh.assert_called()
        await task

    def test_ui_arrangement_logic(self):
        self.assertEqual(get_soc_color(51), "#10b981")
        voltages = [3.3, 3.3, 3.3, 3.0, 0.0]
        _, ghost, bad = get_cell_logic(voltages, 0); self.assertFalse(ghost or bad)
        _, ghost, bad = get_cell_logic(voltages, 3); self.assertTrue(bad)
        _, ghost, bad = get_cell_logic(voltages, 4); self.assertTrue(ghost)


# ---------------------------------------------------------------------------
# BMS driver lifecycle contracts
# ---------------------------------------------------------------------------

class TestBMSLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ['LITHIUM_CONFIG_PATH'] = os.path.join(
            os.path.dirname(__file__), '_lifecycle_test.json'
        )

    async def asyncTearDown(self):
        path = os.environ.pop('LITHIUM_CONFIG_PATH', None)
        if path and os.path.exists(path):
            os.remove(path)

    def _make_bat(self, suffix, bms_type="EG4"):
        from dashboard import poll_battery
        mac = f"CC:DD:EE:FF:00:{suffix}"
        bat = BatteryState("Test", mac, bms_type)
        state.batteries[mac] = bat
        return bat, mac

    async def _poll_with_mock(self, bat, poll_side_effect=None, connect_side_effect=None):
        from dashboard import poll_battery
        mock_bms = AsyncMock()
        if connect_side_effect:
            mock_bms.connect = AsyncMock(side_effect=connect_side_effect)
        else:
            mock_bms.connect = AsyncMock()
        if poll_side_effect:
            mock_bms.poll = AsyncMock(side_effect=poll_side_effect)
        else:
            mock_bms.poll = AsyncMock()
        bat.bms = mock_bms
        bat.connected = poll_side_effect is None and connect_side_effect is None
        with patch('dashboard.layout.refresh'):
            await poll_battery(bat)

    async def test_busy_flag_cleared_after_successful_poll(self):
        bat, mac = self._make_bat("01")
        bat.connected = True
        mock_bms = AsyncMock()
        mock_bms.poll = AsyncMock()
        bat.bms = mock_bms
        with patch('dashboard.layout.refresh'):
            from dashboard import poll_battery
            await poll_battery(bat)
        self.assertFalse(bat.busy)
        state.batteries.pop(mac, None)

    async def test_busy_flag_cleared_after_poll_exception(self):
        bat, mac = self._make_bat("02")
        bat.connected = True
        mock_bms = AsyncMock()
        mock_bms.poll = AsyncMock(side_effect=RuntimeError("BLE error"))
        bat.bms = mock_bms
        with patch('dashboard.layout.refresh'):
            from dashboard import poll_battery
            await poll_battery(bat)
        self.assertFalse(bat.busy)
        state.batteries.pop(mac, None)

    async def test_connected_goes_false_on_poll_error(self):
        bat, mac = self._make_bat("03")
        bat.connected = True
        mock_bms = AsyncMock()
        mock_bms.poll = AsyncMock(side_effect=RuntimeError("timeout"))
        bat.bms = mock_bms
        with patch('dashboard.layout.refresh'):
            from dashboard import poll_battery
            await poll_battery(bat)
        self.assertFalse(bat.connected)
        state.batteries.pop(mac, None)

    async def test_local_status_link_timeout_on_poll_error(self):
        bat, mac = self._make_bat("04")
        bat.connected = True
        mock_bms = AsyncMock()
        mock_bms.poll = AsyncMock(side_effect=RuntimeError("link lost"))
        bat.bms = mock_bms
        with patch('dashboard.layout.refresh'):
            from dashboard import poll_battery
            await poll_battery(bat)
        self.assertEqual(bat.local_status, "LINK TIMEOUT")
        state.batteries.pop(mac, None)

    async def test_local_status_conn_error_on_connect_failure(self):
        bat, mac = self._make_bat("05")
        bat.bms_type = "EG4"
        bat.connected = False
        mock_bms = AsyncMock()
        mock_bms.connect = AsyncMock(side_effect=OSError("not found"))
        bat.bms = mock_bms
        with patch('dashboard.layout.refresh'):
            from dashboard import poll_battery
            await poll_battery(bat)
        self.assertEqual(bat.local_status, "CONN ERROR")
        state.batteries.pop(mac, None)


# ---------------------------------------------------------------------------
# bms_callback data-propagation contracts
# ---------------------------------------------------------------------------

class TestBmsCallbackContracts(unittest.TestCase):
    def setUp(self):
        os.environ['LITHIUM_CONFIG_PATH'] = os.path.join(
            os.path.dirname(__file__), '_callback_test.json'
        )
        self.mac = "EE:FF:00:11:22:33"
        self.bat = BatteryState("CB Test", self.mac, "EG4")
        state.batteries[self.mac] = self.bat

    def tearDown(self):
        state.batteries.pop(self.mac, None)
        path = os.environ.pop('LITHIUM_CONFIG_PATH', None)
        if path and os.path.exists(path):
            os.remove(path)

    def _call(self, **kwargs):
        defaults = dict(
            voltage=13.0, current=5.0, cell_voltages=[3.25] * 16,
            temp_env=25, temp_mos=30, soc=90, soh=99, cycles=10,
            status=0, raw_hex="",
        )
        defaults.update(kwargs)
        with patch('dashboard.layout.refresh'):
            bms_callback(self.mac, BatteryData(**defaults))

    def test_voltage_propagated(self):
        self._call(voltage=14.5)
        self.assertAlmostEqual(self.bat.data.voltage, 14.5)

    def test_current_propagated(self):
        self._call(current=-12.3)
        self.assertAlmostEqual(self.bat.data.current, -12.3)

    def test_power_w_is_voltage_times_current(self):
        self._call(voltage=13.0, current=5.0)
        self.assertAlmostEqual(self.bat.data.power_w, 65.0, places=4)

    def test_power_w_negative_when_discharging(self):
        self._call(voltage=13.0, current=-5.0)
        self.assertAlmostEqual(self.bat.data.power_w, -65.0, places=4)

    def test_soc_propagated(self):
        self._call(soc=77);  self.assertEqual(self.bat.data.soc, 77)

    def test_soh_propagated(self):
        self._call(soh=88);  self.assertEqual(self.bat.data.soh, 88)

    def test_cycles_propagated(self):
        self._call(cycles=256);  self.assertEqual(self.bat.data.cycles, 256)

    def test_temp_env_propagated(self):
        self._call(temp_env=33);  self.assertEqual(self.bat.data.temp_env, 33)

    def test_temp_mos_propagated(self):
        self._call(temp_mos=41);  self.assertEqual(self.bat.data.temp_mos, 41)

    def test_cell_voltages_propagated(self):
        cells = [3.3] * 8 + [3.25] * 8
        self._call(cell_voltages=cells)
        self.assertEqual(self.bat.data.cell_voltages[:16], cells)

    def test_initial_sync_becomes_true_on_first_callback(self):
        self.assertFalse(self.bat.initial_sync)
        self._call()
        self.assertTrue(self.bat.initial_sync)

    def test_connected_becomes_true_on_callback(self):
        self.bat.connected = False
        self._call()
        self.assertTrue(self.bat.connected)

    def test_local_status_is_live_after_callback(self):
        self._call()
        self.assertEqual(self.bat.local_status, "LIVE")

    def test_unknown_mac_is_silently_ignored(self):
        with patch('dashboard.layout.refresh'):
            bms_callback("FF:FF:FF:FF:FF:FF", BatteryData())

    def test_last_update_is_formatted_time_string(self):
        self._call()
        self.assertRegex(self.bat.last_update, r'^\d{2}:\d{2}:\d{2}$')


# ---------------------------------------------------------------------------
# Persistence round-trip contracts
# ---------------------------------------------------------------------------

class TestPersistenceContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_cfg = os.path.join(os.path.dirname(__file__), '_persistence_contract.json')
        os.environ['LITHIUM_CONFIG_PATH'] = self.test_cfg
        state.batteries.clear()
        if os.path.exists(self.test_cfg):
            os.remove(self.test_cfg)

    async def asyncTearDown(self):
        if os.path.exists(self.test_cfg):
            os.remove(self.test_cfg)
        os.environ.pop('LITHIUM_CONFIG_PATH', None)

    async def test_saved_batteries_reload_with_correct_mac(self):
        mac = "AA:BB:CC:11:22:33"
        state.batteries[mac] = BatteryState("Persist", mac, "EG4")
        save_config()
        await asyncio.sleep(0.15)
        self.assertEqual(load_config()[0]['mac'], mac)

    async def test_saved_batteries_reload_with_correct_bms_type(self):
        mac = "AA:BB:CC:11:22:44"
        state.batteries[mac] = BatteryState("P2", mac, "LiTime/Redodo")
        save_config()
        await asyncio.sleep(0.15)
        self.assertEqual(load_config()[0]['bms_type'], "LiTime/Redodo")

    async def test_multiple_batteries_all_persisted(self):
        for i in range(3):
            mac = f"AA:BB:CC:00:00:{i:02X}"
            state.batteries[mac] = BatteryState(f"B{i}", mac, "EG4")
        save_config()
        await asyncio.sleep(0.15)
        self.assertEqual(len(load_config()), 3)

    async def test_load_from_missing_file_returns_empty_list(self):
        self.assertEqual(load_config(), [])

    async def test_load_from_corrupt_json_returns_empty_list(self):
        with open(self.test_cfg, 'w') as f:
            f.write("{not valid json")
        self.assertEqual(load_config(), [])

    async def test_save_uses_temp_file_atomically(self):
        mac = "AA:BB:CC:FF:FF:FF"
        state.batteries[mac] = BatteryState("Atomic", mac, "EG4")
        save_config()
        await asyncio.sleep(0.15)
        self.assertFalse(os.path.exists(self.test_cfg + '.tmp'), ".tmp must be cleaned up")
        self.assertTrue(os.path.exists(self.test_cfg))


if __name__ == "__main__":
    unittest.main()
