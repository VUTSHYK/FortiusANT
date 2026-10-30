"""Tests for the WFTNP transport boundary without network dependencies."""

import asyncio
import struct
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
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

    def test_registered_ftms_services_and_values(self):
        """Exercise start(), not just the standalone byte encoders."""
        from wftnpTransport import (FTMS_SERVICE, FITNESS_MACHINE_FEATURE,
            SUPPORTED_POWER_RANGE, HEART_RATE_SERVICE, HEART_RATE_MEASUREMENT,
            INDOOR_BIKE_DATA, CONTROL_POINT)

        class Props:
            READ = 1
            WRITE = 2
            NOTIFY = 4
            INDICATE = 8

        class Characteristic:
            def __init__(self, uuid, *, properties, value=None,
                         on_write_with_connection=None):
                self.uuid = uuid
                self.properties = properties
                self.value = value
                self.on_write_with_connection = on_write_with_connection

        class Service:
            def __init__(self, uuid, characteristics):
                self.uuid = uuid
                self.characteristics = characteristics

        class Server:
            def __init__(self, **kwargs):
                self.services = kwargs["services"]
                self.port = 36866

            async def start(self):
                pass

            async def stop(self):
                pass

        fake_wftnp = SimpleNamespace(
            CharacteristicProperties=Props,
            CharacteristicSpec=Characteristic,
            ServiceSpec=Service,
            WftnpServer=Server,
        )

        async def check():
            transport = WftnpFTMSTransport(interval=3600)
            with patch.dict(sys.modules, {"wftnp": fake_wftnp}):
                await transport.start()
                try:
                    services = {svc.uuid: svc for svc in transport.server.services}
                    self.assertEqual(set(services), {FTMS_SERVICE, HEART_RATE_SERVICE})
                    ftms = {ch.uuid: ch for ch in services[FTMS_SERVICE].characteristics}
                    self.assertEqual(set(ftms), {
                        FITNESS_MACHINE_FEATURE, SUPPORTED_POWER_RANGE,
                        INDOOR_BIKE_DATA, CONTROL_POINT,
                    })
                    self.assertEqual(ftms[FITNESS_MACHINE_FEATURE].value,
                                     bytes.fromhex("02 40 00 00 08 20 00 00"))
                    self.assertEqual(ftms[SUPPORTED_POWER_RANGE].value,
                                     bytes.fromhex("00 00 e8 03 01 00"))
                    self.assertEqual(ftms[CONTROL_POINT].properties,
                                     Props.WRITE | Props.INDICATE)
                    self.assertTrue(ftms[CONTROL_POINT].on_write_with_connection)
                    heart = services[HEART_RATE_SERVICE].characteristics
                    self.assertEqual(len(heart), 1)
                    self.assertEqual(heart[0].uuid, HEART_RATE_MEASUREMENT)
                    self.assertEqual(heart[0].properties, Props.NOTIFY)
                    self.assertEqual(heart[0].value, bytes((0,0)))
                finally:
                    await transport.stop()

        asyncio.run(check())

    def test_heart_rate_clamping(self):
        self.assertEqual(encode_heart_rate(TrainerTelemetry(0, 0, 0, 300)),
                         bytes((0,255)))
        self.assertEqual(encode_heart_rate(TrainerTelemetry(0, 0, 0, -5)),
                         bytes((0,0)))

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            WftnpFTMSTransport(interval=0)


if __name__ == "__main__":
    unittest.main()
