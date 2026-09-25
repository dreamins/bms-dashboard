import struct
import unittest

from jbd_bms import (
    JBDBMS,
    jbd_checksum,
    build_request,
    parse_jbd_basic,
    parse_jbd_cells,
    HEADER,
    FOOTER,
    REQUEST_TAG,
    STATUS_OK,
    CMD_BASIC_INFO,
    CMD_CELL_VOLTAGES,
)


# ---------------------------------------------------------------------------
# Real frames captured from the user's 14S pack
# ---------------------------------------------------------------------------

REAL_BASIC_FRAME_HEX = (
    "dd030024151700cb03e206d6000134ea0000000000003239030e020c390b8e00000006d603e20000f8e877"
)
REAL_BASIC_FRAGMENTS_HEX = [
    "dd030024151700cb03e206d6000134ea00000000",
    "00003239030e020c390b8e00000006d603e20000",
    "f8e877",
]
REAL_CELLS_FRAME_HEX = (
    "dd04001c0f120f120f100f110f100f100f110f110f100f0f0f110f100f130f12fe2677"
)
REAL_CELLS_FRAGMENTS_HEX = [
    "dd04001c0f120f120f100f110f100f100f110f11",
    "0f100f0f0f110f100f130f12fe2677",
]
REAL_CELL_VOLTAGES = [
    3.858, 3.858, 3.856, 3.857, 3.856, 3.856, 3.857, 3.857,
    3.856, 3.855, 3.857, 3.856, 3.859, 3.858,
]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _wrap_response(cmd: int, data: bytes, status: int = STATUS_OK) -> bytes:
    """Build a valid DD ... 77 response frame around a data payload."""
    length = len(data)
    frame = bytes([HEADER, cmd, status, length]) + bytes(data)
    chk = jbd_checksum(frame[2:4 + length])
    return frame + chk.to_bytes(2, 'big') + bytes([FOOTER])


def make_jbd_basic_data(
    voltage_raw=5399,
    current_raw=203,
    remaining_raw=994,
    nominal_raw=1750,
    cycles=1,
    status=0,
    soc=57,
    cell_count=14,
    ntc_temps=(3129, 2958),
    tail=True,
    full_charge_raw=1750,
    tail_remaining_raw=994,
) -> bytes:
    """Build a basic-info (cmd 0x03) data payload with a correct byte layout."""
    data = bytearray()
    data += struct.pack(">H", voltage_raw)
    data += struct.pack(">h", current_raw)
    data += struct.pack(">H", remaining_raw)
    data += struct.pack(">H", nominal_raw)
    data += struct.pack(">H", cycles)
    data += struct.pack(">H", 0)   # production date (unused)
    data += bytes(4)               # balance status (unused)
    data += struct.pack(">H", status)
    data.append(0)                 # software version (unused)
    data.append(soc)
    data.append(0)                 # FET status (unused)
    data.append(cell_count)
    data.append(len(ntc_temps))
    for t in ntc_temps:
        data += struct.pack(">H", t)
    if tail:
        data.append(0)                            # humidity (unused)
        data += struct.pack(">H", 0)              # alarm (unused)
        data += struct.pack(">H", full_charge_raw)
        data += struct.pack(">H", tail_remaining_raw)
        data += struct.pack(">H", 0)              # balance current (unused)
    return bytes(data)


def make_jbd_basic_frame(**kwargs) -> bytes:
    return _wrap_response(CMD_BASIC_INFO, make_jbd_basic_data(**kwargs))


def make_jbd_cells_frame(cells=None) -> bytes:
    if cells is None:
        cells = [3.858] * 14
    data = b''.join(struct.pack(">H", round(v * 1000)) for v in cells)
    return _wrap_response(CMD_CELL_VOLTAGES, data)


# ---------------------------------------------------------------------------
# build_request contracts (spec: DD A5 <cmd> 00 <chk_hi> <chk_lo> 77)
# ---------------------------------------------------------------------------

