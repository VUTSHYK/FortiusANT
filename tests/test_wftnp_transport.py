"""Tests for the WFTNP transport boundary without network dependencies."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from ftmsBridge import TrainerTelemetry
from wftnpTransport import WftnpFTMSTransport, encode_indoor_bike_data


class TestWftnpTransport(unittest.TestCase):
    def test_bike_data_units_and_flags(self):
        data = encode_indoor_bike_data(TrainerTelemetry(31.25, 87.5, 235))
        self.assertEqual(struct.unpack("<HHHh", data), (0x0044, 3125, 175, 235))

    def test_power_is_signed(self):
        data = encode_indoor_bike_data(TrainerTelemetry(0, 0, -20))
        self.assertEqual(struct.unpack("<HHHh", data)[3], -20)

    def test_control_write_requires_handler(self):
        transport = WftnpFTMSTransport()
        with self.assertRaises(ValueError):
            transport._handle_control_write(b"\x05\xe6\x00")

    def test_control_write_is_delegated(self):
        seen = []
        transport = WftnpFTMSTransport(on_control_write=lambda data: seen.append(data))
        transport._handle_control_write(b"\x00")
        self.assertEqual(seen, [b"\x00"])

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            WftnpFTMSTransport(interval=0)


if __name__ == "__main__":
    unittest.main()
