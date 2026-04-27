import struct
import unittest

from litime_bms import (
    LiTimeBMS,
    build_frame,
    litime_checksum,
    parse_litime_payload,
    C13_RESPONSE_ANCHOR,
    C16_RESPONSE_TAG,
)
from models import BatteryData


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_litime_frame(
    voltage_raw=13316,
    current_raw=5000,
    soc=91,
    soh=100,
    cycles=42,
    temp1=17,
    temp2=18,
    cell_raw=3329,
) -> bytes:
    """Build a minimal valid c_13 response frame with a correct checksum."""
    frame = bytearray(105)
    frame[0:2] = b'\x00\x00'
    frame[3] = 0x01
    frame[4] = 0x93
    frame[5:7] = b'\x55\xAA'
    frame[7] = 0x00
    struct.pack_into("<H", frame, 12, voltage_raw)
    for i in range(16):
        struct.pack_into("<H", frame, 16 + i * 2, cell_raw)
    struct.pack_into("<i", frame, 48, current_raw)
    frame[52] = temp1 & 0xFF
    frame[54] = temp2 & 0xFF
    struct.pack_into("<H", frame, 90, soc)
    struct.pack_into("<H", frame, 92, soh)
    struct.pack_into("<H", frame, 96, cycles)
    frame[104] = litime_checksum(frame, 104)
    return bytes(frame)


# ---------------------------------------------------------------------------
# Original parser smoke test
# ---------------------------------------------------------------------------

class TestLiTimeBMS(unittest.TestCase):
    def test_parse_valid_payload(self):
        frame = bytearray(105)
        frame[5:7] = b'\x55\xAA'
        frame[12:14] = b'\x04\x34'   # 13.316 V
        frame[48:52] = b'\x88\x13\x00\x00'  # 5000 (5.0 A discharge in spec)
        frame[90:92] = b'\x5B\x00'   # 91 % SOC
        frame[92:94] = b'\x64\x00'   # 100 % SOH
        frame[96:98] = b'\x2A\x00'   # 42 cycles
        for i in range(16):
            frame[16 + i * 2: 18 + i * 2] = b'\x01\x0D'
        frame[52] = 17
        frame[54] = 18
        parsed = parse_litime_payload(bytes(frame))
        self.assertEqual(parsed.voltage, 13.316)
        self.assertEqual(parsed.current, -5.0)   # sign-flipped for UI
        self.assertEqual(parsed.soc, 91)
        self.assertEqual(parsed.temp_env, 17)
        self.assertEqual(parsed.temp_mos, 18)


# ---------------------------------------------------------------------------
# Protocol contracts — every field at its spec-defined byte offset
# ---------------------------------------------------------------------------

class TestLiTimeProtocolContracts(unittest.TestCase):

    def test_voltage_at_bytes_12_13_uint16_le_div1000(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 12, 13800)
        self.assertAlmostEqual(parse_litime_payload(bytes(frame)).voltage, 13.800, places=5)

    def test_current_sign_flipped_positive_means_charging_in_ui(self):
        # Spec: positive int32 = discharge. Driver flips sign → UI positive = charging.
        frame = bytearray(105)
        struct.pack_into("<i", frame, 48, 5000)
        self.assertAlmostEqual(parse_litime_payload(bytes(frame)).current, -5.0, places=5)

    def test_current_negative_spec_means_positive_in_ui(self):
        frame = bytearray(105)
        struct.pack_into("<i", frame, 48, -8000)
        self.assertAlmostEqual(parse_litime_payload(bytes(frame)).current, 8.0, places=5)

    def test_cell_1_at_bytes_16_17(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 16, 3350)
        self.assertAlmostEqual(parse_litime_payload(bytes(frame)).cell_voltages[0], 3.350, places=5)

    def test_cell_16_at_bytes_46_47(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 46, 3100)
        self.assertAlmostEqual(parse_litime_payload(bytes(frame)).cell_voltages[15], 3.100, places=5)

    def test_zero_cell_voltage_stored_as_zero(self):
        frame = bytearray(105)
        self.assertEqual(parse_litime_payload(bytes(frame)).cell_voltages[0], 0.0)

    def test_temp1_at_byte_52_int8(self):
        frame = bytearray(105)
        frame[52] = 29
        self.assertEqual(parse_litime_payload(bytes(frame)).temp_env, 29)

    def test_temp2_at_byte_54_int8(self):
        frame = bytearray(105)
        frame[54] = 41
        self.assertEqual(parse_litime_payload(bytes(frame)).temp_mos, 41)

    def test_negative_temperature(self):
        frame = bytearray(105)
        frame[52] = 0xFF   # -1 as int8
        self.assertEqual(parse_litime_payload(bytes(frame)).temp_env, -1)

    def test_soc_at_bytes_90_91_uint16_le(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 90, 78)
        self.assertEqual(parse_litime_payload(bytes(frame)).soc, 78)

    def test_soh_at_bytes_92_93_uint16_le(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 92, 95)
        self.assertEqual(parse_litime_payload(bytes(frame)).soh, 95)

    def test_cycles_at_bytes_96_97_uint16_le(self):
        frame = bytearray(105)
        struct.pack_into("<H", frame, 96, 312)
        self.assertEqual(parse_litime_payload(bytes(frame)).cycles, 312)

    def test_frame_shorter_than_105_raises(self):
        with self.assertRaises(ValueError):
            parse_litime_payload(bytes(104))

    def test_cell_voltages_list_length_is_16(self):
        self.assertEqual(len(parse_litime_payload(bytes(105)).cell_voltages), 16)

    def test_raw_hex_is_hex_string_of_frame(self):
        frame = bytes(105)
        self.assertEqual(parse_litime_payload(frame).raw_hex, frame.hex())