class TestBuildRequestContracts(unittest.TestCase):

    def test_basic_info_request_matches_known_bytes(self):
        self.assertEqual(build_request(CMD_BASIC_INFO), bytes.fromhex("DDA50300FFFD77"))

    def test_cell_voltages_request_matches_known_bytes(self):
        self.assertEqual(build_request(CMD_CELL_VOLTAGES), bytes.fromhex("DDA50400FFFC77"))

    def test_request_is_always_7_bytes(self):
        for cmd in [0x03, 0x04, 0x00, 0xFF]:
            with self.subTest(cmd=cmd):
                self.assertEqual(len(build_request(cmd)), 7)

    def test_header_and_tag_bytes(self):
        frame = build_request(CMD_BASIC_INFO)
        self.assertEqual(frame[0], HEADER)
        self.assertEqual(frame[1], REQUEST_TAG)

    def test_length_byte_is_zero(self):
        self.assertEqual(build_request(CMD_BASIC_INFO)[3], 0x00)

    def test_footer_byte(self):
        self.assertEqual(build_request(CMD_BASIC_INFO)[-1], FOOTER)

    def test_cmd_byte_at_index_2(self):
        for cmd in [0x03, 0x04, 0xA1]:
            with self.subTest(cmd=cmd):
                self.assertEqual(build_request(cmd)[2], cmd)


# ---------------------------------------------------------------------------
# jbd_checksum contract
# ---------------------------------------------------------------------------

class TestChecksumContracts(unittest.TestCase):

    def test_checksum_is_two_complement_of_sum(self):
        segment = bytes([0x03, 0x00])
        self.assertEqual(jbd_checksum(segment), (0x10000 - 0x03) & 0xFFFF)

    def test_checksum_wraps_at_16_bits(self):
        segment = bytes([0xFF] * 300)  # sum comfortably exceeds 0x10000
        calc = jbd_checksum(segment)
        self.assertTrue(0 <= calc <= 0xFFFF)


# ---------------------------------------------------------------------------
# Real captured frame parsing
# ---------------------------------------------------------------------------

class TestRealCapturedFrames(unittest.TestCase):

    def test_parse_real_basic_frame(self):
        frame = bytes.fromhex(REAL_BASIC_FRAME_HEX)
        parsed = parse_jbd_basic(frame)
        self.assertAlmostEqual(parsed.voltage, 53.99, places=2)
        self.assertAlmostEqual(parsed.current, 2.03, places=2)
        self.assertEqual(parsed.soc, 57)
        self.assertEqual(parsed.cycles, 1)
        self.assertEqual(parsed.temp_env, 40)
        self.assertEqual(parsed.temp_mos, 23)
        self.assertEqual(parsed.soh, 100)
        self.assertEqual(parsed.status, 0)

    def test_parse_real_cells_frame(self):
        frame = bytes.fromhex(REAL_CELLS_FRAME_HEX)
        cells = parse_jbd_cells(frame)
        self.assertEqual(len(cells), 16)
        for actual, expected in zip(cells[:14], REAL_CELL_VOLTAGES):
            self.assertAlmostEqual(actual, expected, places=3)
        self.assertEqual(cells[14], 0.0)
        self.assertEqual(cells[15], 0.0)


# ---------------------------------------------------------------------------
# parse_jbd_basic protocol contracts
# ---------------------------------------------------------------------------

