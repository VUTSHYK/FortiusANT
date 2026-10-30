"""Tests for the WFTNP transport boundary without network dependencies."""

import asyncio
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from ftmsBridge import TrainerTelemetry
from wftnpTransport import WftnpFTMSTransport, encode_indoor_bike_data, encode_heart_rate


class TestWftnpTransport(unittest.TestCase):
    def test_bike_data_units_and_flags(self):
        data = encode_indoor_bike_data(TrainerTelemetry(31.25, 87.5, 235))
        self.assertEqual(struct.unpack("<HHHh", data), (0x0044, 3125, 175, 235))

    def test_heart_rate_measurement(self):
        self.assertEqual(encode_heart_rate(TrainerTelemetry(0, 0, 0, 147)), b"\x00\x93")
        self.assertEqual(encode_heart_rate(TrainerTelemetry(0, 0, 0, 0)), b"\x00\x00")

    def test_power_is_signed(self):
        data = encode_indoor_bike_data(TrainerTelemetry(0, 0, -20))
        self.assertEqual(struct.unpack("<HHHh", data)[3], -20)

    def test_control_write_requires_control_ownership(self):
        transport = WftnpFTMSTransport()
        self.assertIsNone(asyncio.run(transport._handle_control_write(object(), bytes((0x05, 230, 0)))))
        self.assertIsNone(transport.bridge.take_command())

    def test_control_write_is_delegated(self):
        seen = []
        transport = WftnpFTMSTransport(on_control_write=lambda data: (seen.append(data), b"\x80\x00\x01")[1])
        asyncio.run(transport._handle_control_write(object(), b"\x00"))
        self.assertEqual(seen, [b"\x00"])

    def test_control_response_is_notified(self):
        transport = WftnpFTMSTransport()
        seen = []

        class FakeServer:
            async def notify_connection(self, connection, uuid, value):
                seen.append((connection, uuid, value))

        transport.server = FakeServer()
        connection = object()
        asyncio.run(transport._handle_control_write(connection, b"\x00"))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], connection)
        self.assertEqual(seen[0][2], b"\x80\x00\x01")

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            WftnpFTMSTransport(interval=0)


if __name__ == "__main__":
    unittest.main()
