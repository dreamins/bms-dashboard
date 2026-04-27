import unittest
from unittest.mock import MagicMock, patch
import asyncio
from models import BatteryData
from litime_bms import LiTimeBMS, parse_litime_payload
from eg4_bms import EG4BMS, parse_eg4_frame

class TestBMSClasses(unittest.TestCase):
    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    @patch('litime_bms.BleakClient')
    def test_litime_bms_callback(self, mock_client):
        # Setup mock client
        instance = mock_client.return_value
        
        # Test state
        received_data = []
        def callback(data):
            received_data.append(data)
            
        bms = LiTimeBMS("AA:BB:CC:00:00:01")
        bms.on_data_callback = callback
        
        # Manually trigger notification handler
        test_payload = bytes.fromhex("000065019355AA006C33000004340000010D010D010D010D0000000000000000000000000000000000000000000000000000000011001200000000000000D94A08520000000000000000000000000000000000000000000000005B0067000000010000002901000094")
        bms._notification_handler(None, test_payload)
        
        self.assertEqual(len(received_data), 1)
        self.assertEqual(received_data[0].soc, 91)
        self.assertEqual(received_data[0].voltage, 13.316)

    @patch('eg4_bms.BleakClient')
    def test_eg4_bms_callback(self, mock_client):
        # Setup mock client
        instance = mock_client.return_value
        
        received_data = []
        def callback(data):
            received_data.append(data)
            
        bms = EG4BMS("AA:BB:CC:00:00:02")
        bms.on_data_callback = callback
        
        # Create a valid EG4 frame (83 bytes)
        import struct
        from eg4_bms import crc16_modbus
        frame = bytearray(83)
        frame[0:3] = bytes.fromhex("01034E")
        struct.pack_into(">H", frame, 3, 5400) # 54.00V
        crc = crc16_modbus(frame[:81])
        struct.pack_into("<H", frame, 81, crc)
        
        bms._notification_handler(None, frame)
        
        self.assertEqual(len(received_data), 1)
        self.assertEqual(received_data[0].voltage, 54.0)

if __name__ == '__main__':
    unittest.main()