class TestJBDBasicProtocolContracts(unittest.TestCase):

    def test_voltage_uint16_be_div100(self):
        frame = make_jbd_basic_frame(voltage_raw=5390)
        self.assertAlmostEqual(parse_jbd_basic(frame).voltage, 53.90, places=5)

    def test_current_positive_is_charging_not_inverted(self):
        frame = make_jbd_basic_frame(current_raw=150)
        self.assertAlmostEqual(parse_jbd_basic(frame).current, 1.50, places=5)

    def test_current_negative_is_discharging(self):
        frame = make_jbd_basic_frame(current_raw=-150)
        self.assertAlmostEqual(parse_jbd_basic(frame).current, -1.50, places=5)

    def test_cycles_field(self):
        frame = make_jbd_basic_frame(cycles=312)
        self.assertEqual(parse_jbd_basic(frame).cycles, 312)

    def test_soc_field(self):
        frame = make_jbd_basic_frame(soc=42)
        self.assertEqual(parse_jbd_basic(frame).soc, 42)

    def test_status_bitmask_field(self):
        frame = make_jbd_basic_frame(status=0b0000000000000110)
        self.assertEqual(parse_jbd_basic(frame).status, 0b0000000000000110)

    def test_ntc_zero_yields_zero_temps(self):
        frame = make_jbd_basic_frame(ntc_temps=(), tail=False)
        parsed = parse_jbd_basic(frame)
        self.assertEqual(parsed.temp_env, 0)
        self.assertEqual(parsed.temp_mos, 0)

    def test_ntc_one_sets_env_only(self):
        frame = make_jbd_basic_frame(ntc_temps=(3031,), tail=False)  # 30.0 C
        parsed = parse_jbd_basic(frame)
        self.assertEqual(parsed.temp_env, 30)
        self.assertEqual(parsed.temp_mos, 0)

    def test_ntc_three_uses_first_two_only(self):
        frame = make_jbd_basic_frame(ntc_temps=(3031, 2931, 2831), tail=False)  # 30.0/20.0/10.0 C
        parsed = parse_jbd_basic(frame)
        self.assertEqual(parsed.temp_env, 30)
        self.assertEqual(parsed.temp_mos, 20)

    def test_temp_rounds_to_nearest_int(self):
        frame = make_jbd_basic_frame(ntc_temps=(3129, 2958), tail=False)  # 39.8/22.7 C
        parsed = parse_jbd_basic(frame)
        self.assertEqual(parsed.temp_env, 40)
        self.assertEqual(parsed.temp_mos, 23)

    def test_soh_from_full_charge_and_nominal(self):
        frame = make_jbd_basic_frame(nominal_raw=1750, full_charge_raw=1750)
        self.assertEqual(parse_jbd_basic(frame).soh, 100)

    def test_soh_capped_at_100(self):
        frame = make_jbd_basic_frame(nominal_raw=1000, full_charge_raw=1200)
        self.assertEqual(parse_jbd_basic(frame).soh, 100)

    def test_soh_partial_capacity(self):
        frame = make_jbd_basic_frame(nominal_raw=2000, full_charge_raw=1000)
        self.assertEqual(parse_jbd_basic(frame).soh, 50)

    def test_soh_zero_when_tail_absent(self):
        frame = make_jbd_basic_frame(tail=False)
        self.assertEqual(parse_jbd_basic(frame).soh, 0)

    def test_soh_zero_when_full_charge_zero(self):
        frame = make_jbd_basic_frame(full_charge_raw=0)
        self.assertEqual(parse_jbd_basic(frame).soh, 0)

    def test_soh_zero_when_nominal_zero(self):
        frame = make_jbd_basic_frame(nominal_raw=0, full_charge_raw=1750)
        self.assertEqual(parse_jbd_basic(frame).soh, 0)

    def test_raw_hex_is_hex_string_of_frame(self):
        frame = make_jbd_basic_frame()
        self.assertEqual(parse_jbd_basic(frame).raw_hex, frame.hex())

    def test_payload_too_short_raises(self):
        frame = _wrap_response(CMD_BASIC_INFO, bytes(10))
        with self.assertRaises(ValueError):
            parse_jbd_basic(frame)


# ---------------------------------------------------------------------------
# parse_jbd_basic / parse_jbd_cells frame-validation contracts
# ---------------------------------------------------------------------------

class TestFrameValidationContracts(unittest.TestCase):

    def test_bad_header_byte_raises(self):
        frame = bytearray(make_jbd_basic_frame())
        frame[0] = 0x00
        with self.assertRaises(ValueError):
            parse_jbd_basic(bytes(frame))

    def test_wrong_cmd_raises(self):
        frame = make_jbd_cells_frame()
        with self.assertRaises(ValueError):
            parse_jbd_basic(frame)

    def test_error_status_raises(self):
        frame = _wrap_response(CMD_BASIC_INFO, make_jbd_basic_data(), status=0x01)
        with self.assertRaises(ValueError):
            parse_jbd_basic(frame)

    def test_length_mismatch_raises(self):
        frame = bytearray(make_jbd_basic_frame())
        frame[3] = frame[3] + 1  # claim one more data byte than actually present
        with self.assertRaises(ValueError):
            parse_jbd_basic(bytes(frame))

    def test_bad_footer_raises(self):
        frame = bytearray(make_jbd_basic_frame())
        frame[-1] = 0x00
        with self.assertRaises(ValueError):
            parse_jbd_basic(bytes(frame))

    def test_bad_checksum_raises(self):
        frame = bytearray(make_jbd_basic_frame())
        frame[-2] ^= 0xFF
        with self.assertRaises(ValueError):
            parse_jbd_basic(bytes(frame))

    def test_cells_bad_checksum_raises(self):
        frame = bytearray(make_jbd_cells_frame())
        frame[-2] ^= 0xFF
        with self.assertRaises(ValueError):
            parse_jbd_cells(bytes(frame))


# ---------------------------------------------------------------------------
# parse_jbd_cells contracts
# ---------------------------------------------------------------------------

