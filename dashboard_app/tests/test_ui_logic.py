import unittest
from unittest.mock import MagicMock, patch
import asyncio
import os
import dashboard
from models import BatteryData

class TestDashboardBugs(unittest.TestCase):
    def setUp(self):
        # Redirect to temporary config for testing
        self.test_config = os.path.join(os.path.dirname(__file__), 'test_logic_batteries.json')
        os.environ['LITHIUM_CONFIG_PATH'] = self.test_config
        
        # Reset global state
        dashboard.state.batteries.clear()
        dashboard.state.devices = []
        dashboard.state.scanning = False
        dashboard.state.status_msg = ""
        dashboard.state.clients.clear()

    def tearDown(self):
        if os.path.exists(self.test_config):
            os.remove(self.test_config)
        os.environ.pop('LITHIUM_CONFIG_PATH', None)

    def test_bug_inplace_update(self):
        mac = "test_mac"
        # We need a real BatteryState because bms_callback expects it
        bat = dashboard.BatteryState("Test", mac, "EG4")
        dashboard.state.batteries[mac] = bat
        
        new_data = BatteryData(soc=95, voltage=13.3)
        dashboard.bms_callback(mac, new_data)
        
        self.assertEqual(bat.data.soc, 95)
        self.assertEqual(bat.data.voltage, 13.3)

    @patch('dashboard.scan_for_batteries')
    def test_bug_invisible_litime(self, mock_scan):
        mock_device = MagicMock()
        mock_device.name = None
        mock_device.address = "AA:BB:CC:00:00:01"
        mock_scan.return_value = [mock_device]
        
        # Pass None as device_sel_component since it's optional in my updated code
        asyncio.run(dashboard.do_scan(None))
        
        self.assertEqual(len(dashboard.state.devices), 1)
        self.assertEqual(dashboard.state.devices[0].address, "AA:BB:CC:00:00:01")

    def test_bug_dropdown_flicker_prevention(self):
        # This test checks for a specific line removal in the file
        with open(dashboard.__file__, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertNotIn('ui.timer(1.0, sidebar_controls_ui.refresh)', content)

if __name__ == '__main__':
    unittest.main()
