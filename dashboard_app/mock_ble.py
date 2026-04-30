"""
Demo / test mock for BLE hardware.
Activated when LITHIUM_DEMO_MODE=1 is set in the environment.
Provides fake devices, instant connect, and synthetic BatteryData
so the full UI flow can be exercised without real hardware.
"""
import asyncio
from models import BatteryData


class MockDevice:
    def __init__(self, address: str, name: str):
        self.address = address
        self.name = name


MOCK_DEVICES = [
    MockDevice("AA:BB:CC:00:00:01", "EG4 Test Battery"),
    MockDevice("AA:BB:CC:00:00:02", "LiTime Test Battery"),
]


async def scan_for_batteries():
    await asyncio.sleep(0.3)
    return MOCK_DEVICES


def _eg4_data() -> BatteryData:
    return BatteryData(
        voltage=13.20, current=5.0,
        cell_voltages=[3.300, 3.302, 3.298, 3.301] + [0.0] * 12,
        temp_env=22, temp_mos=0,
        soc=85, soh=99, cycles=42, status=0,
        raw_hex="",
    )


def _litime_data() -> BatteryData:
    return BatteryData(
        voltage=13.10, current=-2.5,
        cell_voltages=[3.275, 3.274, 3.276, 3.275] + [0.0] * 12,
        temp_env=20, temp_mos=25,
        soc=91, soh=100, cycles=15, status=0,
        raw_hex="",
    )


class MockEG4BMS:
    def __init__(self, address: str):
        self.address = address
        self.on_data_callback = None
        self.is_connected = False

    async def connect(self):
        await asyncio.sleep(0.1)
        self.is_connected = True

    async def poll(self):
        await asyncio.sleep(0.05)
        if self.on_data_callback:
            self.on_data_callback(_eg4_data())

    async def disconnect(self):
        self.is_connected = False


class MockLiTimeBMS:
    def __init__(self, address: str):
        self.address = address
        self.on_data_callback = None
        self.is_connected = False

    async def connect(self):
        await asyncio.sleep(0.1)
        self.is_connected = True

    async def poll(self):
        await asyncio.sleep(0.05)
        if self.on_data_callback:
            self.on_data_callback(_litime_data())

    async def fetch_metadata(self) -> dict:
        return {"model": "LiTime Test", "hw_version": "1.0"}

    async def disconnect(self):
        self.is_connected = False
