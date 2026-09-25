import asyncio
import logging
import struct
from typing import List
from bleak import BleakClient
from models import BatteryData

logger = logging.getLogger("JBD_BMS")

SERVICE_UUID = "0000ff00-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "0000ff01-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "0000ff02-0000-1000-8000-00805f9b34fb"

HEADER = 0xDD
FOOTER = 0x77
REQUEST_TAG = 0xA5
STATUS_OK = 0x00

CMD_BASIC_INFO = 0x03
CMD_CELL_VOLTAGES = 0x04


def jbd_checksum(segment: bytes) -> int:
    """(0x10000 - sum(bytes)) & 0xFFFF, big-endian.

    `segment` is the cmd/status byte through the end of the data field —
    i.e. frame[2:4+len] for both requests (cmd, len) and responses
    (status, len, data).
    """
    return (0x10000 - sum(segment)) & 0xFFFF


def build_request(cmd: int) -> bytes:
    """Build a read request: DD A5 <cmd> 00 <chk_hi> <chk_lo> 77."""
    length = 0x00
    chk = jbd_checksum(bytes([cmd, length]))
    return bytes([HEADER, REQUEST_TAG, cmd, length]) + chk.to_bytes(2, 'big') + bytes([FOOTER])


def _validate_frame(frame: bytes, expected_cmd: int) -> bytes:
    """Validate header/cmd/status/length/checksum/footer, return the data field."""
    if len(frame) < 7:
        raise ValueError(f"Frame too short: {len(frame)} bytes")
    if frame[0] != HEADER:
        raise ValueError(f"Bad header byte: {frame[0]:02X}")
    if frame[1] != expected_cmd:
        raise ValueError(f"Unexpected cmd byte: {frame[1]:02X} (wanted {expected_cmd:02X})")
    status = frame[2]
    if status != STATUS_OK:
        raise ValueError(f"BMS returned error status: {status:02X}")

    length = frame[3]
    total_len = length + 7
    if len(frame) != total_len:
        raise ValueError(f"Frame length mismatch: got {len(frame)} bytes, expected {total_len}")
    if frame[-1] != FOOTER:
        raise ValueError(f"Bad footer byte: {frame[-1]:02X}")

    data = frame[4:4 + length]
    calc = jbd_checksum(frame[2:4 + length])
    recv = int.from_bytes(frame[4 + length:4 + length + 2], 'big')
    if calc != recv:
        raise ValueError(f"Checksum mismatch: expected {calc:04X}, got {recv:04X}")

    return data


def parse_jbd_basic(frame: bytes) -> BatteryData:
    data = _validate_frame(frame, CMD_BASIC_INFO)
    if len(data) < 23:
        raise ValueError(f"Basic info payload too short ({len(data)} bytes)")

    # [0:2] uint16 BE / 100
    voltage = struct.unpack(">H", data[0:2])[0] / 100.0
    # [2:4] int16 BE / 100. Positive = charging already matches UI convention — do not invert.
    current = struct.unpack(">h", data[2:4])[0] / 100.0
    # [6:8] uint16 BE / 100
    nominal_capacity_ah = struct.unpack(">H", data[6:8])[0] / 100.0
    # [8:10] uint16 BE
    cycles = struct.unpack(">H", data[8:10])[0]
    # [16:18] uint16 BE protection bitmask
    status = struct.unpack(">H", data[16:18])[0]
    # [19] RSOC %
    soc = data[19]
    # [22] NTC count
    ntc_count = data[22]

    offset = 23
    temps = []
    for _ in range(ntc_count):
        raw = struct.unpack(">H", data[offset:offset + 2])[0]
        temps.append((raw - 2731) / 10.0)
        offset += 2

    # Which physical sensor each NTC channel is wired to is unconfirmed on this
    # pack — we map NTC1 -> temp_env, NTC2 -> temp_mos when present.
    temp_env = round(temps[0]) if len(temps) >= 1 else 0
    temp_mos = round(temps[1]) if len(temps) >= 2 else 0

    # Optional tail (present on the reference pack): humidity(1) + alarm(2) +
    # full-charge capacity(2) + remaining(2) + balance current(2) = 9 bytes.
    soh = 0
    if len(data) >= offset + 9:
        full_charge_ah = struct.unpack(">H", data[offset + 3:offset + 5])[0] / 100.0
        if full_charge_ah > 0 and nominal_capacity_ah > 0:
            soh = min(100, round(full_charge_ah / nominal_capacity_ah * 100))

    return BatteryData(
        voltage=voltage, current=current,
        temp_env=temp_env, temp_mos=temp_mos,
        soc=soc, soh=soh, cycles=cycles,
        status=status, raw_hex=frame.hex(),
    )


