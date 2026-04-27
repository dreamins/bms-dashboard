import struct
import unittest

from eg4_bms import crc16_modbus, parse_eg4_frame


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def make_eg4_frame(
    voltage_raw=1330,
    current_raw=-100,
    temp_env=25,
    soh=100,
    soc=95,
    status=0,
    cycles=0,
    cell_raw=3320,
) -> bytes:
    frame = bytearray(83)
    frame[0:3] = bytes.fromhex("01034E")
    struct.pack_into(">H", frame, 3, voltage_raw)
    struct.pack_into(">h", frame, 5, current_raw)
    for i in range(16):
        struct.pack_into(">H", frame, 7 + i * 2, cell_raw)
    frame[44] = temp_env
    frame[50] = soh
    frame[52] = soc
    frame[54] = status
    struct.pack_into(">H", frame, 73, cycles)
    crc = crc16_modbus(frame[:81])
    struct.pack_into("<H", frame, 81, crc)
    return bytes(frame)


# ---------------------------------------------------------------------------
# Original parser smoke tests
# ---------------------------------------------------------------------------

class TestEG4BMS(unittest.TestCase):
    def test_parse_valid_payload(self):
        frame = make_eg4_frame(
            voltage_raw=1330, current_raw=-100,
            temp_env=25, soh=100, soc=95, cycles=123, cell_raw=3320,
        )
        parsed = parse_eg4_frame(frame)
        self.assertEqual(parsed.voltage, 13.3)
        self.assertEqual(parsed.current, -10.0)
        self.assertEqual(parsed.temp_env, 25)
        self.assertEqual(parsed.soh, 100)
        self.assertEqual(parsed.soc, 95)
        self.assertEqual(parsed.status, 0)
        self.assertEqual(parsed.cycles, 123)
        self.assertAlmostEqual(parsed.cell_voltages[0], 3.32, places=5)

    def test_crc_failure(self):
        frame = bytearray(83)
        frame[0:3] = bytes.fromhex("01034E")
        struct.pack_into("<H", frame, 81, 0x1234)
        with self.assertRaises(ValueError):
            parse_eg4_frame(bytes(frame))


# ---------------------------------------------------------------------------
# Protocol contracts — every field at its spec-defined byte offset
# ---------------------------------------------------------------------------

class TestEG4ProtocolContracts(unittest.TestCase):

    def test_voltage_at_bytes_3_4_uint16_be_div100(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(voltage_raw=1456)).voltage, 14.56, places=5)

    def test_current_positive_charging(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(current_raw=250)).current, 25.0, places=5)

    def test_current_negative_discharging(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(current_raw=-100)).current, -10.0, places=5)

    def test_current_zero_boundary(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(current_raw=0)).current, 0.0)

    def test_current_max_negative_int16(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(current_raw=-32768)).current, -3276.8, places=1)

    def test_cell_1_at_bytes_7_8_uint16_be_div1000(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(cell_raw=3350)).cell_voltages[0], 3.350, places=5)

    def test_cell_16_at_bytes_37_38(self):
        self.assertAlmostEqual(parse_eg4_frame(make_eg4_frame(cell_raw=3200)).cell_voltages[15], 3.200, places=5)

    def test_temp_env_at_byte_44_raw_int8(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(temp_env=38)).temp_env, 38)

    def test_soh_at_byte_50(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(soh=87)).soh, 87)

    def test_soc_at_byte_52(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(soc=63)).soc, 63)

    def test_status_at_byte_54(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(status=0b00000110)).status, 0b00000110)

    def test_cycles_at_bytes_73_74_uint16_be(self):
        self.assertEqual(parse_eg4_frame(make_eg4_frame(cycles=999)).cycles, 999)

    def test_frame_must_be_83_bytes(self):
        with self.assertRaises(ValueError):
            parse_eg4_frame(bytes(82))

    def test_bad_crc_raises(self):
        frame = bytearray(make_eg4_frame())
        frame[81] ^= 0xFF
        with self.assertRaises(ValueError):
            parse_eg4_frame(bytes(frame))

    def test_crc_covers_first_81_bytes(self):
        frame = bytearray(make_eg4_frame())
        frame[3] ^= 0x01
        with self.assertRaises(ValueError):
            parse_eg4_frame(bytes(frame))

    def test_cell_voltages_list_length_is_16(self):
        self.assertEqual(len(parse_eg4_frame(make_eg4_frame()).cell_voltages), 16)

    def test_raw_hex_is_hex_string_of_frame(self):
        frame = make_eg4_frame()
        self.assertEqual(parse_eg4_frame(frame).raw_hex, frame.hex())


# ---------------------------------------------------------------------------
# CRC utility
# ---------------------------------------------------------------------------

class TestCRC(unittest.TestCase):
    def test_poll_command_crc(self):
        # Known value: crc16_modbus("010300000027") == 0xD005
        data = bytes.fromhex("010300000027")
        self.assertEqual(crc16_modbus(data), 0xD005)

    def test_crc_detects_single_bit_flip(self):
        frame = make_eg4_frame()
        original_crc = crc16_modbus(frame[:81])
        flipped = bytearray(frame[:81])
        flipped[10] ^= 0x01
        self.assertNotEqual(crc16_modbus(bytes(flipped)), original_crc)


if __name__ == "__main__":
    unittest.main()
