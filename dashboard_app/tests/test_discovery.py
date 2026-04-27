import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import dashboard

class TestDiscovery(unittest.TestCase):
    def setUp(self):
        dashboard.state._devices = []
        dashboard.state.device_options = {}
        dashboard.state.scanning = False

    @patch('dashboard.scan_for_batteries', new_callable=AsyncMock)
    def test_do_scan_updates_ui(self, mock_scan):
        mock_device = MagicMock()
        mock_device.address = "AA:BB:CC:DD:EE:FF"
        mock_device.name = "Test Battery"
        mock_scan.return_value = [mock_device]
        
        mock_select = MagicMock()
        mock_select.options = {}
        
        # Trigger scan
        asyncio.run(dashboard.do_scan(mock_select))
        
        # Verify setter logic worked
        self.assertIn("AA:BB:CC:DD:EE:FF", dashboard.state.device_options)
        self.assertEqual(dashboard.state.device_options["AA:BB:CC:DD:EE:FF"], "Test Battery (AA:BB:CC:DD:EE:FF)")

    def test_device_options_reactive_sync(self):
        d1 = MagicMock(); d1.address = "11:22:33"; d1.name = "Normal"
        d2 = MagicMock(); d2.address = "AA:BB:CC:DD:EE:01"; d2.name = "Battery B"

        dashboard.state.devices = [d1, d2]
        self.assertEqual(dashboard.state.device_options["11:22:33"], "Normal (11:22:33)")
        self.assertEqual(dashboard.state.device_options["AA:BB:CC:DD:EE:01"], "Battery B (AA:BB:CC:DD:EE:01)")

    def test_sidebar_content_load(self):
        # Verify sidebar_content (which replaces discovery_ui tests)
        # doesn't crash and initializes with state.device_options
        dashboard.state.device_options = {"MAC1": "Name1"}
        
        # We need to mock context since sidebar_content calls get_client().id
        with patch('dashboard.context.get_client') as mock_context, \
             patch('dashboard.ui.select') as mock_select_factory, \
             patch('dashboard.ui.label'), \
             patch('dashboard.ui.button'), \
             patch('dashboard.ui.row'), \
             patch('dashboard.ui.card'), \
             patch('dashboard.ui.spinner'):
            
            mock_context.return_value.id = "test_client"
            dashboard.sidebar_content()
            # The first select call in sidebar_content is the device selector
            args, kwargs = mock_select_factory.call_args_list[0]
            self.assertEqual(kwargs['options'], {"MAC1": "Name1"})

if __name__ == '__main__':
    unittest.main()