# ---------------------------------------------------------------------------
# Frame framing / checksum contracts
# ---------------------------------------------------------------------------

class TestLiTimeFramingContracts(unittest.TestCase):

    def _make_bms(self):
        bms = LiTimeBMS("00:00:00:00:00:00")
        received = []
        bms.on_data_callback = received.append
        return bms, received

    def test_valid_frame_triggers_callback(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, make_litime_frame())
        self.assertEqual(len(received), 1)

    def test_callback_receives_correct_soc(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, make_litime_frame(soc=77))
        self.assertEqual(received[0].soc, 77)

    def test_bad_checksum_does_not_trigger_callback(self):
        bms, received = self._make_bms()
        frame = bytearray(make_litime_frame())
        frame[104] ^= 0xFF
        bms._notification_handler(None, bytes(frame))
        self.assertEqual(len(received), 0)

    def test_frame_split_across_two_notifications_is_reassembled(self):
        bms, received = self._make_bms()
        frame = make_litime_frame()
        bms._notification_handler(None, frame[:50])
        self.assertEqual(len(received), 0, "Partial frame must not fire callback")
        bms._notification_handler(None, frame[50:])
        self.assertEqual(len(received), 1)

    def test_two_consecutive_frames_both_processed(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, make_litime_frame(soc=80) + make_litime_frame(soc=81))
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].soc, 80)
        self.assertEqual(received[1].soc, 81)

    def test_junk_prefix_before_frame_is_skipped(self):
        bms, received = self._make_bms()
        bms._notification_handler(None, bytes(20) + make_litime_frame(soc=55))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].soc, 55)

    def test_c13_response_anchor_is_four_bytes(self):
        self.assertEqual(len(C13_RESPONSE_ANCHOR), 4)

    def test_c13_anchor_bytes(self):
        # type=0x01, tag-with-response-bit=0x93 (0x13|0x80), magic=55 AA
        self.assertEqual(C13_RESPONSE_ANCHOR[0], 0x01)
        self.assertEqual(C13_RESPONSE_ANCHOR[1], 0x93)
        self.assertEqual(C13_RESPONSE_ANCHOR[2:4], bytes([0x55, 0xAA]))

    def test_c16_response_tag_is_0x16_or_0x80(self):
        self.assertEqual(C16_RESPONSE_TAG, 0x16 | 0x80)

    def test_checksum_covers_bytes_2_to_end_minus_1(self):
        frame = bytearray(105)
        frame[2] = 0x10
        frame[3] = 0x20
        frame[103] = 0x05
        self.assertEqual(litime_checksum(frame, 104), (0x10 + 0x20 + 0x05) & 0xFF)


# ---------------------------------------------------------------------------
# build_frame request-encoding contracts (spec §2.1)
# ---------------------------------------------------------------------------

class TestBuildFrameContracts(unittest.TestCase):

    def test_frame_is_always_8_bytes(self):
        for tag in [0x13, 0x16, 0x0C, 0x22]:
            with self.subTest(tag=tag):
                self.assertEqual(len(build_frame(tag)), 8)

    def test_prefix_bytes_0_1_are_zero(self):
        frame = build_frame(0x13)
        self.assertEqual(frame[0], 0x00)
        self.assertEqual(frame[1], 0x00)

    def test_length_byte_is_0x04(self):
        self.assertEqual(build_frame(0x13)[2], 0x04)

    def test_type_byte_is_0x01(self):
        self.assertEqual(build_frame(0x13)[3], 0x01)

    def test_tag_is_at_byte_4(self):
        for tag in [0x13, 0x16, 0xFF]:
            with self.subTest(tag=tag):
                self.assertEqual(build_frame(tag)[4], tag)

    def test_magic_word_55_AA_at_bytes_5_6(self):
        frame = build_frame(0x13)
        self.assertEqual(frame[5], 0x55)
        self.assertEqual(frame[6], 0xAA)

    def test_checksum_equals_0x04_plus_tag_mod_256(self):
        for tag in [0x13, 0x16, 0x00, 0xFF]:
            with self.subTest(tag=tag):
                self.assertEqual(build_frame(tag)[7], (0x04 + tag) & 0xFF)

    def test_known_c13_poll_command(self):
        # Spec §3: 00 00 04 01 13 55 AA 17
        self.assertEqual(build_frame(0x13), bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17]))

    def test_known_c16_device_info_command(self):
        self.assertEqual(build_frame(0x16), bytes([0x00, 0x00, 0x04, 0x01, 0x16, 0x55, 0xAA, 0x1A]))


if __name__ == "__main__":
    unittest.main()