class TestJBDCellsContracts(unittest.TestCase):

    def test_cells_are_mv_over_1000(self):
        frame = make_jbd_cells_frame([3.301])
        self.assertAlmostEqual(parse_jbd_cells(frame)[0], 3.301, places=5)

    def test_fewer_than_16_cells_padded_with_zero(self):
        frame = make_jbd_cells_frame([3.3] * 4)
        cells = parse_jbd_cells(frame)
        self.assertEqual(len(cells), 16)
        self.assertEqual(cells[4:], [0.0] * 12)

    def test_more_than_16_cells_all_kept(self):
        frame = make_jbd_cells_frame([3.3] * 20)
        cells = parse_jbd_cells(frame)
        self.assertEqual(len(cells), 20)

    def test_exactly_16_cells_not_padded_or_truncated(self):
        frame = make_jbd_cells_frame([3.3] * 16)
        self.assertEqual(len(parse_jbd_cells(frame)), 16)


# ---------------------------------------------------------------------------
# JBDBMS._notification_handler framing / reassembly contracts
# ---------------------------------------------------------------------------

class TestJBDFramingContracts(unittest.TestCase):

    def _make_bms(self, prime_cells=True):
        bms = JBDBMS("00:00:00:00:00:00")
        received = []
        bms.on_data_callback = received.append
        if prime_cells:
            bms._notification_handler(None, make_jbd_cells_frame())
        return bms, received

    def test_valid_basic_frame_triggers_callback(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, make_jbd_basic_frame())
        self.assertEqual(len(received), 1)

    def test_basic_frame_before_any_cells_is_withheld(self):
        bms, received = self._make_bms(prime_cells=False)
        bms._notification_handler(None, make_jbd_basic_frame())
        self.assertEqual(len(received), 0)
        bms._notification_handler(None, make_jbd_cells_frame())
        bms._notification_handler(None, make_jbd_basic_frame())
        self.assertEqual(len(received), 1)

    def test_cells_frame_alone_does_not_trigger_callback(self):
        bms, received = self._make_bms(prime_cells=False)
        bms._notification_handler(None, make_jbd_cells_frame())
        self.assertEqual(len(received), 0)

    def test_cells_then_basic_populates_cell_voltages(self):
        bms, received = self._make_bms(prime_cells=False)
        bms._notification_handler(None, make_jbd_cells_frame([3.301] * 14))
        bms._notification_handler(None, make_jbd_basic_frame())
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(received[0].cell_voltages[0], 3.301, places=5)
        self.assertEqual(len(received[0].cell_voltages), 16)

    def test_real_fragments_cells_then_basic_full_reassembly(self):
        bms, received = self._make_bms(prime_cells=False)
        for chunk in REAL_CELLS_FRAGMENTS_HEX:
            bms._notification_handler(None, bytes.fromhex(chunk))
        self.assertEqual(len(received), 0, "Cell response alone must not fire the callback")
        for chunk in REAL_BASIC_FRAGMENTS_HEX:
            bms._notification_handler(None, bytes.fromhex(chunk))
        self.assertEqual(len(received), 1)
        data = received[0]
        self.assertAlmostEqual(data.voltage, 53.99, places=2)
        self.assertAlmostEqual(data.current, 2.03, places=2)
        self.assertEqual(data.soc, 57)
        for actual, expected in zip(data.cell_voltages[:14], REAL_CELL_VOLTAGES):
            self.assertAlmostEqual(actual, expected, places=3)

    def test_bad_checksum_does_not_trigger_callback(self):
        bms, received = self._make_bms()
        frame = bytearray(make_jbd_basic_frame())
        frame[-2] ^= 0xFF
        bms._notification_handler(None, bytes(frame))
        self.assertEqual(len(received), 0)

    def test_junk_prefix_before_frame_is_skipped(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, bytes(20) + make_jbd_basic_frame(soc=55))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].soc, 55)

    def test_garbage_resync_recovers_next_valid_frame(self):
        bms, received = self._make_bms()
        garbage = bytes([HEADER, 0x99, 0x00, 0x02, 0xAA, 0xBB, 0x00, 0x00, 0x77])
        bms._notification_handler(None, garbage + make_jbd_basic_frame(soc=61))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].soc, 61)

    def test_two_consecutive_frames_both_processed(self):
        bms, received = self._make_bms()
        bms._notification_handler(
            None, make_jbd_basic_frame(soc=80) + make_jbd_basic_frame(soc=81)
        )
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].soc, 80)
        self.assertEqual(received[1].soc, 81)

    def test_partial_frame_across_notifications_waits_for_rest(self):
        bms, received = self._make_bms()
        frame = make_jbd_basic_frame()
        bms._notification_handler(None, frame[:10])
        self.assertEqual(len(received), 0, "Partial frame must not fire callback")
        bms._notification_handler(None, frame[10:])
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()