def parse_jbd_cells(frame: bytes) -> List[float]:
    data = _validate_frame(frame, CMD_CELL_VOLTAGES)
    count = len(data) // 2
    cells = [struct.unpack(">H", data[i * 2:i * 2 + 2])[0] / 1000.0 for i in range(count)]
    if len(cells) < 16:
        cells += [0.0] * (16 - len(cells))
    return cells


class JBDBMS:
    def __init__(self, address_or_device):
        self.target = address_or_device
        self.client = None
        self.on_data_callback = None
        self.is_connected = False
        self._buffer = bytearray()
        self._last_cells = None
        self._lock = asyncio.Lock()

    def _on_disconnect(self, client):
        # Called by Bleak when the BLE link drops without an explicit disconnect().
        self.is_connected = False
        logger.warning(f"JBD {getattr(client, 'address', '?')} disconnected unexpectedly")

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

    async def poll(self):
        if not (self.client and self.is_connected):
            return
        async with self._lock:
            # The pack ignores the very first request written right after
            # start_notify, so cell voltages are requested first (a miss here
            # is harmless — cells just stay at their last known values) and
            # basic info follows, which is what actually emits BatteryData.
            # Basic info is withheld until cells have arrived once: the UI
            # renders the cell grid on first sync, so an all-zero first
            # reading would show 16 ghost cells.
            await self.client.write_gatt_char(CHAR_WRITE, build_request(CMD_CELL_VOLTAGES), response=False)
            await asyncio.sleep(0.3)
            await self.client.write_gatt_char(CHAR_WRITE, build_request(CMD_BASIC_INFO), response=False)
            await asyncio.sleep(0.5)

    def _notification_handler(self, sender, data):
        self._buffer.extend(data)
        while True:
            idx = self._buffer.find(bytes([HEADER]))
            if idx == -1:
                if len(self._buffer) > 300:
                    self._buffer = self._buffer[-10:]
                break
            if idx > 0:
                # Drop junk preceding the header byte.
                del self._buffer[:idx]

            if len(self._buffer) < 4:
                break  # need cmd/status/len bytes to size the frame

            length = self._buffer[3]
            total_len = length + 7
            if len(self._buffer) < total_len:
                break  # frame not fully reassembled yet; wait for more fragments

            frame = bytes(self._buffer[:total_len])
            cmd = frame[1]

            try:
                if cmd == CMD_CELL_VOLTAGES:
                    self._last_cells = parse_jbd_cells(frame)
                elif cmd == CMD_BASIC_INFO:
                    result = parse_jbd_basic(frame)
                    if self._last_cells is not None and self.on_data_callback:
                        result.cell_voltages = list(self._last_cells)
                        self.on_data_callback(result)
                else:
                    raise ValueError(f"Unknown cmd byte: {cmd:02X}")
            except ValueError as e:
                # Bad checksum/footer/status, or a stray 0xDD in unrelated
                # data. Drop just that byte and resync on the next 0xDD.
                logger.warning(f"JBD frame rejected ({e}); resyncing")
                del self._buffer[0]
                continue

            del self._buffer[:total_len]
