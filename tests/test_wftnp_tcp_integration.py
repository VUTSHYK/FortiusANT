"""Real TCP regression for FortiusANT's WFTNP transport."""
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pythoncode"))

from wftnp import Endpoint, WftnpClient
from ftmsBridge import TrainerMode
from wftnpTransport import CONTROL_POINT, INDOOR_BIKE_DATA, WftnpFTMSTransport


class TestWftnpTcpIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_ownership_and_telemetry(self):
        transport = WftnpFTMSTransport(port=0, interval=0.02)
        await transport.start()
        a = WftnpClient(Endpoint("127.0.0.1", transport.server.port),
                        heartbeat_interval=None)
        b = WftnpClient(Endpoint("127.0.0.1", transport.server.port),
                        heartbeat_interval=None)
        try:
            await a.start()
            await b.start()
            await a.wait_ready(timeout=3)
            await b.wait_ready(timeout=3)
            async with (
                await a.subscribe(CONTROL_POINT) as a_control,
                await b.subscribe(CONTROL_POINT) as b_control,
                await a.subscribe(INDOOR_BIKE_DATA) as a_bike,
                await b.subscribe(INDOOR_BIKE_DATA) as b_bike,
            ):
                transport.bridge.set_trainer_data(25, 90, 200)
                self.assertTrue((await asyncio.wait_for(anext(a_bike), 3)).value)
                self.assertTrue((await asyncio.wait_for(anext(b_bike), 3)).value)
                await a.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(a_control), 3)).value,
                                 b"\x80\x00\x01")
                await b.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x00\x05")
                await b.write_characteristic(CONTROL_POINT, b"\x05\xfa\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x05\x05")
                self.assertIsNone(transport.bridge.take_command())
                await a.write_characteristic(CONTROL_POINT, b"\x05\xfa\x00")
                self.assertEqual((await asyncio.wait_for(anext(a_control), 3)).value,
                                 b"\x80\x05\x01")
                command = transport.bridge.take_command()
                self.assertEqual(command.mode, TrainerMode.POWER)
                self.assertEqual(command.target_power_watts, 250)
                await a.stop()
                async with asyncio.timeout(3):
                    while transport.control_point.has_control:
                        await asyncio.sleep(0.01)
                await b.write_characteristic(CONTROL_POINT, b"\x00")
                self.assertEqual((await asyncio.wait_for(anext(b_control), 3)).value,
                                 b"\x80\x00\x01")
        finally:
            await a.stop()
            await b.stop()
            await transport.stop()
