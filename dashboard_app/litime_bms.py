import asyncio
import logging
import struct
from bleak import BleakClient
from models import BatteryData

logger = logging.getLogger("LiTime_BMS")

CHAR_WRITE = "0000ffe2-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "0000ffe1-0000-1000-8000-00805f9b34fb"

# c_13 response anchor: type(01) + tag-with-response-bit(93) + magic(55 AA)
# Lives at frame bytes [3:7], making it a 4-byte discriminator against false positives.
C13_RESPONSE_ANCHOR = bytes([0x01, 0x93, 0x55, 0xAA])
C16_RESPONSE_TAG = 0x96  # 0x16 | 0x80

def build_frame(tag: int) -> bytes:
    # Verified framing: 00 00 04 01 <tag> 55 AA <(0x04 + tag) & 0xFF>
    checksum = (0x04 + tag) & 0xFF
    return bytes([0x00, 0x00, 0x04, 0x01, tag, 0x55, 0xAA, checksum])

def litime_checksum(frame: bytes, end: int) -> int:
    """Additive checksum over frame[2..end-1] per spec §2.3."""
    return sum(frame[2:end]) & 0xFF

def parse_litime_payload(data: bytes) -> BatteryData:
    if len(data) < 105:
        raise ValueError(f"Payload too short ({len(data)} bytes)")

    def p_u16(s): return int.from_bytes(data[s:s+2], 'little')
    def p_i32(s): return int.from_bytes(data[s:s+4], 'little', signed=True)
    def p_i8(s): return int.from_bytes(data[s:s+1], 'little', signed=True)

    # Voltage: [12..13] uint16 LE / 1000
    volts = p_u16(12) / 1000.0

    # Current: [48..51] int32 LE / 1000 (Positive = Discharge per spec)
    # Multiply by -1 to align with UI convention: Positive = Charging
    raw_current = p_i32(48) / 1000.0
    current = -raw_current

    # SOC: [90..91] uint16 LE
    soc = p_u16(90)

    # SOH: [92..93] uint16 LE
    soh = p_u16(92)

    # Cycles: [96..97] uint16 LE
    cycles = p_u16(96)

    # Temps: temp1 [52] (cells), temp2 [54] (MOSFET)
    t_cells = p_i8(52)
    t_mos = p_i8(54)

    cells = []
    for i in range(16):
        val = p_u16(16 + (i * 2))
        cells.append(val / 1000.0 if val > 0 else 0.0)

    return BatteryData(
        voltage=volts, current=current, cell_voltages=cells,
        temp_env=t_cells, temp_mos=t_mos, soc=soc, soh=soh, cycles=cycles,
        status=0, raw_hex=data.hex()
    )

class LiTimeBMS:
    def __init__(self, address_or_device):
        self.target = address_or_device
        self.client = None
        self.on_data_callback = None
        self.is_connected = False
        self._buffer = bytearray()
        self._lock = asyncio.Lock()

    def _on_disconnect(self, client):
        # Called by Bleak when the BLE link drops without an explicit disconnect().
        self.is_connected = False
        logger.warning(f"LiTime {getattr(client, 'address', '?')} disconnected unexpectedly")

    async def connect(self):
        self.client = BleakClient(
            self.target,
            timeout=20.0,
            disconnected_callback=self._on_disconnect,
        )
        await self.client.connect()
        self.is_connected = True
        await self.client.start_notify(CHAR_NOTIFY, self._notification_handler)

    async def disconnect(self):
        if self.client:
            if self.is_connected:
                await self.client.stop_notify(CHAR_NOTIFY)
                await self.client.disconnect()
            self.is_connected = False
            self.client = None

    async def fetch_metadata(self) -> dict:
        """Query c_16 (device-info) and return model/hw_version strings."""
        if not (self.client and self.is_connected):
            return {}

        collected = bytearray()
        done = asyncio.Event()

        def _capture(sender, raw):
            collected.extend(raw)
            if len(collected) >= 89:
                done.set()

        await self.client.stop_notify(CHAR_NOTIFY)
        await self.client.start_notify(CHAR_NOTIFY, _capture)
        try:
            await self.client.write_gatt_char(CHAR_WRITE, build_frame(0x16), response=True)
            await asyncio.wait_for(done.wait(), timeout=3.0)
        except Exception as e:
            logger.warning(f"fetch_metadata failed: {e}")
        finally:
            await self.client.stop_notify(CHAR_NOTIFY)
            await self.client.start_notify(CHAR_NOTIFY, self._notification_handler)

        # Validate: response tag 0x96, magic 55 AA at [5:7]
        if (len(collected) >= 89
                and collected[4] == C16_RESPONSE_TAG
                and collected[5:7] == b'\x55\xAA'):
            model = collected[48:88].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            hw_ver = collected[18:48].rstrip(b'\x00').decode('ascii', errors='replace').strip()
            return {"model": model or "LiTime", "hw_version": hw_ver}
        return {}

    async def poll(self):
        if not (self.client and self.is_connected):
            return
        async with self._lock:
            await self.client.write_gatt_char(CHAR_WRITE, build_frame(0x13), response=True)
            await asyncio.sleep(0.5)

    def _notification_handler(self, sender, data):
        self._buffer.extend(data)
        while True:
            # Locate the c_13 response anchor (bytes [3:7] of a valid frame).
            idx = self._buffer.find(C13_RESPONSE_ANCHOR)
            if idx == -1:
                if len(self._buffer) > 300:
                    self._buffer = self._buffer[-10:]
                break

            frame_start = idx - 3
            if frame_start < 0:
                # Anchor found too early; wait for the preceding prefix bytes.
                break

            # Verify the two zero-prefix bytes at the frame start.
            if self._buffer[frame_start] != 0x00 or self._buffer[frame_start + 1] != 0x00:
                # False anchor hit — skip past it and keep searching.
                self._buffer = self._buffer[idx + 4:]
                continue

            if frame_start + 105 > len(self._buffer):
                break  # Frame not yet complete; wait for more data.

            frame = bytes(self._buffer[frame_start:frame_start + 105])
            self._buffer = self._buffer[frame_start + 105:]

            # Validate additive checksum (spec §2.3): covers bytes [2..103].
            cs = litime_checksum(frame, 104)
            if cs != frame[104]:
                logger.warning(f"LiTime checksum mismatch: calc {cs:02X} != recv {frame[104]:02X}")
                continue

            try:
                res = parse_litime_payload(frame)
                if self.on_data_callback:
                    self.on_data_callback(res)
            except Exception as e:
                logger.error(f"LiTime Parse Err: {e}")
