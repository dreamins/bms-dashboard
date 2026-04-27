import asyncio
import struct
import logging
from bleak import BleakClient, BleakScanner
from typing import List, Optional, Callable
from models import BatteryData

logger = logging.getLogger("EG4_BMS")

SERVICE_UUID = "00001000-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "00001001-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "00001002-0000-1000-8000-00805f9b34fb"
POLL_COMMAND = bytes.fromhex("01030000002705D0")

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1: crc = (crc >> 1) ^ 0xA001
            else: crc >>= 1
    return crc

def parse_eg4_frame(frame: bytes) -> BatteryData:
    if len(frame) < 83:
        raise ValueError(f"Frame too short: {len(frame)} bytes")
        
    received_crc = struct.unpack("<H", frame[81:83])[0]
    calculated_crc = crc16_modbus(frame[:81])
    if received_crc != calculated_crc:
        raise ValueError(f"CRC mismatch: expected {calculated_crc:04X}, got {received_crc:04X}")

    # [3:5] uint16 BE / 100
    voltage = struct.unpack(">H", frame[3:5])[0] / 100.0
    # [5:7] int16 BE / 10
    current = struct.unpack(">h", frame[5:7])[0] / 10.0
    
    cells = []
    for i in range(16):
        cells.append(struct.unpack(">H", frame[7 + (i * 2):9 + (i * 2)])[0] / 1000.0)

    # Cycles at [73:75] uint16 BE (Register 35)
    # Register 0 is at index 3. Register 35 = 3 + 35*2 = 73.
    cycles = struct.unpack(">H", frame[73:75])[0]

    return BatteryData(
        voltage=voltage, current=current, cell_voltages=cells,
        temp_env=frame[44], soh=frame[50], soc=frame[52],
        cycles=cycles, status=frame[54], raw_hex=frame.hex()
    )

class EG4BMS:
    def __init__(self, address_or_device):
        self.target = address_or_device
        self.client = None
        self.on_data_callback = None
        self._buffer = bytearray()

    async def connect(self):
        self.client = BleakClient(self.target)
        await self.client.connect()
        await self.client.start_notify(NOTIFY_UUID, self._notification_handler)

    async def disconnect(self):
        if self.client:
            if self.client.is_connected:
                await self.client.stop_notify(NOTIFY_UUID)
                await self.client.disconnect()
            self.client = None

    async def poll(self):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(WRITE_UUID, POLL_COMMAND, response=False)

    def _notification_handler(self, sender, data):
        self._buffer.extend(data)
        while len(self._buffer) >= 83:
            header = bytes.fromhex("01034E")
            idx = self._buffer.find(header)
            if idx == -1:
                if len(self._buffer) > 200:
                    self._buffer = self._buffer[-10:] # Keep last bit in case header is split
                break
            
            if len(self._buffer) < idx + 83:
                break
                
            frame = self._buffer[idx:idx + 83]
            self._buffer = self._buffer[idx + 83:]
            try:
                data_obj = parse_eg4_frame(frame)
                if self.on_data_callback:
                    self.on_data_callback(data_obj)
            except Exception as e:
                logger.error(f"Error parsing EG4 frame: {e}")

async def scan_for_batteries():
    return await BleakScanner.discover(timeout=5.0)
